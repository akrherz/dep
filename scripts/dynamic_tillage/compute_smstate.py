"""
Process DEP Soil Moisture to create a state file.

Division of labor and this can run much earlier for the Dynamic Tillage
workflow.

Crontab entry at 3 PM Central for the previous date.
"""

import os
import tempfile
from datetime import date
from functools import partial
from multiprocessing import cpu_count
from multiprocessing.pool import Pool

import click
import geopandas as gpd
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

from dailyerosion.io.dep import read_wb

LOG = logger()

NON_PLASTIC_SOILS = (
    "Sand,Fine sand,Coarse sand,Very fine sand,Loamy sand,Loamy fine sand,"
    "Loamy coarse sand,Loamy very fine sand,Silt"
).split(",")


def job(dates: list[date], tmpdir, huc12: str) -> int:
    """Do work for a HUC12"""
    with get_sqlalchemy_conn("dep") as conn:
        # Build up cross reference of fields and flowpath/OFEs
        # Dates are currently always for the same year
        huc12df = pd.read_sql(
            sql_helper(
                """
    with layers as (
        select sf.mukey, sf.om,
        rank() OVER (partition by mukey order by depthto_mm asc)
        from gssurgo24.dep_soilfractions sf
    ), toplayer as (
        select mukey, om from layers where rank = 1
    )
    select o.ofe, p.huc12_fpath_num, f.huc12_fbndid_num,
    g.plastic_limit as raw_plastic_limit,
    g.wepp_min_sw1 + (g.wepp_max_sw1 - g.wepp_min_sw1) * 0.5796 as fieldcap58,
    case when
        g.textureclass = ANY(:nonplastic) or g.plastic_limit > 50 or tl.om > 10
        or strpos(hydrogroup, 'D') > 0
    then
        g.wepp_min_sw1 + (g.wepp_max_sw1 - g.wepp_min_sw1) * 0.5796
    else
        g.plastic_limit * 0.8
    end as plastic_limit,
    p.huc12_fpath_num || '_' || o.ofe as combo, h.huc12_code as huc12,
    substr(o.landuse, :charat, 1) as crop
    from
    flowpaths p LEFT JOIN flowpath_ofes o on p.fid = o.flowpath
      LEFT JOIN fields f on o.field_id = f.field_id
      LEFT JOIN gssurgo g on o.gssurgo_id = g.id
      LEFT JOIN toplayer tl on g.mukey = tl.mukey::int
      LEFT JOIN huc12 h on f.huc12_id = h.huc12_id
    WHERE h.huc12_code = :huc12 and p.scenario_id = 0
            """
            ),
            conn,
            params={
                "nonplastic": NON_PLASTIC_SOILS,
                "huc12": huc12,
                "charat": dates[0].year - 2007 + 1,
            },
            index_col=None,
        )
    # Provision the storage of the 0-10cm value from WEPP
    huc12df["sw1"] = pd.NA
    # expand the cross reference to include the dates, so the original
    # data frame now has one row per date per metadata row
    entries = len(huc12df.index)
    huc12df = huc12df.loc[huc12df.index.repeat(len(dates))]
    huc12df["date"] = pd.concat([dates] * entries, ignore_index=True).values
    # need to have a valid index to make magic below work
    huc12df = huc12df.reset_index(drop=True)

    reads = 0
    for flowpath, flowpathdf in huc12df.groupby("fpath"):
        wbfn = f"/i/0/wb/{huc12[:8]}/{huc12[8:]}/{huc12}_{flowpath}.wb"
        if not os.path.isfile(wbfn):
            LOG.info("Missing wb: %s", wbfn)
            continue
        try:
            reads += 1
            smdf = read_wb(wbfn)
        except Exception as exp:
            raise ValueError(f"Read {wbfn} failed") from exp
        # Find the dates of interest
        smdf = smdf[smdf["date"].isin(dates)]
        for ofe, gdf in smdf.groupby("ofe"):
            ofedf = flowpathdf[flowpathdf["ofe"] == ofe]
            # Alignment assumption seems reasonable here.
            huc12df.loc[ofedf.index, "sw1"] = gdf["sw1"].values
    huc12df.to_feather(f"{tmpdir}/{huc12}.feather")
    return reads


@click.command()
@click.option("--date", "dt", type=click.DateTime(), help="Date to process")
@click.option("--huc12", type=str, help="HUC12 to process")
@click.option("--year", type=int, help="Year to process 4/10 through 6/15")
def main(dt, huc12, year):
    """Go Main Go."""
    if dt is None:
        dates = pd.Series(pd.date_range(f"{year}-04-10", f"{year}-06-15"))
    else:
        dates = pd.Series([pd.Timestamp(dt.date())])

    outdir = f"/mnt/idep2/data/smstate/{dates[0]:%Y}"
    os.makedirs(outdir, exist_ok=True)

    huc12limiter = "" if huc12 is None else " and huc12_code = :huc12"
    with get_sqlalchemy_conn("dep") as conn:
        huc12df = gpd.read_postgis(
            sql_helper(
                """
            SELECT geom, huc12_code,
            ST_x(st_transform(st_centroid(geom), 4326)) as lon,
            ST_y(st_transform(st_centroid(geom), 4326)) as lat
            from huc12 where scenario_id = 0 {huc12limiter}
            """,
                huc12limiter=huc12limiter,
            ),
            conn,
            params={"huc12": huc12},
            geom_col="geom",
            index_col="huc12_code",
        )
    progress = tqdm(total=len(huc12df.index), disable=not os.isatty(1))
    with (
        Pool(min([8, int(cpu_count() / 2)])) as pool,
        tempfile.TemporaryDirectory() as tmpdir,
    ):
        func = partial(job, dates, tmpdir)
        for _ in pool.imap_unordered(func, huc12df.index.values):
            progress.update(1)
        pool.close()
        pool.join()

        df = pd.concat(
            pd.read_feather(f"{tmpdir}/{huc12}.feather")
            for huc12 in huc12df.index.values
        )
    for ddt, dfdate in df.groupby("date"):
        dfdate.to_feather(f"{outdir}/smstate{ddt:%Y%m%d}.feather")


if __name__ == "__main__":
    main()
