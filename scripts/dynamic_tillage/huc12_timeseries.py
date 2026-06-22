"""HUC12 Diagnostic."""

import os

import click
import pandas as pd
from matplotlib.dates import DateFormatter
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.plot import figure


def get_plastic_limit(huc12: str, year: int) -> pd.DataFrame:
    """Figure out what the plastic limit is."""
    charat = year - 2007 + 1
    with get_sqlalchemy_conn("idep") as conn:
        # build up the cross reference of everyhing we need to know
        return pd.read_sql(
            sql_helper(
                """
                select o.ofe, p.fpath, f.fbndid,
                g.wepp_min_sw1 + (g.wepp_max_sw1 - g.wepp_min_sw1) * 0.58
                as plastic_limit58,
                g.plastic_limit,
                p.fpath || '_' || o.ofe as combo,
                substr(f.landuse, :charat, 1) as crop
                from flowpaths p, flowpath_ofes o, gssurgo g, fields f
                WHERE o.flowpath = p.fid and p.huc_12 = :huc12
                and p.scenario = 0 and o.gssurgo_id = g.id
                and o.field_id = f.field_id
            """
            ),
            conn,
            params={
                "huc12": huc12,
                "charat": charat,
            },
            index_col=None,
        )


@click.command()
@click.option("--huc12", required=True, help="HUC12 To Plot")
@click.option("--year", required=True, type=int, help="Year to Plot")
def main(huc12: str, year: int):
    """Go Main Go."""
    pldf = get_plastic_limit(huc12, year)
    smdfs = []
    hucstatusdfs = []
    for dt in pd.date_range(f"{year}/04/11", f"{year}/06/13"):
        fn = f"/mnt/idep2/data/smstate/{dt:%Y}/smstate{dt:%Y%m%d}.feather"
        if not os.path.isfile(fn):
            continue
        smdf = pd.read_feather(fn)
        smdfs.append(smdf[smdf["huc12"] == huc12])

        fn = f"/mnt/idep2/data/huc12status/{dt:%Y}/{dt:%Y%m%d}.feather"
        if not os.path.isfile(fn):
            continue
        statusdf = pd.read_feather(fn)
        statusdf["date"] = dt
        hucstatusdfs.append(statusdf.loc[[huc12]])
    hucstatusdf = pd.concat(hucstatusdfs)
    huc12sm = pd.concat(smdfs)
    huc12sm = huc12sm[huc12sm["crop"].isin(["C", "B"])]
    huc12sm["combo"] = (
        huc12sm["fpath"].astype(str) + "_" + huc12sm["ofe"].astype(str)
    )
    huc12sm["pl0.8"] = (
        huc12sm["combo"].map(pldf.set_index("combo")["plastic_limit"]) * 0.8
    )
    huc12sm["crop"] = huc12sm["combo"].map(pldf.set_index("combo")["crop"])
    huc12sm["below_pl"] = huc12sm["sw1"] < huc12sm["plastic_limit"]

    _title = f"DEP: {huc12} Dynamic Tillage Diagnostic"
    _subtitle = f"11 April - 15 June {year}"

    fig = figure(
        title="",
        subtitle="",
        logo=None,
        figsize=(8, 9),  # Made figure taller to accommodate indicators
    )
    yaxsize = 0.2
    status_height = 0.025  # Height for each status row
    xloc = 0.2
    xaxsize = 0.7

    # Main plots with background shading
    ax = fig.add_axes([xloc, 0.7, xaxsize, yaxsize])
    ax2 = fig.add_axes([xloc, 0.45, xaxsize, yaxsize], sharex=ax)
    ax3 = fig.add_axes([xloc, 0.2, xaxsize, yaxsize], sharex=ax)

    # Status indicator axes
    status_axes = []
    for i in range(4):  # 3 individual + 1 combined
        status_axes.append(
            fig.add_axes(
                [
                    xloc,
                    0.02 + (i * status_height * 1.5),
                    xaxsize,
                    status_height,
                ]
            )
        )

    # Original plotting code
    ax3.xaxis.set_major_formatter(DateFormatter("%-d %b"))
    ax3.text(
        0,
        1.02,
        "* Soil Moisture Evaluation using previous date",
        transform=ax3.transAxes,
    )
    for dt, gdf in huc12sm.groupby("date"):
        ax3.bar(
            dt + pd.Timedelta(hours=24),
            gdf["below_pl"].sum() / gdf["below_pl"].size * 100,
            color="r",
            width=0.5,
            align="center",
            edgecolor="black",
        )
    ax3.axhline(50, lw=2, color="k")
    ax3.set_ylim(0, 100)
    ax3.set_yticks([0, 10, 25, 50, 75, 90, 100])
    ax3.grid(True)
    ax3.set_ylabel("Percent of OFEs\nBelow Computed Plastic Limit")

    ax2.bar(
        hucstatusdf["date"],
        hucstatusdf["precip_mm"],
        width=0.4,
        color="b",
        lw=2,
    )
    ax2.set_ylabel("Precip till 6 PM [mm]")
    ax2.axhline(10, lw=2, color="k")
    ax2.grid(True)

    # Filter temperature data
    temp_data = hucstatusdf[hucstatusdf["tsoil_avg"] < 80]
    ax.bar(
        temp_data["date"],
        temp_data["tsoil_avg"],
        width=0.4,
        color="b",
        lw=2,
    )
    ax.set_ylabel("Forecast Soil Temp [C]")
    ax.axhline(6, lw=2, color="k")
    ax.grid(True)

    xlim = (
        hucstatusdf["date"].min() - pd.Timedelta(days=1),
        hucstatusdf["date"].max() + pd.Timedelta(days=1),
    )

    # Add background shading for status
    for _ax, label in zip(
        [ax3, ax2, ax], ["soilmoisture", "precip", "soiltemp"], strict=False
    ):
        _ax.set_xlim(*xlim)
        prev_status = None
        span_start = None

        for _idx, row in hucstatusdf.iterrows():
            is_limited = row[f"limited_by_{label}"]
            if prev_status is None or is_limited != prev_status:
                if span_start is not None:
                    _ax.axvspan(
                        span_start - pd.Timedelta(hours=12),
                        row["date"] - pd.Timedelta(hours=12),
                        alpha=0.15,
                        color="red" if prev_status else "green",
                        zorder=0,
                    )
                span_start = row["date"]
                prev_status = is_limited

        if span_start is not None:
            _ax.axvspan(
                span_start - pd.Timedelta(hours=12),
                hucstatusdf.iloc[-1]["date"] + pd.Timedelta(days=1),
                alpha=0.15,
                color="red" if prev_status else "green",
                zorder=0,
            )

    # Add status indicators
    labels = [
        "Combined Status",
        "Soil Moisture",
        "Precipitation",
        "Soil Temperature",
    ]
    for ax_idx, status_ax in enumerate(status_axes):
        status_ax.set_xlim(*xlim)
        status_ax.set_ylim(-0.5, 0.5)
        status_ax.set_xticks([])
        status_ax.set_yticks([])

        # Add label on the left
        status_ax.text(
            -0.01,
            0.5,
            labels[ax_idx],
            ha="right",
            va="center",
            transform=status_ax.transAxes,
        )

        if ax_idx > 0:  # Individual status indicators
            var_names = ["", "soilmoisture", "precip", "soiltemp"]
            for _idx, row in hucstatusdf.iterrows():
                text_props = {"ha": "center", "va": "center"}
                if row[f"limited_by_{var_names[ax_idx]}"]:
                    status_ax.text(
                        row["date"], 0, "✘", color="red", **text_props
                    )
                else:
                    status_ax.text(
                        row["date"], 0, "✔", color="green", **text_props
                    )
        else:  # Combined status
            for _idx, row in hucstatusdf.iterrows():
                is_limited = (
                    row["limited_by_soilmoisture"]
                    or row["limited_by_precip"]
                    or row["limited_by_soiltemp"]
                )
                text_props = {"ha": "center", "va": "center"}
                if is_limited:
                    status_ax.text(
                        row["date"], 0, "✘", color="red", **text_props
                    )
                else:
                    status_ax.text(
                        row["date"], 0, "✔", color="green", **text_props
                    )

    # plots directory is symlinked
    pngfn = f"plots/sm_{huc12}_{year}.png"
    print(f"Created {pngfn}")
    fig.savefig(pngfn, dpi=300)


if __name__ == "__main__":
    main()
