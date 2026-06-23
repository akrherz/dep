"""Bootstrap database for dynamic tillage."""

from datetime import date

import click
import pandas as pd
from pyiem.database import get_dbconnc, get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

from dailyerosion.tillage import make_tillage

LOG = logger()


@click.command()
@click.option("--year", type=int, help="Year to bootstrap", required=True)
@click.option("--scenario", type=int, default=0)
def main(year: int, scenario: int):
    """Run for the given year."""
    dbcolidx = year - 2007 + 1
    with get_sqlalchemy_conn("dep") as conn:
        # Delete current year's data
        res = conn.execute(
            sql_helper("""
                 delete from field_operations o USING field f
                 WHERE o.field_id = f.field_id and o.year = :year
                 and f.scenario_id = :scenario
                 """),
            {"year": year, "scenario": scenario},
        )
        LOG.info("deleted %s field operation rows", res.rowcount)
        conn.commit()
        # The isAg field is not reliable, we need to look at the landuse
        # column which we control planting dates for.
        fields = pd.read_sql(
            sql_helper("""
                select field_id, landuse, management,
                st_y(st_centroid(st_transform(geom, 4326))) as lat
                from field where scenario_id = :scenario
                and substr(landuse, :dbcolidx, 1) = ANY(:crops)
                and management is not null
            """),
            conn,
            params={
                "scenario": scenario,
                "dbcolidx": dbcolidx,
                "crops": ["B", "C"],
            },
            index_col="field_id",
        )
    LOG.info("Processing %s fields", len(fields.index))
    conn, cursor = get_dbconnc("dep")
    colidx = year - 2007
    inserts = 0
    progress = tqdm(fields.iterrows(), total=len(fields.index))
    for field_id, row in progress:
        zone = "KS_NORTH"
        if row["lat"] >= 42.5:
            zone = "IA_NORTH"
        elif row["lat"] >= 41.5:
            zone = "IA_CENTRAL"
        elif row["lat"] >= 40.5:
            zone = "IA_SOUTH"
        res = make_tillage(
            scenario,
            zone,
            row["landuse"][colidx - 1],
            row["landuse"][colidx],
            row["landuse"][colidx - 2],  # HACK
            row["management"][colidx],
            year - 2006,
        )
        events = 0
        for line in res.split("\n"):
            tokens = line.split()
            if len(tokens) < 5 or tokens[4] != "Tillage" or int(tokens[0]) > 6:
                continue
            events += 1
        # till1, till2, till3, plant
        dates = [None, None, None, None]
        if events == 1:
            dates[3] = date(year, 6, 10)
        elif events == 2:
            dates[0] = date(year, 6, 10)
            dates[3] = date(year, 6, 11)
        elif events == 3:
            dates[0] = date(year, 6, 10)
            dates[1] = date(year, 6, 11)
            dates[3] = date(year, 6, 12)
        elif events == 4:
            dates[0] = date(year, 6, 10)
            dates[1] = date(year, 6, 11)
            dates[2] = date(year, 6, 12)
            dates[3] = date(year, 6, 13)
        elif events > 4:
            LOG.info("events: %s", events)
            LOG.info("res: %s", res)
            raise ValueError("too many events")
        cursor.execute(
            """
            INSERT into field_operations
            (field_id, year, till1, till2, till3, plant)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            (field_id, year, dates[0], dates[1], dates[2], dates[3]),
        )
        inserts += 1
        if inserts % 10_000 == 0:
            cursor.close()
            conn.commit()
            cursor = conn.cursor()

    cursor.close()
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
