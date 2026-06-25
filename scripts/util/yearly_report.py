"""Generate a report for the yearly DEP totals"""

import sys
from datetime import date, datetime

import matplotlib.pyplot as plt
from pandas import read_sql
from pyiem.database import get_dbconnstr
from pyiem.reference import state_names

from dailyerosion.reference import KG_M2_TO_TON_ACRE


def main(argv):
    """Do What We Wanted"""
    scenario = int(argv[1])
    state = argv[2]
    lyear = date.today().year - 1
    print(f"This report covers the inclusive years 2008-{lyear} for {state}")

    df = read_sql(
        """
        WITH iahuc12 as (
            SELECT huc12_id from huc12 where states = %s and scenario_id = 0
        ), agg as (
            SELECT r.huc12_id, extract(year from valid)::int as yr,
            sum(qc_precip_mm) as precip, sum(avg_runoff_mm) as runoff,
            sum(avg_delivery_kgm2) as delivery,
            sum(avg_loss_kgm2) as detachment
            from water_results_by_huc12 r JOIN iahuc12 i
            on (r.huc12_id = i.huc12_id) WHERE r.scenario_id = %s
            and r.valid >= '2008-01-01'
            and r.valid <= %s GROUP by r.huc12_id, yr
        )

        SELECT yr, round((avg(precip) / 25.4)::numeric, 2) as precip_in,
        round((avg(runoff) / 25.4)::numeric, 2) as runoff_in,
        round((avg(delivery) * %s)::numeric, 2) as delivery_ta,
        round((avg(detachment) * %s)::numeric, 2) as detachment_ta
        from agg GROUP by yr ORDER by yr
    """,
        get_dbconnstr("dep"),
        params=(
            state,
            scenario,
            date(lyear, 12, 31),
            KG_M2_TO_TON_ACRE,
            KG_M2_TO_TON_ACRE,
        ),
        index_col="yr",
    )

    print(df.to_markdown())
    print(df.mean())

    (fig, ax) = plt.subplots(1, 1)
    ax.bar(df.index.values, df["detachment_ta"].values)
    for year, row in df.iterrows():
        ax.text(
            year,
            row["detachment_ta"] + 0.2,
            f"{row['detachment_ta']:.1f}",
            ha="center",
        )
    ax.axhline(
        df["detachment_ta"].mean(),
        label=f"mean {df['detachment_ta'].mean():.2f}",
        zorder=5,
        color="k",
        lw=1.5,
    )
    ax.legend(loc="best")
    ax.grid(True)
    ax.set_xlim(df.index.values[0] - 0.5, df.index.values[-1] + 0.5)
    ax.set_ylim(0, 3.5)
    ax.set_ylabel("Yearly Detatchment [tons/acre]")
    ax.set_title(
        f"{state_names[state]} Daily Erosion Project Iowa's Yearly Detachment"
    )
    fig.text(
        0.01,
        0.01,
        f"Plot generated {datetime.now():%d %B %Y}",
    )
    fig.savefig("test.png")


if __name__ == "__main__":
    main(sys.argv)
