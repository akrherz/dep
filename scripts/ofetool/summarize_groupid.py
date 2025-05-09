"""Summarize OFE results to support OFETool.

Via one-time processing, each HUC12 in DEP has a oferesults CSV file.  We want
to summarize and supplement these files to support the OFETool.  We will
use a methodology of:

1. If we have 10 samples locally, we are golden.
2. We will look spatially 100km around the HUC12 centroid and summarize any
   other groupids with at least 100 samples.

"""

import os
from typing import Optional

import click
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

LOG = logger()


def summarize(ofedf: pd.DataFrame, groupid, is_local: bool) -> dict:
    """Do the summarization."""
    popdf: pd.DataFrame = ofedf[ofedf["groupid"] == groupid]
    rstats = popdf["runoff[mm/yr]"].describe()
    lstats = popdf["ofe_loss[t/a/yr]"].describe()
    row0 = popdf.iloc[0]
    return {
        "groupid": groupid,
        "is_local": is_local,
        "n": len(popdf),
        "slope_reclass": row0["slope_reclass"],
        "kw_reclass": row0["kw_reclass"],
        "tillage_code_2023": row0["tillage_code_2023"],
        "genlanduse": row0["genlanduse"],
        "isag": row0["isag"],
        "runoff[mm/yr]": rstats["mean"],
        "runoff[mm/yr]_min": rstats["min"],
        "runoff[mm/yr]_max": rstats["max"],
        "runoff[mm/yr]_std": rstats["std"],
        "runoff[mm/yr]_25": rstats["25%"],
        "runoff[mm/yr]_median": rstats["50%"],
        "runoff[mm/yr]_75": rstats["75%"],
        "ofe_loss[t/a/yr]": lstats["mean"],
        "ofe_loss[t/a/yr]_min": lstats["min"],
        "ofe_loss[t/a/yr]_max": lstats["max"],
        "ofe_loss[t/a/yr]_std": lstats["std"],
        "ofe_loss[t/a/yr]_25": lstats["25%"],
        "ofe_loss[t/a/yr]_median": lstats["50%"],
        "ofe_loss[t/a/yr]_75": lstats["75%"],
    }


def process_huc12_results(huc12, oferesults, scenario: int):
    """Do the processing of a single HUC12."""
    results = []
    local_oferesults = oferesults[oferesults["huc12"] == huc12]
    # Figure out which local groupids we have 10 samples for
    local_groupids = local_oferesults.groupby("groupid").size()
    local_groupids = local_groupids[local_groupids >= 10].index.values
    LOG.info("Found %s local groupids with 10 samples", len(local_groupids))
    for groupid in local_groupids:
        results.append(summarize(local_oferesults, groupid, True))
    groupids = oferesults.groupby("groupid").size()
    for groupid in groupids.index:
        if groupids[groupid] < 100:
            continue
        results.append(summarize(oferesults, groupid, False))

    resultdf = pd.DataFrame(results)
    resultdf.to_csv(
        f"/i/{scenario}/ofe/{huc12[:8]}/{huc12[8:]}/ofetool_{huc12}.csv",
        index=False,
        float_format="%.4f",
    )


def do_huc12(pgconn, huc12, scenario: int):
    """Process a single HUC12."""
    domaindf = pd.read_sql(
        sql_helper("""
    select huc_12 from huc12 where scenario = :scenario and st_distance(geom,
        (select st_centroid(geom) from huc12 where huc_12 = :huc12 and
         scenario = :scenario)) < 100_000
             """),
        pgconn,
        params={"huc12": huc12, "scenario": scenario},
    )
    LOG.info("Found %s neighboring HUC12s for %s", len(domaindf), huc12)

    files = [
        f"/i/{scenario}/ofe/{huc[:8]}/{huc[8:]}/oferesults_{huc}.csv"
        for huc in domaindf["huc_12"]
    ]
    oferesults = pd.concat(
        (
            pd.read_csv(fn, dtype={"huc12": str, "ofe": int})
            for fn in files
            if os.path.isfile(fn)
        ),
        ignore_index=True,
    )
    # Only consider top of flowpath results
    oferesults = oferesults[oferesults["ofe"] == 1]
    process_huc12_results(huc12, oferesults, scenario)


@click.command()
@click.option("--scenario", default=0, type=int, help="Scenario to process")
@click.option("--huc12", type=str, help="Run for a single HUC12")
def main(scenario: int, huc12: Optional[str]):
    """Go Main Go."""
    with get_sqlalchemy_conn("idep") as pgconn:
        huc12df = pd.read_sql(
            sql_helper("select huc_12 from huc12 where scenario = :scenario"),
            pgconn,
            params={"scenario": scenario},
        )
        progress = tqdm(huc12df["huc_12"].values)
        for _huc12 in progress:
            progress.set_description(_huc12)
            if huc12 is not None and huc12 != _huc12:
                continue
            do_huc12(pgconn, _huc12, scenario)


if __name__ == "__main__":
    main()
