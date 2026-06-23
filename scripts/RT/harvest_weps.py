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
    select p.huc12_fpath_num, h.huc12_code, o.field_id
    from flowpath p
    JOIN flowpath_ofe o ON (p.flowpath_id = o.flowpath_id)
    JOIN fields f ON (o.field_id = f.field_id)
    JOIN huc12 h on (p.huc12_id = h.huc12_id) WHERE
    p.scenario_id = 0 and o.ofe = 1
    """
    with get_sqlalchemy_conn("dep") as conn:
        fieldsdf = pd.read_sql(
            sql_helper(sql),
            conn,
        )
    progress = tqdm(fieldsdf.itertuples(), total=len(fieldsdf.index))
    inserts = 0
    with get_sqlalchemy_conn("dep") as conn:
        for row in progress:
            progress.set_description(
                f"{row.huc12_code}_{row.huc12_fpath_num:04.0f} {inserts}"
            )
            outfn = (
                Path("/i/0/weps")
                / f"{row.huc12_code[:8]}"
                / f"{row.huc12_code[8:]}"
                / f"{row.huc12_code}_{row.huc12_fpath_num}.out"
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
                    if dt.year == 2026:  # Don't want these attm
                        continue
                    if wanteddt is not None and dt != wanteddt:
                        continue
                    total_loss = float(tokens[5]) * -1.0
                    if total_loss == 0:
                        continue
                    inserts += 1
                    conn.execute(
                        sql_helper(
                            """
    insert into {table} (field_id, scenario_id, valid,
    erosion_kgm2, max_wind_speed_mps, drct) values (:fld, 0,
    :valid, :erosion, :max_wmps, :drct)""",
                            table=f"field_wind_erosion_results_{dt.year}",
                        ),
                        {
                            "fld": row.field_id,
                            "valid": dt,
                            "erosion": total_loss,
                            "max_wmps": float(tokens[9]),
                            "drct": float(tokens[10]),
                        },
                    )
                    if inserts % 1000 == 0:
                        conn.commit()
        conn.commit()


if __name__ == "__main__":
    main()
