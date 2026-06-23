"""Suck in the yield data!"""

import datetime
import multiprocessing
import os
import sys
from io import StringIO

import pandas as pd
from pyiem.database import get_dbconn
from tqdm import tqdm

from dailyerosion.io.wepp import read_yld


def readfile(huc12, filename):
    """Make me a df please"""
    df = read_yld(filename)
    if df.empty:
        return None
    df["huc12"] = huc12
    df["fpath"] = filename.split("/")[-1].split("_")[-1].split(".")[0]
    return df


def find_huc12s(scenario):
    """yield a listing of huc12s with output!"""
    res = []
    for huc8 in os.listdir("/i/%s/yld" % (scenario,)):
        for huc12 in os.listdir("/i/%s/yld/%s" % (scenario, huc8)):
            res.append("/i/%s/yld/%s/%s" % (scenario, huc8, huc12))
    return res


def do_huc12(basedir):
    """ "Process this path's worth of data"""
    huc12 = "".join(basedir.split("/")[-2:])
    frames = [readfile(huc12, basedir + "/" + f) for f in os.listdir(basedir)]
    if not frames or all([f is None for f in frames]):
        return None
    return pd.concat(frames)


def main(argv):
    """Run for a given scenario and year(optional)"""
    scenario = int(argv[1])
    if len(argv) > 2:
        year = int(argv[2])
    else:
        year = datetime.date.today().year
    print(
        "harvest2database running for scenario: %s year: %s" % (scenario, year)
    )
    huc12s = find_huc12s(scenario)
    pool = multiprocessing.Pool()
    tdf = StringIO()
    for df in tqdm(
        pool.imap_unordered(do_huc12, huc12s),
        total=len(huc12s),
        disable=(not sys.stdout.isatty()),
    ):
        if df is None:
            continue
        df["scenario"] = scenario
        df2 = df[df["year"] == year]
        df2[
            [
                "scenario",
                "valid",
                "huc12",
                "fpath",
                "ofe",
                "crop",
                "yield_kgm2",
            ]
        ].to_csv(tdf, mode="a", sep="\t", index=False, header=False)

    tdf.seek(0)
    pgconn = get_dbconn("dep")
    cursor = pgconn.cursor()
    cursor.execute(
        "DELETE from harvest WHERE scenario_id = %s "
        "and valid >= %s and valid <= %s",
        (scenario, datetime.date(year, 1, 1), datetime.date(year, 12, 31)),
    )
    print("  + Deleted %s rows" % (cursor.rowcount,))
    cursor.copy_from(
        tdf,
        "harvest",
        columns=(
            "scenario_id",
            "valid",
            "huc12",
            "fpath",
            "ofe",
            "crop",
            "yield_kgm2",
        ),
    )
    print("  + Inserted %s rows" % (cursor.rowcount,))
    cursor.close()
    pgconn.commit()


if __name__ == "__main__":
    main(sys.argv)
