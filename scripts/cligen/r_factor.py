"""R factor work."""

import os
from multiprocessing import Pool

import cartopy.crs as ccrs
import geopandas as gpd
import matplotlib.colors as mpcolors
import numpy as np
import pandas as pd
from matplotlib.patches import Polygon
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.plot import MapPlot
from pyiem.plot.use_agg import plt
from tqdm import tqdm

from dailyerosion.rfactor import compute_rfactor_from_cli


def plot():
    """Plot."""
    df2 = pd.read_csv("/tmp/data.csv", dtype={"huc12": str}).set_index("huc12")
    with get_sqlalchemy_conn("dep") as conn:
        df = gpd.read_postgis(
            sql_helper(
                "SELECT huc12_code, ST_Transform(simple_geom, 4326) as geom "
                "from huc12 WHERE scenario_id = 0"
            ),
            conn,
            geom_col="geom",
            index_col="huc12_code",
        )
    minx, miny, maxx, maxy = df["geom"].total_bounds
    colname = "rfactor_yr_avg"
    df2[colname] = df2[colname] * 0.05876
    desc = df2[colname].describe()
    buffer = 0.1
    mp = MapPlot(
        title="DEP 2007-2021 Average R Factor Yearly Total by HUC12",
        subtitle=(
            f"Min: {desc['min']:.1f} Mean: {desc['mean']:.1f} "
            f"Max: {desc['max']:.1f}, based on daily R factor"
        ),
        axisbg="#EEEEEE",
        logo="dep",
        sector="custom",
        south=miny - buffer,
        north=maxy + buffer,
        west=minx - buffer,
        east=maxx + buffer,
        projection=ccrs.PlateCarree(),
        caption="Daily Erosion Project",
    )
    cmap = plt.get_cmap("turbo")
    clevs = np.arange(0, 300.1, 25.0)
    norm = mpcolors.BoundaryNorm(clevs, cmap.N)
    for huc_12, row in df.iterrows():
        val = df2.at[huc_12, colname]
        c = cmap(norm([val]))[0]
        p = Polygon(row["geom"].exterior.coords, fc=c, ec=c, zorder=2, lw=0.1)
        mp.ax.add_patch(p)
    mp.draw_colorbar(
        clevs,
        cmap,
        norm,
        extend="neither",
        units="hundred ft tonf inches per acre per hour",
    )
    mp.fig.savefig("test.png")


def job(args) -> pd.DataFrame:
    """Process."""
    (cliid, row) = args
    if not os.path.isfile(row["filepath"]):
        return cliid, pd.DataFrame()
    return cliid, compute_rfactor_from_cli(row["filepath"])


def dump_data():
    """Go main Go."""
    inserts = 0
    with get_sqlalchemy_conn("dep") as conn, Pool() as pool:
        clidf = pd.read_sql(
            """
            SELECT climate_file_id, filepath from climate_file where
            scenario_id = 0
        """,
            conn,
            index_col="climate_file_id",
        )
        for clid, resdf in tqdm(
            pool.imap(job, clidf.iterrows()), total=len(clidf)
        ):
            if resdf.empty:
                continue
            conn.execute(
                sql_helper("""
    delete from climate_file_yearly_summary where climate_file_id = :clid
                     """),
                {"clid": clid},
            )
            for year in range(2007, 2025):
                conn.execute(
                    sql_helper(
                        """
    insert into climate_file_yearly_summary
    (climate_file_id, year, rfactor, rfactor_storms) values
    (:clid, :year, :rfactor, :rfactor_storms)
                        """
                    ),
                    {
                        "clid": clid,
                        "year": year,
                        "rfactor": resdf.at[year, "rfactor"],
                        "rfactor_storms": resdf.at[year, "storm_count"],
                    },
                )
                inserts += 1
            if inserts > 1_000:
                conn.commit()
                inserts = 0
        conn.commit()


if __name__ == "__main__":
    dump_data()
