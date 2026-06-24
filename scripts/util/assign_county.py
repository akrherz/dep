"""Compute the county a HUC12 belongs in."""

from pyiem.database import get_dbconn
from pyiem.util import logger

LOG = logger()


def main():
    """Go Main Go."""
    postgis = get_dbconn("postgis")
    pcursor = postgis.cursor()

    dep = get_dbconn("dep")
    cursor = dep.cursor()
    cursor2 = dep.cursor()

    cursor.execute(
        """with data as (
        SELECT ST_Transform(ST_Centroid(geom), 4326) as geo,
        huc12_id, huc12_code
        from huc12 where ugc is null)

        SELECT ST_x(geo), ST_y(geo), huc12_id, huc12_code from data
    """
    )
    for row in cursor:
        pcursor.execute(
            """
        select ugc from ugcs where end_ts is null and
        ST_Contains(geom, ST_POINT(%s, %s, 4326))
        and substr(ugc, 3, 1) = 'C'
        """,
            (row[0], row[1]),
        )
        if pcursor.rowcount == 0:
            LOG.info("failed to find a county for HUC12: %s", row[3])
            continue
        ugc = pcursor.fetchone()[0]
        cursor2.execute(
            "UPDATE huc12 SET ugc = %s where huc12_id = %s",
            (ugc, row[2]),
        )

    cursor2.close()
    dep.commit()


if __name__ == "__main__":
    main()
