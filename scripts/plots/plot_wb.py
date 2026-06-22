"""Diagnose some Water Balance stuff"""

import glob
from datetime import date, timedelta

import click
import pandas as pd
import seaborn as sns
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.plot import figure
from tqdm import tqdm

from dailyerosion.io.dep import read_wb


def get_plastic_limit(huc12: str, year: int) -> pd.DataFrame:
    """Figure out what the plastic limit is."""
    charat = year - 2007 + 1
    with get_sqlalchemy_conn("idep") as conn:
        # build up the cross reference of everyhing we need to know
        return pd.read_sql(
            sql_helper(
                """
                select o.ofe, p.fpath, f.fbndid,
                g.wepp_min_sw1,
                g.wepp_max_sw1,
                g.wepp_min_sw,
                g.wepp_max_sw,
                g.plastic_limit,
                substr(f.landuse, :charat, 1) as crop,
                p.fpath || '_' || o.ofe as combo
                from flowpaths p, flowpath_ofes o, gssurgo g, fields f
                WHERE o.flowpath = p.fid and p.huc_12 = :huc12
                and p.scenario = 0 and o.gssurgo_id = g.id and
                o.field_id = f.field_id
            """
            ),
            conn,
            params={
                "huc12": huc12,
                "charat": charat,
            },
            index_col=None,
        ).set_index(["fpath", "ofe"])


@click.command()
@click.option("--huc12", type=str, required=True)
@click.option("--year", type=int)
def main(huc12: str, year: int):
    """Do things"""
    dfs = []
    for fn in glob.glob(f"/i/0/wb/{huc12[:8]}/{huc12[8:]}/*"):
        df = read_wb(fn)
        df["fpath"] = int(fn.split("_")[1][:-3])
        dfs.append(df)
    df = pd.concat(dfs)
    pldf = get_plastic_limit(huc12, year)
    ranges = df.groupby(["fpath", "ofe"]).describe()

    ptime = []
    pl = []
    for fpath, ofe in ranges.index:
        if (fpath, ofe) not in pldf.index:
            print(f"Huh? {fpath} {ofe}")
            continue
        total = df[(df["fpath"] == fpath) & (df["ofe"] == ofe)].shape[0]
        below = df[
            (df["fpath"] == fpath)
            & (df["ofe"] == ofe)
            & (df["sw1"] < pldf.loc[(fpath, ofe), "plastic_limit"] * 0.8)
        ].shape[0]
        ptime.append(below / total * 100.0)
        pl.append(pldf.loc[(fpath, ofe), "plastic_limit"] * 0.8)

    for doy in tqdm(range(1, 365)):
        dt = date(year, 1, 1) + timedelta(days=(doy - 1))
        wb = df[(df["year"] == year) & (df["jday"] == doy)].copy()
        wb = wb.set_index(["fpath", "ofe"])
        for col in ["plastic_limit", "wepp_min_sw1", "wepp_max_sw1"]:
            wb[col] = pldf[col]
        for f2 in ["sw1", "sw2", "sw"]:
            for f1 in ["min", "max"]:
                wb[f"{f2}_{f1}"] = ranges[f2, f1]
            wb[f"{f2}_range"] = wb[f"{f2}_max"] - wb[f"{f2}_min"]
            wb[f"{f2}_percent"] = (
                (wb[f2] - wb[f"{f2}_min"]) / wb[f"{f2}_range"] * 100.0
            )

        sns.set_theme(style="white", palette="muted", color_codes=True)
        fig = figure(
            title=f"{dt:%d %B %Y} :: Water Balance for {huc12}",
            subtitle=f"{len(wb)} OFEs in Corn/Soybeans Plotted",
            logo="dep",
            figsize=(12, 7),
        )

        xcol = [0.05, 0.275, 0.525, 0.8]
        width = 0.15
        ax = [
            [
                fig.add_axes((xcol[0], 0.7, width, 0.2)),
                fig.add_axes((xcol[1], 0.7, width, 0.2)),
                fig.add_axes((xcol[2], 0.7, width, 0.2)),
                fig.add_axes((xcol[3], 0.7, width, 0.2)),
            ],
            [
                fig.add_axes((xcol[0], 0.4, width, 0.2)),
                fig.add_axes((xcol[1], 0.4, width, 0.2)),
                fig.add_axes((xcol[2], 0.4, width, 0.2)),
                fig.add_axes((xcol[3], 0.4, width, 0.2)),
            ],
            [
                fig.add_axes((xcol[0], 0.1, width, 0.2)),
                fig.add_axes((xcol[1], 0.1, width, 0.2)),
                fig.add_axes((xcol[2], 0.1, width, 0.2)),
                fig.add_axes((xcol[3], 0.1, width, 0.2)),
            ],
        ]
        sns.despine(left=True)

        # Diagnostic
        myax = ax[0][3]
        myax.scatter(
            wb["wepp_max_sw1"].to_numpy(),
            wb["plastic_limit"].to_numpy(),
            color="g",
        )
        myax.plot([0, 50], [0, 50])
        myax.set_ylabel("Plastic Limit [%]")
        myax.set_xlabel("WEPP 0-10cm Max SW [%]")

        # Diagnostic
        myax = ax[1][3]
        myax.scatter(
            wb["wepp_max_sw1"].to_numpy(),
            wb["sw1_max"].to_numpy(),
            color="g",
        )
        myax.plot([0, 50], [0, 50])
        myax.set_ylabel("OFE 0-10cm Max SW [%]")
        myax.set_xlabel("GSSURGO 0-10cm Max SW [%]")

        # Percent of time below PL * 0.8
        myax = ax[2][3]
        pltdf = pd.DataFrame({"pl": pl, "ptime": ptime}).sort_values("pl")
        myax.scatter(
            pltdf["pl"],
            pltdf["ptime"],
            color="g",
        )
        myax.set_ylabel("% Time < PL * 0.8")
        myax.set_xlabel("0.8 * PL")
        myax.set_ylim(0, 100)

        # ---------------------------------------------------
        myax = ax[0][0]
        sns.histplot(wb["sw1"], color="g", ax=myax, kde=True)
        myax.set_xlabel("0-10cm Soil Water [mm]")
        myax.axvline(wb["sw1"].mean(), color="r")
        myax.set_xlim(0, 60)
        myax.set_ylim(0, 70)

        # --------------------------------------------------------
        myax = ax[0][1]
        sns.histplot(wb["sw1_percent"], color="g", ax=myax, kde=True)
        myax.set_xlabel("0-10cm Soil Water of Capacity [%]")
        myax.axvline(wb["sw1_percent"].mean(), color="r")
        myax.set_xlim(0, 100)
        myax.set_ylim(0, 70)
        myax.set_ylabel("")

        # --------------------------------------------------------
        for i, fract in enumerate([0.8, 0.9, 1]):
            myax = ax[i][2]
            delta = wb["sw1"] - (wb["plastic_limit"] * fract)
            percent = (delta > 0).sum() / len(delta) * 100.0
            myax.annotate(
                f"{percent:.1f}% ↑",
                xy=(0.2, 0.8),
                xycoords="axes fraction",
                ha="center",
                fontsize=12,
                color="r" if percent > 75 else "g",
            )
            sns.histplot(delta, color="g", ax=myax, kde=True)
            myax.set_xlabel(f"0-10cm Diff (PP) to PL * {fract}")
            myax.axvline(delta.mean(), color="r")
            myax.set_xlim(-40, 40)
            myax.set_ylim(0, 70)
            myax.set_ylabel("")

        # ---------------------------------------------------------
        myax = ax[1][0]
        sns.histplot(wb["sw2"], color="g", ax=myax, kde=True)
        myax.set_xlabel("10-20cm Soil Water [mm]")
        myax.axvline(wb["sw2"].mean(), color="r")
        myax.set_xlim(0, 60)
        myax.set_ylim(0, 70)

        myax = ax[1][1]
        sns.histplot(wb["sw2_percent"], color="g", ax=myax, kde=True)
        myax.set_xlabel("10-20cm Soil Water of Capacity [%]")
        myax.axvline(wb["sw2_percent"].mean(), color="r")
        myax.set_xlim(0, 100)
        myax.set_ylim(0, 70)
        myax.set_ylabel("")

        # -------------------------------------------------------
        myax = ax[2][0]
        sns.histplot(wb["sw"], color="g", ax=myax, kde=True)
        myax.set_xlabel("Total Soil Water [mm]")
        myax.axvline(wb["sw"].mean(), color="r")
        myax.set_xlim(150, 650)
        myax.set_ylim(0, 70)

        #
        myax = ax[2][1]
        sns.histplot(wb["sw_percent"], color="g", ax=myax, kde=True)
        myax.set_xlabel("Total Soil Water of Capacity [%]")
        myax.axvline(wb["sw_percent"].mean(), color="r")
        myax.set_xlim(0, 100)
        myax.set_ylim(0, 70)
        myax.set_ylabel("")

        fig.savefig(f"frames/{doy - 1:05.0f}.png")
        del fig


if __name__ == "__main__":
    main()
