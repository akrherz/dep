"""Dump OFE metadata."""

import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger

LOG = logger()
# 2007 is skipped
YEARS = 6.0


def main():
    """Do the computations for the flowpath."""
    with get_sqlalchemy_conn("idep") as conn:
        meta = pd.read_sql(
            sql_helper("""
    with pop as (
        SELECT MU.mukey::int as mukey
             ,C.cokey
             ,C.compname
             ,C.comppct_r
             ,hrz.chkey
             ,hrz.hzdept_r
             ,hrz.hzdepb_r
             ,tgrp.texture as tgTexture
             ,tgrp.rvindicator as tgRVind
             ,txt.texcl as txTxtClass
             ,hrz.dbthirdbar_r as bulk_density
             ,hrz.sandtotal_r as sand_content
             ,hrz.claytotal_r as clay_content
             ,hrz.awc_r + (hrz.wfifteenbar_r / 100.) as field_capacity
             ,hrz.wfifteenbar_r as wilting_point
             ,hrz.ksat_r as hydro_conduct
             ,coalesce(hrz.cec7_r, hrz.ecec_r) as cec
             ,hrz.om_r as organic_matter
              , ROW_NUMBER() OVER (PARTITION BY MU.mukey
                ORDER BY C.comppct_r desc) as rowNbr

        FROM gssurgo24.MAPUNIT MU left join gssurgo24.component C ON
                       MU.mukey = C.mukey
         LEFT JOIN gssurgo24.chorizon hrz ON hrz.cokey = C.cokey
          LEFT JOIN gssurgo24.chtexturegrp tgrp ON hrz.chkey = tgrp.chkey
           LEFT JOIN gssurgo24.chtexture txt ON txt.chtgkey = tgrp.chtgkey

        WHERE  C.majcompflag = 'Yes' and hrz.hzdept_r = 0
                       ),
        soilstuff as (
            select * from pop where rowNbr = 1
        )

                select huc_12, fpath as flowpath, ofe,
                st_x(st_pointn(st_transform(o.geom, 4326), 1)) as lon,
                st_y(st_pointn(st_transform(o.geom, 4326), 1)) as lat,
                o.bulk_slope,
                o.max_slope,
                o.landuse, o.management,
                g.mukey as surgo24,
                kwfact, hydrogroup, d.fbndid,
                o.real_length as length, groupid,
                substr(o.management, 17, 1) as tillage2023,
                substr(o.landuse, 17, 1) as landuse2023,
                s.bulk_density, s.sand_content, s.clay_content,
                s.field_capacity,
                s.wilting_point, s.hydro_conduct, s.cec, s.organic_matter
                from flowpath_ofes o JOIN flowpaths f on
                (o.flowpath = f.fid)
                JOIN gssurgo g on (o.gssurgo_id = g.id)
                JOIN soilstuff s on (g.mukey = s.mukey)
                JOIN fields d on (o.field_id = d.field_id)
                WHERe f.scenario = 0
            """),
            conn,
        )
    meta.to_csv(
        "flowpath_ofe_meta.csv",
        index=False,
    )


if __name__ == "__main__":
    main()
