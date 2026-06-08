"""Collect the output from the saved WEPS runs."""

from datetime import date, datetime
from pathlib import Path

import click
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

LOG = logger()


@click.command()
@click.option("--all", "alldates", is_flag=True, help="Process all days.")
@click.option(
    "--date",
    "wanteddt",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Process this date",
)
def main(alldates: bool, wanteddt: datetime | None):
    """Go Main Go."""
    if not alldates and wanteddt is None:
        LOG.error("Specify either --all or a single --date")
        return
    if wanteddt is not None:
        wanteddt = wanteddt.date()
    sql = """
    select p.fpath, p.huc_12, o.field_id
    from flowpaths p, flowpath_ofes o, fields f WHERE
    p.huc_12 = '070802020102' and p.scenario = 0 and p.fid = o.flowpath and
    o.field_id = f.field_id and o.ofe = 1
    """
    with get_sqlalchemy_conn("idep") as conn:
        fieldsdf = pd.read_sql(
            sql_helper(sql),
            conn,
        )
    progress = tqdm(fieldsdf.itertuples(), total=len(fieldsdf.index))
    for row in progress:
        progress.set_description(f"Processing {row.huc_12} {row.fpath}")
        outfn = (
            Path("/i/0/weps")
            / f"{row.huc_12[:8]}"
            / f"{row.huc_12[8:]}"
            / f"{row.huc_12}_{row.fpath}.out"
        )
        if not outfn.exists():
            progress.write(f"Missing {outfn}")
            continue
        with open(outfn, "r") as fh:
            for line in fh:
                if line.find("doy") > 0:
                    continue
                tokens = line.strip().split()
                if len(tokens) < 20:
                    continue
                dt = date(int(tokens[4]), int(tokens[3]), int(tokens[2]))
                if wanteddt is not None and dt != wanteddt:
                    continue
                total_loss = float(tokens[5]) * -1.0
                if total_loss == 0:
                    continue
                progress.write(f"{outfn} {dt} {total_loss}")


if __name__ == "__main__":
    main()
