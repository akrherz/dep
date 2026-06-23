"""Dump a days worth of output to file."""

import os
import sys
from datetime import date, timedelta
from multiprocessing import Pool

import geopandas as gpd
import numpy as np
import pandas as pd
from affine import Affine
from pyiem.database import get_dbconn
from pyiem.iemre import NORTH, WEST
from pyiem.util import logger
from rasterstats import zonal_stats
from tqdm import tqdm

from dailyerosion.io.wepp import read_env
from dailyerosion.util import load_scenarios

LOG = logger()
PRECIP_AFF = Affine(0.01, 0.0, WEST, 0.0, -0.01, NORTH)
CONFIG = {"subset": False}


def find_huc12s(scenario):
    """yield a listing of huc12s with output!"""
    if os.path.isfile("myhucs.txt"):
        LOG.warning("Using myhucs.txt to guide processing...")
        CONFIG["subset"] = True
        with open("myhucs.txt") as fh:
            return [s.strip() for s in fh.readlines()]

    res = []
    for huc8 in os.listdir("/i/%s/env" % (scenario,)):
        for huc12 in os.listdir("/i/%s/env/%s" % (scenario, huc8)):
            res.append(huc8 + huc12)
    return res


def readfile(fn, lengths):
    """Our env reader."""
    df = read_env(fn)
    key = int(fn.split("/")[-1].split(".")[0].split("_")[1])
    df["fpath"] = key
    df["delivery"] = df["sed_del"] / lengths[key]
    return df


def determine_dates(argv):
    """Figure out which dates we are interested in processing"""
    res = []
    today = date.today()
    if len(argv) == 2:
        # Option 1, we have no arguments, so we assume yesterday
        res.append(today - timedelta(days=1))
    elif len(argv) == 3:
        # Option 2, we are running for an entire year, gulp
        if argv[2] == "all":
            now = date(2007, 1, 1)
            ets = date.today()
        else:
            now = date(int(argv[2]), 1, 1)
            ets = date(int(argv[2]) + 1, 1, 1)
        while now < ets:
            if now >= today:
                break
            res.append(now)
            now += timedelta(days=1)
    elif len(argv) == 4:
        # Option 3, we are running for a month
        now = date(int(argv[2]), int(argv[3]), 1)
        ets = now + timedelta(days=35)
        ets = ets.replace(day=1)
        while now < ets:
            if now >= today:
                break
            res.append(now)
            now += timedelta(days=1)
    elif len(argv) == 5:
        # Option 4, we are running for one date
        res.append(date(int(argv[2]), int(argv[3]), int(argv[4])))
    return res


def load_precip(dates, huc12s):
    """Compute the HUC12 spatially averaged precip

    This provides the `qc_precip` value stored in the database for each HUC12,
    so that we have complete precipitation accounting as the other database
    table fields are based on WEPP output, which does not report all precip
    events.

    Args:
      dates (list): the dates we need precip data for
      huc12s (list): listing of huc12s of interest, use if CONFIG['subset']

    Returns:
      dict of [date][huc12]
    """
    # 1. Build GeoPandas DataFrame of HUC12s of interest
    idep = get_dbconn("dep")
    huc12df = gpd.GeoDataFrame.from_postgis(
        """
        SELECT huc12_code, ST_Transform(simple_geom, 4326) as geo
        from huc12 WHERE scenario_id = 0
    """,
        idep,
        index_col="huc12_code",
        geom_col="geo",
    )
    if CONFIG["subset"]:
        huc12df = huc12df.loc[huc12s]
    # 2. Loop over dates
    res = {}
    for dt in tqdm(dates, disable=not sys.stdout.isatty()):
        fn = dt.strftime("/mnt/idep2/data/dailyprecip/%Y/%Y%m%d.npy")
        if not os.path.isfile(fn):
            print("Missing precip: %s" % (fn,))
            for huc12 in huc12df.index.values:
                d = res.setdefault(huc12, [])
                d.append(0)
            continue
        pcp = np.flipud(np.load(fn))
        # nodata here represents the value that is set to missing within the
        # source dataset!, setting to zero has strange side affects
        zs = zonal_stats(
            huc12df["geo"], pcp, affine=PRECIP_AFF, nodata=-1, all_touched=True
        )
        i = 0
        for huc12, _ in huc12df.itertuples():
            d = res.setdefault(huc12, [])
            d.append(zs[i]["mean"])
            i += 1
    return res


def load_lengths(scenario):
    """Build out our flowpath lengths."""
    sdf = load_scenarios()
    dep = get_dbconn("dep")
    icursor = dep.cursor()
    res = {}
    icursor.execute(
        """
        SELECT huc12_code, huc12_fpath_num, length_m
        FROM flowpath p
        JOIN huc12 h ON (p.huc12_id = h.huc12_id)
        WHERE p.scenario_id = %s
        """,
        (int(sdf.loc[scenario, "flowpath_scenario"]),),
    )
    for row in icursor:
        d = res.setdefault(row[0], {})
        d[row[1]] = row[2]
    return res


def do_huc12(arg):
    """Process a huc12's worth of WEPP output files"""
    scenario, huc12, lengths, dates, _precip = arg
    basedir = "/i/%s/env/%s/%s" % (scenario, huc12[:8], huc12[8:])
    frames = [
        readfile(basedir + "/" + f, lengths) for f in os.listdir(basedir)
    ]
    if not frames or any([f is None for f in frames]):
        return huc12, None, None, None
    # Push all dataframes into one
    df = pd.concat(frames)
    df = df.fillna(0)
    res = ""
    for _, dt in enumerate(dates):
        # df['date'] is datetime64, so need to cast
        df2 = df[df["date"].dt.date == dt]
        for _, row in df2.iterrows():
            # hillslope ID, HUC12 ID, precip, runoff, detachment, soil loss
            res += "%s,%s,%.2f,%.4f,%.4f,%.4f\n" % (
                row["fpath"],
                huc12,
                row["precip"],
                row["runoff"],
                row["av_det"],
                row["delivery"],
            )

    return res


def main(argv):
    """Go Main Go."""
    with open("output.csv", "w") as csvfp:
        csvfp.write(
            (
                "hillslope ID, HUC12 ID, precipitation, "
                "runoff, detachment, soil loss\n"
            )
        )
        scenario = int(argv[1])
        lengths = load_lengths(scenario)
        dates = determine_dates(sys.argv)
        huc12s = find_huc12s(scenario)
        precip = load_precip(dates, huc12s)
        jobs = []
        for huc12 in huc12s:
            if huc12 not in precip:
                LOG.info("Skipping huc12 %s with no precip", huc12)
                continue
            jobs.append(
                [scenario, huc12, lengths[huc12], dates, precip[huc12]]
            )

        # Begin the processing work now!
        # NB: Usage of a ThreadPool here ended in tears (so slow)
        pool = Pool()
        for res in tqdm(
            pool.imap_unordered(do_huc12, jobs),
            total=len(jobs),
            disable=(not sys.stdout.isatty()),
        ):
            csvfp.write(res)


if __name__ == "__main__":
    main(sys.argv)
