"""General HUC12 mapper"""

import sys

import geopandas as gpd
import matplotlib.colors as mpcolors
import pandas as pd
from pyiem.database import get_sqlalchemy_conn
from pyiem.plot import MapPlot
from pyiem.reference import Z_POLITICAL

from dailyerosion.reference import KG_M2_TO_TON_ACRE


def main(argv):
    """Do Great Things"""
    oferesults = pd.read_csv(
        "../util/oferesults_071000081505.csv", index_col="id"
    )
    fieldresults = (
        oferesults[["fbndid", "delivery_2010[t/a/yr]"]]
        .groupby("fbndid")
        .mean()
    )
    fpresults = (
        oferesults[["fpath", "delivery_2010[t/a/yr]"]].groupby("fpath").mean()
    )
    with get_sqlalchemy_conn("idep") as conn:
        huc12res = pd.read_sql(
            """
            SELECT huc_12, sum(avg_delivery) * %s * 2.24  as del_tonnes from
            results_by_huc12 where scenario = 0 and
            valid >= '2010-01-01' and valid < '2011-01-01'
            GROUP by huc_12
            """,
            conn,
            params=(KG_M2_TO_TON_ACRE,),
            index_col="huc_12",
        )
        df = gpd.read_postgis(
            """
            SELECT ST_Transform(geom, 4326) as geom, dominant_tillage,
            huc_12
            from huc12 WHERE scenario = 0 and states ~* 'IA'
        """,
            conn,
            geom_col="geom",
            index_col="huc_12",
        )
        df["del_tonnes"] = huc12res["del_tonnes"]
        fields = gpd.read_postgis(
            """
            select st_transform(geom, 4326) as geo, fbndid, isag from fields
            """,
            conn,
            geom_col="geo",
            index_col="fbndid",
        )
        fields["del_tonnes"] = fieldresults["delivery_2010[t/a/yr]"] * 2.24
        fps = gpd.read_postgis(
            """
            select st_transform(geom, 4326) as geo, fpath from flowpaths
            WHERE scenario = 0 and huc_12 = '071000081505'
            """,
            conn,
            geom_col="geo",
            index_col="fpath",
        )
        fps["del_tonnes"] = fpresults["delivery_2010[t/a/yr]"] * 2.24
        ofes = gpd.read_postgis(
            """
            select st_transform(o.geom, 4326) as geo, fields.fbndid,
            f.huc_12 || '_' || f.fpath || '_' || o.ofe as id from
            flowpath_ofes o JOIN flowpaths f on (o.flowpath = f.fid)
            JOIN fields on (o.field_id = fields.field_id)
            WHERE scenario = 0 and huc_12 = '071000081505'
            """,
            conn,
            geom_col="geo",
            index_col="id",
        )
        ofes["del_tonnes"] = oferesults["delivery_2010[t/a/yr]"] * 2.24
    extent = df.total_bounds
    buffer = 0.01
    huc10 = df.dissolve(aggfunc="mean").copy()
    mp = MapPlot(
        sector="custom",
        south=extent[1] - buffer,  # + 0.11,
        north=extent[3] + buffer,  # - 0.04,
        west=extent[0] - buffer,  # + 0.07,
        east=extent[2] + buffer,  # - 0.085,
        continentalcolor="white",
        logo="dep",
        nocaption=True,
        title="DEP 2010 Iowa Hillslope Soil Delivery",
        subtitle=(
            f"Iowa Avg: {huc10['del_tonnes'].values[0]:.2f} tonnes/hectare"
        ),
    )
    cmap = mpcolors.ListedColormap(
        "#FFFF80 #FCDD60 #E69729 #B35915 #822507".split(),
        "erosion",
    )
    cmap.set_bad("white")
    cmap.set_under("white")
    cmap.set_over("#00ffff")
    bins = list(range(0, 11, 2))
    norm = mpcolors.BoundaryNorm(bins, cmap.N)
    """
    df.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        edgecolor="blue",
        lw=1.4,
        facecolor="None",
        zorder=Z_POLITICAL + 3,
    )
    """
    huc10 = df.dissolve(aggfunc="mean").copy()
    huc10["color"] = [c for c in cmap(norm(huc10["del_tonnes"].values))]

    huc10.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        edgecolor="None",
        lw=0.5,
        facecolor=huc10["color"],
        zorder=Z_POLITICAL,
    )
    """
    fields["color"] = [c for c in cmap(norm(fields["del_tonnes"].values))]
    fields.loc[pd.isna(fields["del_tonnes"]), "color"] = "white"

    fields.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        edgecolor="tan",
        facecolor=fields["color"],
        lw=0.5,
        zorder=Z_POLITICAL + 1,
    )
    fps.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        color="k",
        lw=2,
        zorder=Z_POLITICAL + 2,
    )
    fields.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        edgecolor="tan",
        facecolor="None",
        lw=0.5,
        zorder=Z_POLITICAL + 1,
    )

    ofes["color"] = [c for c in cmap(norm(ofes["del_tonnes"].values))]
    ofes.loc[pd.isna(ofes["del_tonnes"]), "color"] = "white"

    ofes.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        color=ofes["color"],
        lw=5,
        zorder=Z_POLITICAL + 1,
    )
    """

    mp.draw_colorbar(
        bins, cmap, norm, extend="max", units="Delivery tonnes / hectare"
    )
    mp.postprocess(filename="test.png")


if __name__ == "__main__":
    main(sys.argv)
