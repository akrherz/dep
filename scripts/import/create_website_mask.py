"""Create a GISable PNG with DEP's domain."""

import subprocess

import geopandas as gpd
import pyproj
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.iemre import EAST, NORTH, SOUTH, WEST
from pyiem.plot.use_agg import plt


def main():
    """Go Main Go."""
    with get_sqlalchemy_conn("dep") as conn:
        gdf = gpd.read_postgis(
            sql_helper(
                "SELECT st_transform(simple_geom, 3857) as geo from huc12 "
                "where scenario_id = 0"
            ),
            conn,
            geom_col="geo",
        )
    # Figure out iemre domain
    transformer = pyproj.Transformer.from_crs(
        "epsg:4326", "epsg:3857", always_xy=True
    )
    (ulx, uly) = transformer.transform(WEST, NORTH)
    (lrx, lry) = transformer.transform(EAST, SOUTH)
    # Create 10km grid cell
    xsize = (lrx - ulx) / 2_000 / 100.0
    ysize = (uly - lry) / 2_000 / 100.0
    print(xsize, ysize)

    fig = plt.figure(figsize=(xsize, ysize), facecolor="black")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("black")
    gdf.plot(
        ax=ax,
        aspect=None,
        fc="white",
        ec="white",
    )
    ax.set_xlim(ulx, lrx)
    ax.set_ylim(lry, uly)

    fig.savefig("depdomain.png")
    with open("depdomain.wld", "w", encoding="utf-8") as fp:
        fp.write(f"2000.\n0.0\n0.0\n-2000.\n{ulx:.2f}\n{uly:.2f}\n")
    # Now make white color transparent
    subprocess.call(
        [
            "magick",
            "depdomain.png",
            "-transparent",
            "white",
            "-colors",
            "2",
            "depdomain.png",
        ],
    )


if __name__ == "__main__":
    main()
