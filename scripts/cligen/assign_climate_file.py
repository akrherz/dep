"""Make sure our database has things right with climate_file."""

import sys

from pyiem.database import get_dbconn
from pyiem.util import logger

from dailyerosion.util import get_cli_fname

LOG = logger()


def main(argv):
    """Go Main Go."""
    scenario = int(argv[1])
    pgconn = get_dbconn("dep")
    cursor = pgconn.cursor()
    cursor2 = pgconn.cursor()
    # Get the climate_scenario
    cursor.execute(
        "SELECT climate_scenario from scenario where scenario_id = %s",
        (scenario,),
    )
    clscenario = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT st_x(st_pointn(st_transform(geom, 4326), 1)),
        st_y(st_pointn(st_transform(geom, 4326), 1)), flowpath_id
        from flowpath WHERE scenario_id = %s and climate_file_id is null
    """,
        (scenario,),
    )
    ok = wrong = updated = 0
    for row in cursor:
        fn = get_cli_fname(row[0], row[1], clscenario)
        cursor2.execute(
            "update flowpath SET "
            "climate_file_id = (select climate_file_id from climate_file "
            "where filepath = %s and scenario_id = %s) WHERE flowpath_id = %s",
            (fn, clscenario, row[2]),
        )
        updated += 1
        if updated % 1000 == 0:
            LOG.info("updated %s rows", updated)
            cursor2.close()
            pgconn.commit()
            cursor2 = pgconn.cursor()
    LOG.info(
        "%s rows updated: %s ok: %s wrong: %s",
        cursor.rowcount,
        updated,
        ok,
        wrong,
    )
    cursor2.close()
    pgconn.commit()


if __name__ == "__main__":
    main(sys.argv)
