"""Create a map of where we have climate files!"""

import click
import geopandas as gpd
import numpy as np
import rasterio as rio
from matplotlib.colors import BoundaryNorm
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.grid.nav import get_nav
from pyiem.plot import MapPlot, get_cmap
from pyiem.reference import Z_OVERLAY

"""
select geom from climate_files where id in (
        select distinct climate_file_id from climate_file_yearly_summary
        where rfactor < 1 and year = 2024) and scenario = 0
"""


@click.command()
@click.option("--year", default=2024, help="Year to plot")
def main(year: int):
    """make maps, not war."""
    # https://zenodo.org/records/11078865
    with rio.open("/home/akrherz/Downloads/GloRESatE/GloRESatE.tif") as src:
        gloresate = src.read(1)
        aff = src.transform

    def find_ij(lon, lat):
        """figure out the grid index."""
        return ~aff * (lon, lat)

    with get_sqlalchemy_conn("dep_europe") as pgconn:
        pts = gpd.read_postgis(
            sql_helper("""
    with climo as (
        select climate_file_id, avg(rfactor) as rr from
        climate_file_yearly_summary
        GROUP by climate_file_id)
    select geom, rr from
    climate_file f JOIN climo c on (f.climate_file_id = c.climate_file_id)
    WHERE f.scenario_id = 0
"""),
            pgconn,
            params={"year": year},
            geom_col="geom",
        )
    for idx, row in pts.iterrows():
        lon, lat = row["geom"].x, row["geom"].y
        i, j = find_ij(lon, lat)
        pts.at[idx, "gloresate"] = gloresate[int(j), int(i)]

    pts["ratio"] = (pts["rr"] - pts["gloresate"]) / pts["gloresate"] * 100.0

    print(pts["ratio"].describe())

    cmap = get_cmap("RdBu")
    clevs = np.arange(-60, 61, 20)
    norm = BoundaryNorm(clevs, cmap.N)
    nav = get_nav("iemre", "europe")
    mp = MapPlot(
        logo="dep",
        sector="custom",
        west=nav.left_edge,
        east=nav.right_edge,
        south=nav.bottom_edge,
        north=nav.top_edge,
        title="R-Factor % Difference DEP 2007-2024 Minus GloRESatE",
        subtitle=f"Total Climate Files: {len(pts)}",
        caption="Daily Erosion Project",
    )
    # All points will overwhelm matplotlib, so we need to plot them in chunks
    pts.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        marker="o",
        markersize=3,
        color=cmap(norm(pts["ratio"].values)),
        zorder=Z_OVERLAY,
    )
    mp.draw_colorbar(
        clevs=clevs,
        cmap=cmap,
        norm=norm,
        spacing="proportional",
        units="%",
        extend="both",
    )
    mp.fig.savefig("dep_clifiles.png")


if __name__ == "__main__":
    main()
