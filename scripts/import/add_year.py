"""Update the database storage to add another value."""

import click
from pyiem.database import get_dbconn
from pyiem.util import logger

LOG = logger()


@click.command()
@click.option("--newyear", type=int, required=True)
def main(newyear: int):
    """Go Main Go."""
    length_to_fix = int(newyear - 2007)
    LOG.info("For %s fixing length of %s", newyear, length_to_fix)
    pgconn = get_dbconn("dep")
    cursor = pgconn.cursor()
    cursor.execute(
        """
        UPDATE field SET
        landuse = landuse || substr(landuse, %s, 1),
        management = management || substr(management, %s, 1)
        where length(landuse) = %s
        """,
        (length_to_fix - 1, length_to_fix - 1, length_to_fix),
    )
    LOG.info("%s updated %s rows", newyear, cursor.rowcount)
    cursor.close()
    pgconn.commit()


if __name__ == "__main__":
    main()
