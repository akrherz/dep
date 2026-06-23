"""Proctor script for running the SWEEP model.

See dailyerosion/dep#36 for generally more details.

I looked at the measured data again, and realized that a better date would
be June 1 or June 2, 2018; or potentially June 10, 2018.

The lat-long for the site is:
Latitude: 46.78
Longitude: -100.95

Output fields (kg/m2)
-------------
  - total soil loss
  - saltation/creep soil loss
  - suspended soil loss
  - PM10 soil loss
  - PM2.5 soil loss
"""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from multiprocessing import Pool

import click
import numpy as np
import pandas as pd
import requests
from enqueue_wepp_jobs import GRAPH_HUC12
from pyiem.database import (
    get_sqlalchemy_conn,
    sql_helper,
    with_sqlalchemy_conn,
)
from pyiem.util import logger
from sqlalchemy.engine import Connection
from tqdm import tqdm

from dailyerosion.io.man import man2df, read_man

LOG = logger()
IEMRE = "http://mesonet.agron.iastate.edu/iemre/hourly"


def run_command(cmd: list[str]) -> bool:
    """Common command running logic."""
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as proc:
        (stdout, stderr) = proc.communicate()
        if proc.returncode != 0:
            LOG.error(
                "Command %s failed with %s\n%s",
                " ".join(cmd),
                stdout.decode("utf-8"),
                stderr.decode("utf-8"),
            )
            return False
    return True


def get_wind_obs(dt: datetime, lon: float, lat: float) -> list[float]:
    """Get what we need from IEMRE."""
    # Hopefully the two decimal degrees results in some caching
    uri = f"{IEMRE}/{dt:%Y-%m-%d}/{lat:.2f}/{lon:.2f}/json"
    attempts = 0
    res = {"data": []}
    while attempts < 3:
        try:
            resp = requests.get(uri, timeout=30)
            resp.raise_for_status()
            res = resp.json()
            break
        except Exception as exp:
            print(uri)
            LOG.exception(exp)
        attempts += 1
        if attempts == 3:
            LOG.warning("Failed to get %s, returning 1s", uri)
            return [1.0] * 24
    hourly = []
    for entry in res["data"]:
        try:
            vel = (entry["uwnd_mps"] ** 2 + entry["vwnd_mps"] ** 2) ** 0.5
        except Exception:
            vel = 1.0
        hourly.append(vel)
    for _i in range(len(hourly), 24):
        hourly.append(1.0)
    return hourly


def compute_crop(manfn: str, year: int) -> str:
    """Compute the crop code used for magic.R in sweep workflow."""
    try:
        mandf = man2df(read_man(manfn), 2007)
    except Exception as exp:
        LOG.info("%s generated %s", manfn, exp)
        return "0"
    cropname = (
        mandf.query(f"year == {year} and ofe == 1")
        .iloc[0]["crop_name"]
        .lower()
    )
    cropcode = "0"
    if cropname.startswith("Cor"):
        cropcode = "C"
    elif cropname.startswith("Soy"):
        cropcode = "B"
    return cropcode


def workflow(arg):
    """Do what we need to do."""
    (idx, row) = arg
    # 1. Replace wind information in each sweepin file
    sweepinfn = (
        f"/i/{row['scenario']}/sweepin/{row['huc12_code'][:8]}/"
        f"{row['huc12_code'][8:12]}/"
        f"{row['huc12_code']}_{row['huc12_fpath_num']}.sweepin"
    )
    cropcode = compute_crop(
        sweepinfn.replace("sweepin", "man"),
        row["date"].year,
    )
    # Compute the management df to get the crop code needed for downstream
    if not os.path.isfile(sweepinfn):
        LOG.warning("%s does not exist, copying template", sweepinfn)
        shutil.copyfile("sweepin_template.txt", sweepinfn)
    sweepoutfn = sweepinfn.replace("sweepin", "sweepout")
    # sweep arbitarily sets the erod output file to be the same as the
    # sweepin, but with a erod extension.
    erodfn = sweepinfn.replace(".sweepin", ".erod")
    windobs = get_wind_obs(row["date"], row["lon"], row["lat"])
    with open(sweepinfn, "r", encoding="utf-8") as fh:
        lines = list(fh.readlines())
    found = False
    for linenum, line in enumerate(lines):
        if not found and line.find(" awu(i)") > -1:
            found = True
            continue
        if found and not line.startswith("#"):
            for i in range(4):
                sl = slice(i * 6, (i + 1) * 6)
                lines[linenum + i] = (
                    " ".join([str(round(x, 2)) for x in windobs[sl]]) + "\n"
                )
            break
    with open(sweepinfn, "w", encoding="utf-8") as fh:
        fh.write("".join(lines))
    # 2. Run Rscript to replace grph file content
    cmd = [
        "Rscript",
        "--vanilla",
        "magic.R",
        sweepinfn,
        sweepinfn.replace("sweepin", "grph"),
        sweepinfn.replace("sweepin", "sol"),
        f"{row['date'].year}",
        sweepinfn.replace("sweepin", "rot")[:-4] + "_1.txt",
        f"{row['date']:%j}",
        f"{cropcode}",
    ]
    if not run_command(cmd):
        return None, None
    # 3. Run sweep with given sweepin file, writing to sweepout
    cmd = [
        "/opt/dep/bin/sweep",
        f"-i{sweepinfn}",  # yuck
        "-Erod",
    ]
    if not run_command(cmd):
        return None, None
    # Move the erod file into the sweepout directory
    shutil.move(erodfn, sweepoutfn)
    # 4. Harvest the result and profit.
    erosion = None
    with open(sweepoutfn, encoding="utf-8") as fh:
        tokens = fh.read().strip().split()
        # total soil loss, saltation loss, suspension loss, PM10 loss
        # TODO: units
        erosion = float(tokens[0])
    return idx, erosion


@with_sqlalchemy_conn("dep")
def write_database(
    scenario: int,
    dt: datetime,
    results: pd.DataFrame,
    conn: Connection | None = None,
):
    """Write things to the database."""
    res = conn.execute(
        sql_helper("""
                delete from wind_results_by_huc12 where scenario_id = :scenario
                and valid = :dt
        """),
        {"scenario": scenario, "dt": dt},
    )
    LOG.info("deleted %s result rows", res.rowcount)
    for huc12, row in results.iterrows():
        # Life choice to not store zeros
        if row[("erosion", "mean")] == 0:
            continue
        conn.execute(
            sql_helper("""
            insert into wind_results_by_huc12
            (scenario_id, valid, huc_12, avg_loss) VALUES
            (:scenario, :valid, :huc12, :avg_loss)
                    """),
            {
                "scenario": scenario,
                "valid": dt,
                "huc12": huc12,
                "avg_loss": row[("erosion", "mean")],
            },
        )
    conn.commit()


@click.command()
@click.option("--scenario", "-s", default=0, type=int, help="Scenario to run")
@click.option("--date", "dt", type=click.DateTime(), help="Date to run")
@click.option("--workers", type=int, default=4, help="Number of workers")
def main(scenario: int, dt: datetime, workers: int):
    """Go Main Go."""
    with get_sqlalchemy_conn("dep") as conn:
        df = pd.read_sql(
            sql_helper("""
            SELECT huc12_code, huc12_fpath_num, scenario_id,
            ST_x(ST_Transform(ST_PointN(p.geom, 1), 4326)) as lon,
            ST_y(ST_Transform(ST_PointN(p.geom, 1), 4326)) as lat
            from flowpath p JOIN huc12 h on (p.huc12_id = h.huc12_id)
            where p.scenario_id = :scenario
            and h.huc12_code = ANY(:huc12s)
        """),
            conn,
            params={"scenario": scenario, "huc12s": GRAPH_HUC12},
            index_col=None,
        )
    df["date"] = pd.Timestamp(dt)
    df["erosion"] = np.nan
    LOG.info("found %s flowpaths to run for %s", len(df.index), dt)
    jobs = list(df.iterrows())
    # hard coded CPU count for now as using them all is too much
    LOG.info("Starting %s workers", workers)
    with Pool(workers) as pool:
        progress = tqdm(
            pool.imap_unordered(workflow, jobs),
            total=len(df.index),
            disable=not sys.stdout.isatty(),
        )
        for idx, erosion in progress:
            if erosion is None:
                break
            df.at[idx, "erosion"] = erosion

    if df["erosion"].isna().any():
        LOG.warning("Some jobs failed, not writing to database")
        return

    results = df[["huc12_code", "erosion"]].groupby("huc12_code").describe()
    LOG.warning(results[("erosion", "mean")])
    write_database(scenario, dt, results)


if __name__ == "__main__":
    main()
