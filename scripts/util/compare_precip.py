"""Something precip related."""

from datetime import date

import matplotlib.pyplot as plt
import pandas as pd
from pyiem.database import get_dbconn
from pyiem.network import Table as NetworkTable
from pyiem.plot import MapPlot
from pyiem.util import mm2inch


def two(year):
    """Compare yearly totals in a scatter plot"""
    coop = get_dbconn("coop")
    ccursor = coop.cursor()
    idep = get_dbconn("dep")
    icursor = idep.cursor()

    ccursor.execute(
        """
        SELECT station, sum(precip) from alldata_ia
        WHERE year = %s and station != 'IA0000'
        and substr(station, 3, 1) != 'C' GROUP by station ORDER by station ASC
    """,
        (year,),
    )
    nt = NetworkTable("IACLIMATE")
    rows = []
    for row in ccursor:
        station = row[0]
        precip = row[1]
        if station not in nt.sts:
            continue
        lon = nt.sts[station]["lon"]
        lat = nt.sts[station]["lat"]
        icursor.execute(
            """
            select huc12_code from huc12
            where ST_Contains(geom,
            ST_Transform(ST_Point(%s, %s, 4326), 5070))
            and scenario_id = 0
        """,
            (lon, lat),
        )
        if icursor.rowcount == 0:
            continue
        huc12 = icursor.fetchone()[0]
        icursor.execute(
            """
        select sum(qc_precip_mm) from
        water_results_by_huc12 w JOIN huc12 h ON (w.huc12_id = h.huc12_id)
        WHERE valid between %s and %s and huc12_code = %s and w.scenario_id = 0
        """,
            (date(year, 1, 1), date(year, 12, 31), huc12),
        )
        val = icursor.fetchone()[0]
        if val is None:
            continue
        rows.append(
            dict(
                station=station,
                precip=precip,
                iprecip=mm2inch(val),
                lat=lat,
                lon=lon,
            )
        )
    df = pd.DataFrame(rows)
    df["diff"] = df["iprecip"] - df["precip"]
    bias = df["diff"].mean()
    print(
        "%s %5.2f %5.2f %5.2f"
        % (year, df["iprecip"].mean(), df["precip"].mean(), bias)
    )
    m = MapPlot(
        title=("%s IDEP Precipitation minus IEM Climodat (inch)") % (year,),
        subtitle=("HUC12 Average minus point observation, Overall bias: %.2f")
        % (bias,),
        axisbg="white",
    )
    m.plot_values(df["lon"], df["lat"], df["diff"], fmt="%.2f", labelbuffer=1)
    m.postprocess(filename="%s_map.png" % (year,))
    m.close()

    (fig, ax) = plt.subplots(1, 1)
    ax.scatter(df["precip"], df["iprecip"])
    ax.grid(True)
    ylim = ax.get_ylim()
    ax.plot([ylim[0], ylim[1]], [ylim[0], ylim[1]], lw=2)
    ax.set_xlabel("IEM Climodat Precip")
    ax.set_ylabel("IDEP HUC12 Precip")
    ax.set_title("%s Precipitation Comparison, bias=%.2f" % (year, bias))
    fig.savefig("%s_xy.png" % (year,))
    plt.close()


def one():
    """One."""
    iem = get_dbconn("iem")

    idep = get_dbconn("dep")
    icursor = idep.cursor()

    # Get obs
    df = pd.read_sql(
        """SELECT day, min(pday) as min_pday, avg(pday) as avg_pday,
        max(pday) as max_pday
        from summary_2014 s JOIN stations t on
      (t.iemid = s.iemid) WHERE t.network = 'IA_ASOS'
      GROUP by day""",
        iem,
        index_col="day",
    )

    # Get idep
    # Due to join issues, we hardcode the huc12 count
    icursor.execute(
        "SELECT count(*) from huc12 where states = 'IA' and scenario_id = 0"
    )
    huccount = icursor.fetchone()[0]
    df2 = pd.read_sql(
        """
        WITH iahuc12 as (
            SELECT huc12_id from huc12
            where states = 'IA' and scenario_id = 0
        )
        SELECT valid, sum(qc_precip_mm) / 25.4 as precip
        from water_results_by_huc12 r
        JOIN iahuc12 i on (r.huc12_id = i.huc12_id)
        WHERE r.scenario_id = 0 and r.valid >= '2014-01-01' and
        r.valid < '2015-01-01' GROUP by valid
      """,
        idep,
        index_col="valid",
    )

    df["idep"] = df2["precip"] / huccount
    df = df.fillna(0)
    df["diff2max"] = df["max_pday"] - df["idep"]
    df["diff2avg"] = df["avg_pday"] - df["idep"]

    df = df.sort_values(by="diff2avg", ascending=False)

    df.to_excel("test.xls")


if __name__ == "__main__":
    one()
