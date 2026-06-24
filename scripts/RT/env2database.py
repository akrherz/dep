"""My purpose in life is to harvest the WEPP env (erosion output) files

The arguments to call me require the SCENARIO to be provided, but you can
also do any of the following:

    # See usage
    python env2database.py -h
"""

import argparse
import os
import re
import sys
from datetime import date, timedelta
from multiprocessing import Pool, cpu_count

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyiem.database import get_dbconn, get_dbconnstr
from pyiem.grid.zs import CachingZonalStats
from pyiem.util import logger
from tqdm import tqdm

from dailyerosion.io.dep import read_env
from dailyerosion.util import load_scenarios

LOG = logger()
CONFIG = {"subset": False}

# Maximum precip value allowed, will alert otherwise, see dailyerosion/dep#65
PRECIP_CEILING = 750.0


def find_huc12s(scenario):
    """yield a listing of huc12s with output!"""
    if os.path.isfile("myhucs.txt"):
        LOG.warning("Using myhucs.txt to guide processing...")
        CONFIG["subset"] = True
        with open("myhucs.txt", encoding="utf-8") as fh:
            return [s.strip() for s in fh.readlines()]

    res = []
    for huc8 in os.listdir(f"/i/{scenario}/env"):
        for huc12 in os.listdir(f"/i/{scenario}/env/{huc8}"):
            res.append(huc8 + huc12)
    return res


def readfile(fn, lengths):
    """Our env reader."""
    try:
        df = read_env(fn)
    except Exception as exp:
        LOG.warning("ABORT: Attempting to read: %s resulted in: %s", fn, exp)
        return None
    key = int(fn.split("/")[-1].split(".")[0].split("_")[1])
    df["delivery"] = df["sed_del"] / lengths[key]
    return df


def determine_dates(args):
    """Convert what `argparser` provided us into a list of dates."""
    res = []
    dateformat = re.compile("^(?P<yr>[0-9]{4})-(?P<mo>[0-9]+)-(?P<dy>[0-9]+)$")
    monthformat = re.compile("^(?P<yr>[0-9]{4})-(?P<mo>[0-9]+)$")
    lastdate = date.today() - timedelta(days=1)
    for dtstr in args.date:
        # Option 1: YYYY-m-d
        m = dateformat.match(dtstr)
        if m:
            d = m.groupdict()
            dt = pd.Timestamp(
                year=int(d["yr"]), month=int(d["mo"]), day=int(d["dy"])
            )
            if dt not in res:
                res.append(dt)
            LOG.debug("conv %s to %s", dt, res[-1])
            continue
        # Option 2: all
        if dtstr == "all":
            res.extend(pd.date_range("2007/01/01", lastdate))
            LOG.debug("all dates size %s", len(res))
            continue
        # Option 3: A month's worth
        m = monthformat.match(dtstr)
        if m:
            d = m.groupdict()
            sts = date(int(d["yr"]), int(d["mo"]), 1)
            ets = sts + timedelta(days=35)
            ets = ets.replace(day=1) - timedelta(days=1)
            res.extend(pd.date_range(sts, min([lastdate, ets])))
    return res


def compute_res(df, dt: date, slopes, qc_precip):
    """Compute things"""
    allhits = slopes == len(df.index)
    slopes = float(slopes)
    # NB: code was added to WEPP to output every precipitation/runoff event,
    # so the average precip here is more accurate than before.
    return dict(
        date=dt,
        count=len(df.index),
        min_precip=(df.precip.min() if allhits else 0),
        avg_precip=(df.precip.sum() / slopes),
        max_precip=df.precip.max(),
        min_loss=(df.av_det.min() if allhits else 0),
        avg_loss=(df.av_det.sum() / slopes),
        max_loss=df.av_det.max(),
        min_runoff=(df.runoff.min() if allhits else 0),
        avg_runoff=(df.runoff.sum() / slopes),
        max_runoff=df.runoff.max(),
        min_delivery=(df.delivery.min() if allhits else 0),
        avg_delivery=(df.delivery.sum() / slopes),
        max_delivery=df.delivery.max(),
        qc_precip=qc_precip,
    )


def load_precip(dates, huc12s):
    """Compute the HUC12 spatially averaged precip

    This provides the `qc_precip` value stored in the database for each HUC12,
    so that we have complete precipitation accounting as the other database
    table fields are based on WEPP output, which does not report all precip
    events.

    Args:
      dates (list<pd.Timestamp>): the dates we need precip data for
      huc12s (list): listing of huc12s of interest, use if CONFIG['subset']

    Returns:
      dict of [date][huc12]
    """
    # 1. Build GeoPandas DataFrame of HUC12s of interest
    huc12df = gpd.GeoDataFrame.from_postgis(
        """
    SELECT huc12_code, ST_Transform(simple_geom, 4326) as geo from huc12
    WHERE scenario_id = 0
        """,
        get_dbconnstr("dep"),
        index_col="huc12_code",
        geom_col="geo",
    )
    if CONFIG["subset"]:
        huc12df = huc12df.loc[huc12s]

    czs = None
    # 2. Loop over dates
    res = {}
    progress = tqdm(dates, disable=(not sys.stdout.isatty()))
    for dt in progress:
        progress.set_description(dt.strftime("%Y-%m-%d"))
        fn = dt.strftime("/mnt/idep2/data/dailyprecip/%Y/%Y%m%d.geotiff")
        if not os.path.isfile(fn):
            LOG.info("Missing precip: %s", fn)
            for huc12 in huc12df.index.values:
                d = res.setdefault(huc12, [])
                d.append(0)
            continue
        with rasterio.open(fn, "r") as ds:
            if czs is None:
                czs = CachingZonalStats(ds.transform)
            pcp = ds.read(1) * ds.scales[0]
        # nodata here represents the value that is set to missing within the
        # source dataset!, setting to zero has strange side affects
        pcp[pcp < 0] = np.nan
        zs = czs.gen_stats(
            pcp,
            geometries=huc12df["geo"],
        )
        i = 0
        for huc12, _ in huc12df.itertuples():
            d = res.setdefault(huc12, [])
            if zs[i] is None:
                LOG.info("Missing precip: %s, aborting.", huc12)
                sys.exit(1)
            if zs[i] > PRECIP_CEILING:
                LOG.info("%s precip %.2f > QC, zeroing", huc12, zs[i])
                zs[i] = 0.0
            d.append(zs[i])
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
    from flowpath p JOIN huc12 h on (p.huc12_id = h.huc12_id) where
    p.scenario_id = %s""",
        (int(sdf.loc[scenario, "flowpath_scenario"]),),
    )
    for row in icursor:
        d = res.setdefault(row[0], {})
        d[row[1]] = row[2]
    return res


def delete_previous_entries(icursor, scenario, huc12, dates):
    """Remove whatever previous data we have for this huc12 and dates"""
    if len(dates) > 366:
        # Means we are running for 'all'
        icursor.execute(
            """
    DELETE from water_results_by_huc12 WHERE scenario_id = %s
    and huc12_id = get_huc12_id(%s, %s)
    """,
            (scenario, huc12, scenario),
        )
    else:
        icursor.execute(
            """
    DELETE from water_results_by_huc12 WHERE valid = ANY(%s) and
    scenario_id = %s and huc12_id = get_huc12_id(%s, %s)
            """,
            (dates, scenario, huc12, scenario),
        )
    return icursor.rowcount


def save_results(icursor, scenario, huc12, df, dates):
    """Save our output to the database"""
    inserts = 0
    skipped = len(dates) - len(df.index)
    for _, row in df.iterrows():
        # test both sides of the coin to see that we can indeed skip dumping
        # this date to the databse.
        if row["qc_precip"] < 0.254 and row["count"] == 0:
            skipped += 1
            continue
        inserts += 1
        icursor.execute(
            """
            INSERT into water_results_by_huc12
            (huc12_id, valid, scenario_id,
            min_precip_mm, avg_precip_mm, max_precip_mm,
            min_loss_kgm2, avg_loss_kgm2, max_loss_kgm2,
            min_runoff_mm, avg_runoff_mm, max_runoff_mm,
            min_delivery_kgm2, avg_delivery_kgm2, max_delivery_kgm2,
            qc_precip_mm) VALUES
            (get_huc12_id(%s, %s), %s, %s,
            coalesce(%s, 0.), coalesce(%s, 0.), coalesce(%s, 0.),
            coalesce(%s, 0.), coalesce(%s, 0.), coalesce(%s, 0.),
            coalesce(%s, 0.), coalesce(%s, 0.), coalesce(%s, 0.),
            coalesce(%s, 0.), coalesce(%s, 0.), coalesce(%s, 0.), %s)
        """,
            (
                huc12,
                scenario,
                row["date"],
                scenario,
                row["min_precip"],
                row["avg_precip"],
                row["max_precip"],
                row["min_loss"],
                row["avg_loss"],
                row["max_loss"],
                row["min_runoff"],
                row["avg_runoff"],
                row["max_runoff"],
                row["min_delivery"],
                row["avg_delivery"],
                row["max_delivery"],
                row["qc_precip"],
            ),
        )
    return inserts, skipped


def update_metadata(scenario, dates):
    """Update database property for this scenario."""
    pgconn = get_dbconn("dep")
    icursor = pgconn.cursor()
    maxdate = max(dates)
    pkey = f"last_date_{scenario}"
    icursor.execute(
        "SELECT value from properties where key = %s",
        (pkey,),
    )
    if icursor.rowcount == 0:
        icursor.execute(
            "INSERT into properties(key, value) values (%s, %s)",
            (pkey, maxdate.strftime("%Y-%m-%d")),
        )
    icursor.execute(
        "UPDATE properties SET value = %s WHERE key = %s and value < %s",
        (maxdate.strftime("%Y-%m-%d"), pkey, maxdate.strftime("%Y-%m-%d")),
    )
    icursor.close()
    pgconn.commit()


def do_huc12(arg):
    """Process a huc12's worth of WEPP output files"""
    scenario, huc12, lengths, dates, precip = arg
    pgconn = get_dbconn("dep")
    icursor = pgconn.cursor()
    basedir = f"/i/{scenario}/env/{huc12[:8]}/{huc12[8:]}"
    frames = [
        readfile(basedir + "/" + f, lengths) for f in os.listdir(basedir)
    ]
    if not frames or any(f is None for f in frames):
        return huc12, None, None, None
    # Push all dataframes into one
    df = pd.concat(frames)
    if df.empty:
        LOG.info("FAIL huc12: %s resulted in empty data frame", huc12)
        return huc12, None, None, None
    df = df.fillna(0)
    hillslopes = len(frames)
    rows = []
    deleted = delete_previous_entries(icursor, scenario, huc12, dates)
    for i, dt in enumerate(dates):
        # df['date'] is datetime64, so need to cast
        df2 = df[df["date"] == pd.Timestamp(dt)]
        # We have no data, any previous entries were deleted above already
        qc_precip = precip[i]
        if df2.empty and qc_precip == 0:
            continue
        # Do computation
        rows.append(compute_res(df2, dt, hillslopes, qc_precip))
    if not rows:
        icursor.close()
        pgconn.commit()
        return huc12, 0, len(dates), deleted
    # save results
    df = pd.DataFrame(rows)
    # Prevent any NaN/Inf values
    df = df.replace([np.inf, -np.inf], 0).fillna(0)
    inserts, skipped = save_results(icursor, scenario, huc12, df, dates)
    icursor.close()
    pgconn.commit()

    return huc12, inserts, skipped, deleted


def usage():
    """Create the argparse instance."""
    parser = argparse.ArgumentParser("Send WEPP env info to the database")
    parser.add_argument("-s", "--scenario", required=True, type=int)
    parser.add_argument("-d", "--date", required=True, action="append")
    return parser


def main(argv):
    """Go Main Go."""
    parser = usage()
    args = parser.parse_args(argv[1:])
    lengths = load_lengths(args.scenario)
    dates = determine_dates(args)
    huc12s = find_huc12s(args.scenario)
    precip = load_precip(dates, huc12s)
    jobs = []
    for huc12 in huc12s:
        if huc12 not in precip:
            LOG.warning("Skipping huc12 %s with no precip", huc12)
            continue
        jobs.append(
            [args.scenario, huc12, lengths[huc12], dates, precip[huc12]]
        )

    # Begin the processing work now!
    # NB: Usage of a ThreadPool here ended in tears (so slow)
    totalinserts = 0
    totalskipped = 0
    totaldeleted = 0
    with Pool(max([2, cpu_count() - 4])) as pool:
        for huc12, inserts, skipped, deleted in tqdm(
            pool.imap_unordered(do_huc12, jobs),
            total=len(jobs),
            disable=(not sys.stdout.isatty()),
        ):
            if inserts is None:
                LOG.warning("ERROR: huc12 %s returned 0 data", huc12)
                continue
            totalinserts += inserts
            totalskipped += skipped
            totaldeleted += deleted
    LOG.warning(
        "Inserts: %s skips: %s deleted: %s",
        totalinserts,
        totalskipped,
        totaldeleted,
    )
    update_metadata(args.scenario, dates)


if __name__ == "__main__":
    main(sys.argv)
