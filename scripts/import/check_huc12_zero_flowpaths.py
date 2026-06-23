"""Report which HUC12s have 0 flowpaths."""

import click
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper


@click.command()
@click.option("-s", "--scenario", type=int, required=True)
def main(scenario: int):
    """Go Main Go."""
    with open("myhucs.txt", encoding="utf8") as fh:
        huc12s = [s.strip() for s in fh.readlines()]
    with get_sqlalchemy_conn("dep") as conn:
        df = pd.read_sql(
            sql_helper(
                """
    SELECT huc12_code, count(*) from
    flowpath p JOIN huc12 h on (p.huc12_id = h.huc12_id)
    where p.scenario_id = :scenario
    GROUP by huc12_code"""
            ),
            conn,
            params={"scenario": scenario},
            index_col="huc12_code",
        )
    df = df.reindex(huc12s).fillna(0)
    print(df[df["count"] == 0].index.values)


if __name__ == "__main__":
    main()
