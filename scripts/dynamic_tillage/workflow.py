"""Dynamic Tillage Workflow.

On a given date between 11 April and 10 June, we will attempt to plant or till
fields within a HUC12.  We run this script at 9 PM and needs to be done by
about 12:30 AM.

The `bootstrap_year.py` script creates database entries with default June
dates and dates that may not be needed given the actual tillage in play.

"""

import os
import shutil
import subprocess
import tempfile
import threading
from datetime import date, datetime, timedelta
from multiprocessing import cpu_count
from multiprocessing.pool import Pool

import click
import geopandas as gpd
import numpy as np
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.iemre import daily_offset, get_daily_mrms_ncname
from pyiem.util import archive_fetch, logger, ncopen
from tqdm import tqdm

from dailyerosion.workflows.dyntillage import do_huc12

LOG = logger()
CPU_COUNT = min([4, cpu_count() / 2])
HUC12STATUSDIR = "/mnt/idep2/data/huc12status"
PROJDIR = "/opt/dep/prj2wepp"
EXE = f"{PROJDIR}/prj2wepp"
# Quorum for OFE fraction within HUC12 to be below plastic limit
OFE_PL_QUORUM = 0.5


def setup_thread():
    """Ensure that we have temp folders and sym links constructed."""
    tmpdir = tempfile.mkdtemp()
    # Store the reference for later use
    threading.current_thread().tmpdir = tmpdir
    os.makedirs(f"{tmpdir}/wepp/runs", exist_ok=True)
    for dn in ["data", "output", "wepp", "weppwin"]:
        subprocess.call(
            ["ln", "-s", f"{PROJDIR}/wepp/{dn}"], cwd=f"{tmpdir}/wepp"
        )


def prj2wepp(huc12, fpath):
    """Run prj2wepp."""
    mydir = threading.current_thread().tmpdir
    fn = f"/i/0/prj/{huc12[:8]}/{huc12[8:]}/{huc12}_{fpath:.0f}.prj"
    testfn = os.path.basename(fn)[:-4]
    cmd = [EXE, fn, testfn, f"{mydir}/wepp", "no"]
    with subprocess.Popen(
        cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=mydir
    ) as proc:
        # Need to block the above
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        if not os.path.isfile(f"{mydir}/{testfn}.man"):
            print("bzzzz", testfn)
            print(" ".join(cmd))
            print(stdout.decode("ascii"))
            print(stderr.decode("ascii"))
            return False
        # This generates .cli, .man, .run, .slp, .sol
        # We need the .man , .slp , .sol from this process
        # slp is generated in flowpath2prj
        for suffix in ["man", "sol"]:
            shutil.copyfile(
                f"{mydir}/{testfn}.{suffix}", fn.replace("prj", suffix)
            )
        for suffix in ["cli", "man", "run", "slp", "sol"]:
            os.unlink(f"{mydir}/{testfn}.{suffix}")
    return True


def do_edit_rotfile(year, huc12: str, row: dict):
    """Edit up our .rot files."""
    yearindex = str(year - 2007 + 1)
    rotfn = (
        f"/i/0/rot/{huc12[:8]}/{huc12[8:]}/"
        f"{huc12}_{row['huc12_fpath_num']:.0f}_{row['ofe']:.0f}.rot"
    )
    with open(rotfn, encoding="ascii") as fh:
        lines = fh.readlines()
    dates = [row["till1"], row["till2"], row["till3"], row["plant"]]
    for i, line in enumerate(lines):
        pos = line.find(f" {yearindex} ")  # false positives
        if pos == -1:
            continue
        tokens = line.split()
        if (
            tokens[2] == yearindex
            and int(tokens[0]) < 7
            and tokens[4].startswith(("Tillage", "Plant"))
        ):
            thisdt = row["plant"]
            if tokens[4] == "Tillage":
                thisdt = dates.pop(0)
            if pd.isna(thisdt):
                thisdt = row["plant"]
            lines[i] = f"{thisdt:%-m %-d} {yearindex} {' '.join(tokens[3:])}\n"
    with open(rotfn, "w", encoding="ascii") as fh:
        fh.write("".join(lines))


def estimate_soiltemp(huc12df: pd.DataFrame, dt: datetime):
    """Write mean GFS soil temperature C into huc12df."""
    # Look back from 12z at most 24 hours for a file to use
    z12 = datetime(dt.year, dt.month, dt.day, 12)
    for offset in range(0, 25, 6):
        now = z12 - timedelta(hours=offset)
        ppath = f"{now:%Y/%m/%d}/model/gfs/gfs_{now:%Y%m%d%H}_iemre.nc"
        with archive_fetch(ppath) as ncfn:
            if ncfn is None:
                continue
            LOG.info("Using GFS@%s for soil temperature", now)
            with ncopen(ncfn) as nc:
                tmin = np.min(nc.variables["tsoil"][1:7], axis=0) - 273.15
                tavg = np.mean(nc.variables["tsoil"][1:7], axis=0) - 273.15
                tmax = np.max(nc.variables["tsoil"][1:7], axis=0) - 273.15
                y = np.digitize(huc12df["lat"].values, nc.variables["lat"][:])
                x = np.digitize(huc12df["lon"].values, nc.variables["lon"][:])
                for i, idx in enumerate(huc12df.index.values):
                    # The crude GFS may not have a soil temperature at the
                    # given grid cell, so we move left and down to find one.
                    gfs_offset = 0
                    while gfs_offset < 6 and tmin.mask:
                        if not tmin.mask[y[i] - gfs_offset, x[i] - gfs_offset]:
                            break
                        gfs_offset = gfs_offset + 1
                    if gfs_offset > 0:
                        LOG.info("Applying offset %s", gfs_offset)
                    huc12df.at[idx, "tsoil_min"] = tmin[
                        y[i] - gfs_offset, x[i] - gfs_offset
                    ]
                    huc12df.at[idx, "tsoil_avg"] = tavg[
                        y[i] - gfs_offset, x[i] - gfs_offset
                    ]
                    huc12df.at[idx, "tsoil_max"] = tmax[
                        y[i] - gfs_offset, x[i] - gfs_offset
                    ]
                break


def estimate_rainfall(huc12df: pd.DataFrame, dt: date):
    """Figure out our rainfall estimate."""
    tidx = daily_offset(dt)
    ncfn = get_daily_mrms_ncname(dt.year)
    depncfn = ncfn.replace("daily", "dep")
    if os.path.isfile(depncfn):
        ncfn = depncfn
        tidx = daily_offset(dt) - daily_offset(dt.replace(month=4, day=11))
    LOG.info("Using %s[tidx:%s] for precip", ncfn, tidx)
    with ncopen(ncfn) as nc:
        p01d = nc.variables["p01d"][tidx].filled(0)
        south = nc.variables["lat"][0]
        west = nc.variables["lon"][0]
    for idx, row in huc12df.iterrows():
        y = int((row["lat"] - south) * 100.0)
        x = int((row["lon"] - west) * 100.0)
        huc12df.at[idx, "precip_mm"] = p01d[y, x]


def job(arg: list[date, str, bool, bool]):
    """Do the job."""
    dt, huc12, edit_rotfile, run_prj2wepp = arg
    with get_sqlalchemy_conn("dep") as conn:
        fields, planted, tilled = do_huc12(conn, 0, dt, huc12)
    # A HUC12 without any C or B, likely
    if not edit_rotfile or "ofe" not in fields.columns:
        return huc12, planted, tilled
    # Now we need to figure out which files need edited
    fields = fields[fields["ofe"].notna()]
    if f"{dt:%m%d}" != "0614":
        fields = fields[fields["operation_done"]]

    for _, row in fields.iterrows():
        do_edit_rotfile(dt.year, huc12, row)
    if run_prj2wepp and not fields.empty:
        for fpath in fields["fpath"].unique():
            prj2wepp(huc12, fpath)

    return huc12, planted, tilled


@click.command()
@click.option("--scenario", type=int, default=0)
@click.option("--date", "dt", type=click.DateTime(), required=True)
@click.option("--huc12", type=str, required=False)
@click.option("--edit_rotfile", "edr", type=bool, default=False)
@click.option("--run_prj2wepp", type=bool, default=False)
def main(scenario, dt, huc12, edr, run_prj2wepp):
    """Go Main Go."""
    # Deal with dates not datetime
    dt = dt.date()
    LOG.info("Processing %s for scenario %s", dt, scenario)
    huc12_filter = "" if huc12 is None else " and huc12_code = :huc12"
    with get_sqlalchemy_conn("dep") as conn:
        huc12df = gpd.read_postgis(
            sql_helper(
                """
            SELECT geom, huc12_code,
            false as limited_by_precip,
            false as limited_by_soiltemp,
            false as limited_by_soilmoisture,
            false as limited,
            99.9 as tsoil_min,
            99.9 as tsoil_avg,
            99.9 as tsoil_max,
            ST_x(st_transform(st_centroid(geom), 4326)) as lon,
            ST_y(st_transform(st_centroid(geom), 4326)) as lat
            from huc12 where scenario_id = :scenario {huc12_filter}
            """,
                huc12_filter=huc12_filter,
            ),
            conn,
            params={"scenario": scenario, "huc12": huc12},
            geom_col="geom",
            index_col="huc12_code",
        )
    huc12df["tilled"] = pd.NA
    huc12df["planted"] = pd.NA

    # After June 10th, we mud it in.
    if f"{dt:%m%d}" < "0610":
        # Estimate today's rainfall so to delay triggers
        estimate_rainfall(huc12df, dt)
        # Any HUC12 over 10mm gets skipped
        huc12df.loc[huc12df["precip_mm"] > 9.9, "limited_by_precip"] = True
        # Estimate soil temperature via GFS forecast
        estimate_soiltemp(huc12df, dt)
        # Any HUC12 under 6C gets skipped
        huc12df.loc[huc12df["tsoil_avg"] < 6, "limited_by_soiltemp"] = True
        # The soil moisture state is the day before
        yesterday = dt - timedelta(days=1)
        smdf = pd.read_feather(
            f"/mnt/idep2/data/smstate/{yesterday:%Y}/"
            f"smstate{yesterday:%Y%m%d}.feather"
        )
        # Only consider rows that are in either Corn or Soybean
        smdf = smdf[smdf["crop"].isin(["C", "B"])]
        for huc12, gdf in smdf.groupby("huc12"):
            if huc12 not in huc12df.index:
                continue
            # Require that fraction of modelled OFEs are below plastic limit
            # compute_smstate applies business logic, like 0.8 * PL, so
            # DO NOT do it here as well
            total_below = gdf["sw1"].lt(gdf["plastic_limit"]).sum()
            if total_below < (len(gdf.index) * OFE_PL_QUORUM):
                huc12df.at[huc12, "limited_by_soilmoisture"] = True

    # restrict to HUC12s that are not limited
    huc12df["limited"] = (
        huc12df["limited_by_precip"]
        | huc12df["limited_by_soiltemp"]
        | huc12df["limited_by_soilmoisture"]
    )
    LOG.info(
        "%s/%s HUC12s failed precip[%s], soiltemp[%s], sm[%s] check",
        huc12df["limited"].sum(),
        len(huc12df.index),
        huc12df["limited_by_precip"].sum(),
        huc12df["limited_by_soiltemp"].sum(),
        huc12df["limited_by_soilmoisture"].sum(),
    )

    # Need to run from project dir so local userdb is found
    os.chdir(PROJDIR)

    queue = []
    for huc12 in huc12df[~huc12df["limited"]].index:
        queue.append((dt, huc12, edr, run_prj2wepp))

    LOG.warning("%s processes for %s huc12s", CPU_COUNT, len(queue))
    progress = tqdm(total=len(queue), disable=not os.isatty(1))

    with Pool(CPU_COUNT, initializer=setup_thread) as pool:
        for huc12, planted, tilled in pool.imap_unordered(job, queue):
            progress.set_description(huc12)
            progress.update()
            huc12df.at[huc12, "planted"] = planted
            huc12df.at[huc12, "tilled"] = tilled

        pool.close()
        pool.join()

    LOG.warning(
        "Planted: %.1f Tilled: %.1f Limited SM: %s Precip: %s Temp: %s",
        huc12df["planted"].sum(),
        huc12df["tilled"].sum(),
        huc12df["limited_by_soilmoisture"].sum(),
        huc12df["limited_by_precip"].sum(),
        huc12df["limited_by_soiltemp"].sum(),
    )

    # save a debug output file
    mydir = f"{HUC12STATUSDIR}/{dt:%Y}"
    os.makedirs(mydir, exist_ok=True)
    if len(huc12df.index) == 1:  # Don't save when run for single huc12
        return
    huc12df.drop(columns="geom").to_feather(f"{mydir}/{dt:%Y%m%d}.feather")


if __name__ == "__main__":
    main()
