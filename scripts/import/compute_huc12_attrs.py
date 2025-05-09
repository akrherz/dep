"""Compute attributes associated with the huc12 table."""

import click
from pyiem.database import get_dbconn


def compute_average_slope_ratio(cursor, scenario):
    """Set attr"""
    cursor.execute(
        """
        with data as (
            select huc_12, avg(bulk_slope) from flowpaths where
            scenario = %s GROUP by huc_12
        )
        UPDATE huc12 h SET average_slope_ratio = d.avg FROM data d
        WHERE h.huc_12 = d.huc_12 and h.scenario = %s
        """,
        (scenario, scenario),
    )
    print(f"Updated {cursor.rowcount} rows for average_slope_ratio")


@click.command()
@click.option("--scenario", type=int, required=True)
def main(scenario: int):
    """Do great things."""
    pgconn = get_dbconn("idep")
    cursor = pgconn.cursor()
    compute_average_slope_ratio(cursor, scenario)
    # Very small percentage have ties, so take max tillage code in that case
    cursor.execute(
        """
        with data as (
            select huc_12, regexp_split_to_table(management, '') as ch
            from flowpaths p JOIN flowpath_ofes t on (p.fid = t.flowpath)
            where p.scenario = %s and
            substr(management, 1, 1) in ('0', '1', '2', '3', '4', '5', '6')
            ORDER by management desc, flowpath, fpath),
        agg as (select ch, huc_12, count(*) from data
            WHERE ch != '0' GROUP by ch, huc_12),
        agg2 as (select huc_12, ch::int, rank() OVER (PARTITION by huc_12
            ORDER by count DESC, ch DESC) from agg)

        UPDATE huc12 h SET dominant_tillage = a.ch FROM agg2 a
        WHERE h.scenario = %s and h.huc_12 = a.huc_12 and
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
