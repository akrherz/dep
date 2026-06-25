"""Plot accumulated acres diagnostic."""

import geopandas as gpd
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm
from matplotlib.patches import Rectangle
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.plot import MapPlot, figure_axes, get_cmap


def plot_map_progress(i, dt):
    """Make a map diagnostic."""
    charidx = dt.year - 2007 + 1
    with get_sqlalchemy_conn("dep") as conn:
        huc12df = gpd.read_postgis(
            sql_helper("""
            with data as (
                select huc12_id, sum(acres) as total,
                sum(case when o.plant is not null then acres else 0 end)
                    as planted from
                field f LEFT JOIN field_operations o
                on (f.field_id = o.field_id and o.year = :year and
                o.plant <= :dt) where scenario_id = 0 and
                substr(landuse, :charidx, 1) = 'C' GROUP by huc12_id
            )
            select huc12_code, ST_Transform(simple_geom, 4326) as geom,
            total, planted
            from huc12 h JOIN data d on (h.huc12_id = d.huc12_id)
            where scenario_id = 0
        """),
            conn,
            params={"year": dt.year, "dt": dt, "charidx": charidx},
            index_col="huc12_code",
            geom_col="geom",
        )
    huc12df["progress"] = huc12df["planted"] / huc12df["total"] * 100.0
    bins = np.arange(0, 101, 10)
    cmap = get_cmap("jet")
    cmap.set_under("white")
    cmap.set_over("black")
    norm = BoundaryNorm(bins, cmap.N)
    huc12df["color"] = cmap(norm(huc12df["progress"].values)).tolist()
    minx, miny, maxx, maxy = huc12df["geom"].to_crs(4326).total_bounds
    buffer = 0.01

    mp = MapPlot(
        title=f"DEP Corn Planting Progress on {dt:%Y %b %d}",
        logo="dep",
        sector="custom",
        west=minx - buffer,
        north=maxy + buffer,
        south=miny - buffer,
        east=maxx + buffer,
        caption="Daily Erosion Project",
        continentalcolor="white",
    )
    huc12df.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        color=huc12df["color"],
        zorder=100,
    )
    mp.draw_colorbar(bins, cmap, norm, units="Percent", extend="max")
    mp.fig.savefig(f"plots/plant{i:04.0f}.png")
    mp.close()


def plot_map(i, dt, huc12df, fields):
    """Make a map diagnostic"""
    minx, miny, maxx, maxy = huc12df["geom"].to_crs(4326).total_bounds
    buffer = 0.01
    huc12 = huc12df.index.values[0]

    mp = MapPlot(
        title=f"DEP Planting Progress {dt:%Y %b %d} for HUC12: {huc12}",
        logo="dep",
        sector="custom",
        west=minx - buffer,
        north=maxy + buffer,
        south=miny - buffer,
        east=maxx + buffer,
        caption="Daily Erosion Project",
        continentalcolor="white",
    )
    huc12df.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        facecolor="None",
        edgecolor="b",
        linewidth=2,
        zorder=100,
    )
    fields["color"] = "white"
    fields.loc[fields["till1"].notna(), "color"] = "tan"
    fields.loc[fields["plant"].notna(), "color"] = "g"
    fields.to_crs(mp.panels[0].crs).plot(
        ax=mp.panels[0].ax,
        aspect=None,
        facecolor=fields["color"],
        edgecolor="k",
        linewidth=1,
        zorder=100,
    )
    p0 = Rectangle((0, 0), 1, 1, fc="white", ec="k")
    p1 = Rectangle((0, 0), 1, 1, fc="tan", ec="k")
    p2 = Rectangle((0, 0), 1, 1, fc="g", ec="k")
    mp.panels[0].ax.legend(
        (p0, p1, p2),
        ("Awaiting", "Tilled", "Planted"),
        ncol=3,
        fontsize=11,
        loc=2,
    )

    mp.fig.savefig(f"plots/{i:04.0f}.png")
    mp.close()


def plot_timeseries(year, df, huc12):
    """Make a diagnostic."""
    (fig, ax) = figure_axes(
        logo="dep",
        title=f"DEP {year} Tillage/Plant Operation Timing for HUC12: {huc12}",
        subtitle="<=10% Daily Rate, All Field OFEs below 0.9 Plastic Limit",
    )
    ax2 = ax.twinx()
    x = pd.date_range(f"{year}/04/15", f"{year}/06/03")
    ax2.bar(
        x - pd.Timedelta(hours=8),
        df["acres_planted"],
        color="#00ff00",
        alpha=0.5,
        width=0.3,
        align="edge",
        zorder=2,
    )
    ax2.bar(
        x,
        df["acres_tilled"],
        color="#ff0000",
        alpha=0.5,
        width=0.3,
        align="edge",
        zorder=2,
    )

    ax.plot(
        x,
        df["acres_not_planted"],
        color="k",
        label="Not Planted",
        zorder=3,
        lw=3,
    )
    ax.plot(x, df["acres_to_till"], color="r", label="Tillage", zorder=3, lw=3)
    ax.plot(
        x,
        df["acres_to_plant"],
        c="g",
        label="Plant",
        zorder=3,
        lw=3,
    )
    ax.set_ylabel("Acres Available for Operations")
    ax.legend(loc=1)
    ax.grid(True)
    ax.set_ylim(bottom=-10)
    ax2.set_ylim(bottom=-10)
    ax2.set_ylabel("Acreas Worked per Day (bars)")
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    fig.savefig(f"plots/{year}_timeseries.png")


def main():
    """Go Main Go."""
    fig, ax = figure_axes(
        logo="dep",
        title="DEP 102300070305 2007-2022 Accumulated Plant Completion",
    )

    with get_sqlalchemy_conn("dep") as conn:
        df = pd.read_sql(
            """
            select f.acres, o.year, o.plant,
            plant - (o.year || '-03-01')::date as doy
            from field f
            JOIN field_operations o on (f.field_id = o.field_id)
            JOIN huc12 h on (h.huc12_id = f.huc12_id)
            WHERE h.huc12_code = '102300070305' ORDER by plant asc
            """,
            conn,
            parse_dates=["plant"],
        )
    for year in range(2007, 2023):
        df2 = (
            df[df["year"] == year]
            .groupby("doy")
            .sum(numeric_only=True)
            .cumsum()
        )
        ax.plot(
            df2.index.values,
            df2["acres"] / df2["acres"].max() * 100.0,
            label=f"{year}",
        )

    xticks = []
    xticklabels = []
    for dt in pd.date_range("2000/04/15", "2000/06/05"):
        x = (dt - pd.Timestamp(f"{dt.year}/03/01")).days
        if dt.day in [1, 8, 15, 22]:
            xticks.append(x)
            xticklabels.append(f"{dt:%-d %b}")
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels)
    ax.grid()
    ax.set_ylabel("Acres Planted [%]")
    ax.set_yticks([0, 5, 10, 25, 50, 75, 90, 95, 100])
    ax.legend(loc=4, ncol=3)
    fig.savefig("plots/test.png")


if __name__ == "__main__":
    for _i, _dt in enumerate(pd.date_range("2008-04-15", "2008-06-05")):
        plot_map_progress(_i, _dt)
