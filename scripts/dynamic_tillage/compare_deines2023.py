"""Comparison to: https://zenodo.org/records/16740666"""

import click
import pandas as pd
from compute_county_district import DISTRICTS, NAMES, XREF
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.plot import figure_axes


@click.command()
@click.option("--year", type=int, required=True)
@click.option("--crop", type=str, default="corn")
@click.option("--district", type=str, default="IAC005")
def main(year: int, crop: str, district: str):
    """Go main Go."""
    counties = XREF[district]
    deines_all = pd.read_csv(
        f"deines2023/deines2023_district_{crop}.csv", parse_dates=["date"]
    )
    deines = deines_all[
        (deines_all["district"] == district) & (deines_all["year"] == year)
    ].copy()

    nass = None
    if district.startswith("IA"):
        with get_sqlalchemy_conn("coop") as conn:
            nass = pd.read_sql(
                sql_helper(
                    """
        select valid, {dist} as datum from nass_iowa
        where metric = :metric
        and extract(year from valid) = :year order by valid asc
    """,
                    dist=DISTRICTS[district],
                ),
                conn,
                params={"metric": f"{crop} planted", "year": year},
            )

    with get_sqlalchemy_conn("dep") as conn:
        dep = pd.read_sql(
            sql_helper("""
    select o.plant, sum(acres), count(*) from
    field f JOIN field_operations o on (f.field_id = o.field_id)
    JOIN huc12 h on (f.huc12_id = h.huc12_id)
    WHERE o.year = :year and
    substr(f.landuse, :pos, 1) = 'B' and
    h.scenario_id = 0 and h.ugc = ANY(:fips)
    group by plant order by plant;
                                      """),
            conn,
            params={"year": year, "pos": year - 2007 + 1, "fips": counties},
        )

    (fig, ax) = figure_axes(
        title=f"{NAMES[district]} CRD {year} {crop} Planting Progress",
        figsize=(8, 6),
        logo="dep",
    )

    ax.plot(
        dep["plant"],
        dep["sum"].cumsum() / dep["sum"].sum() * 100.0,
        label="DEP",
        marker="o",
        color="blue",
        lw=2,
    )

    ax.plot(
        deines["date"],
        deines["pct"],
        label="Deines 2023",
        marker="o",
        color="red",
        lw=2,
    )

    if district.startswith("IA") and nass is not None:
        ax.plot(
            nass["valid"],
            nass["datum"],
            label="NASS",
            marker="o",
            color="green",
            lw=2,
        )
    ax.legend(loc=2)
    ax.grid(True)
    ax.set_yticks([0, 5, 10, 25, 50, 75, 90, 95, 100])
    ax.set_ylabel("Percentage of Acres Planted [%]")

    fig.savefig(f"plots/comparison_{year}_{district}_{crop}.png")


if __name__ == "__main__":
    main()
