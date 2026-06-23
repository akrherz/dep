"""Compute attributes associated with the huc12 table."""

import click
from pyiem.database import get_dbconn


def compute_average_slope_ratio(cursor, scenario):
    """Set attr"""
    cursor.execute(
        """
        with data as (
            select huc12_id, avg(avg_slope_ratio) from flowpath where
            scenario_id = %s GROUP by huc12_id
        )
        UPDATE huc12 h SET avg_slope_ratio = d.avg FROM data d
        WHERE h.huc12_id = d.huc12_id and h.scenario_id = %s
        """,
        (scenario, scenario),
    )
    print(f"Updated {cursor.rowcount} rows for average_slope_ratio")


@click.command()
@click.option("-s", "--scenario", type=int, required=True)
def main(scenario: int):
    """Do great things."""
    pgconn = get_dbconn("dep")
    cursor = pgconn.cursor()
    compute_average_slope_ratio(cursor, scenario)
    # Very small percentage have ties, so take max tillage code in that case
    cursor.execute(
        """
        with data as (
            select huc12_id, regexp_split_to_table(management, '') as ch
            from flowpath p JOIN flowpath_ofe t
            on (p.flowpath_id = t.flowpath_id)
            where p.scenario_id = %s and
            substr(management, 1, 1) in ('0', '1', '2', '3', '4', '5', '6')
            ORDER by management desc, flowpath, fpath),
        agg as (select ch, huc12_id, count(*) from data
            WHERE ch != '0' GROUP by ch, huc12_id),
        agg2 as (select huc12_id, ch::int, rank() OVER (PARTITION by huc12_id
            ORDER by count DESC, ch DESC) from agg)

        UPDATE huc12 h SET dominant_tillage = a.ch FROM agg2 a
        WHERE h.scenario_id = %s and h.huc12_id = a.huc12_id and
        a.rank = 1 and
        (h.dominant_tillage is null or h.dominant_tillage != a.ch)
        """,
        (scenario, scenario),
    )
    print(f"Updated dominant_tillage for {cursor.rowcount} HUC12s")
    pgconn.commit()
    pgconn.close()


if __name__ == "__main__":
    main()
