"""Collect the output from the saved WEPS runs."""

from datetime import date, datetime
from pathlib import Path

import click
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

LOG = logger()
# Threshold for saving wind erosion results based on wind speed (m/s)
# if there was no erosion
WIND_SAVE_THRESH = 12.0


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
    JOIN field f ON (o.field_id = f.field_id)
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
    files_read = 0
    today = date.today()
    day_index = None
    month_index = None
    year_index = None
    loss_index = None
    max_wind_index = None
    drct_index = None
    pm10_index = None
    pm2_5_index = None
    suspen_index = None
    sampled_header = None
    with get_sqlalchemy_conn("dep") as conn:
        for row in progress:
            progress.set_description(
                f"{row.huc12_code}_{row.huc12_fpath_num:04.0f} {inserts} over "
                f"{files_read}"
            )
            outfn = (
                Path("/i/0/weps")
                / f"{row.huc12_code[:8]}"
                / f"{row.huc12_code[8:]}"
                / f"{row.huc12_code}_{row.huc12_fpath_num}.out"
            )
            if not outfn.exists():
                # Don't really care about not existing output files as inserts
                # will be sus if lots of files are missing
                continue
            files_read += 1
            with open(outfn, "r") as fh:
                for linenum, line in enumerate(fh):
                    if linenum == 0:
                        header = line.strip()
                        if sampled_header is None:
                            sampled_header = header
                            tokens = [x.strip() for x in header.split("|")]
                            day_index = tokens.index("day")
                            month_index = tokens.index("mon")
                            year_index = tokens.index("yr")
                            loss_index = tokens.index("tot_loss")
                            max_wind_index = tokens.index("max_wind")
                            drct_index = tokens.index("dir_wind")
                            pm10_index = tokens.index("pm10")
                            pm2_5_index = tokens.index("pm2_5")
                            suspen_index = tokens.index("suspen")
                        if sampled_header != header:
                            progress.write("Abort has header does not match")
                            break
                        continue
                    tokens = line.strip().split()
                    if len(tokens) < 20:
                        continue
                    dt = date(
                        int(tokens[year_index]),
                        int(tokens[month_index]),
                        int(tokens[day_index]),
                    )
                    if dt >= today:
                        continue
                    if wanteddt is not None and dt != wanteddt:
                        continue
                    total_loss = float(tokens[loss_index]) * -1.0
                    max_wmps = float(tokens[max_wind_index])
                    if total_loss == 0 and max_wmps < WIND_SAVE_THRESH:
                        continue
                    inserts += 1
                    salt_creep = total_loss - (
                        float(tokens[suspen_index]) * -1.0
                    )
                    conn.execute(
                        sql_helper(
                            """
    insert into {table} (field_id, scenario_id, valid,
    erosion_kgm2, max_wind_speed_mps, drct, pm10_kgm2, pm2_5_kgm2,
    salt_creep_kgm2) values (:fld, 0,
    :valid, :erosion, :max_wmps, :drct, :pm10, :pm2_5, :salt)""",
                            table=f"field_wind_erosion_results_{dt.year}",
                        ),
                        {
                            "fld": row.field_id,
                            "valid": dt,
                            "erosion": total_loss,
                            "max_wmps": max_wmps,
                            "drct": float(tokens[drct_index]),
                            "pm10": max(0, float(tokens[pm10_index]) * -1.0),
                            "pm2_5": max(0, float(tokens[pm2_5_index]) * -1.0),
                            "salt": salt_creep,
                        },
                    )
                    if inserts % 1000 == 0:
                        conn.commit()
        conn.commit()


if __name__ == "__main__":
    main()
