"""When DEP expands, we have a problem that we have no close by precip files.

So lets ensure we have one file per 0.1 degree lat and lon, we can then use
these to fast-start newly expanded areas...
"""

import os
import shutil

import click
import numpy as np
from pyiem.database import get_dbconnc
from pyiem.grid.nav import get_nav
from pyiem.util import ncopen
from tqdm import tqdm

from dailyerosion.util import get_cli_fname


def finder(lon, lat, clscenario):
    """The logic of finding a file."""
    # https://stackoverflow.com/questions/398299/looping-in-a-spiral
    x = y = 0
    dx = 0
    dy = -1
    # points near the domain edge need to seach a bit further than 0.25deg
    X = 40
    Y = 40
    for _ in range(40**2):
        if (-X / 2 < x <= X / 2) and (-Y / 2 < y <= Y / 2):
            newfn = get_cli_fname(lon + x * 0.01, lat + y * 0.01, clscenario)
            if os.path.isfile(newfn):
                return newfn, x, y
        if x == y or (x < 0 and x == -y) or (x > 0 and x == 1 - y):
            dx, dy = -dy, dx
        x, y = x + dx, y + dy
    return None, None, None


@click.command()
@click.option("--domain", required=True, help="The domain to init.")
def main(domain: str):
    """Go Main Go."""
    # We shall use this file, no mater what
    SCENARIO = 0
    created = 0
    nav = get_nav("IEMRE", domain)
    # round to nearest 0.1 degree
    left = round(nav.left_edge, 1)
    bottom = round(nav.bottom_edge, 1)
    # https://gpm.nasa.gov/data/directory/imerg-land-sea-mask-netcdf
    nc = ncopen("/tmp/IMERG_land_sea_mask.nc")
    mask = nc.variables["landseamask"][:]
    nc.close()
    conn, cursor = get_dbconnc("dep" if domain == "conus" else f"dep_{domain}")
    progress = tqdm(np.arange(left, nav.right_edge + 0.1, 0.1))
    for lon in progress:
        for lat in np.arange(bottom, nav.top_edge + 0.1, 0.1):
            progress.set_description(f"Created {created}")
            # crude for non-conus
            j = int((lat + 90) * 10.0)
            if lon < 0:
                i = int((lon + 360) * 10.0)
            else:
                i = int(lon * 10.0)
            if mask[j, i] > 50:  # arb
                continue
            try:
                fn = get_cli_fname(lon, lat, SCENARIO)
            except ValueError:  # Potentially out of bounds
                continue
            # Check if we have this file
            if os.path.isfile(fn):
                continue
            created += 1
            # Ensure the directory exists
            os.makedirs(os.path.dirname(fn), exist_ok=True)
            # Copy random file
            shutil.copyfile("/i/0/cli/092x042/092.56x042.98.cli", fn)
            # create database entry
            cursor.execute(
                """
                INSERT into climate_file (scenario_id, filepath, geom)
                VALUES (%s, %s, ST_Point(%s, %s, 4326))
            """,
                (SCENARIO, fn, lon, lat),
            )
            if created % 100 == 0:
                cursor.close()
                conn.commit()
                cursor = conn.cursor()
    cursor.close()
    conn.commit()

    print(f"We just created {created} new files")


if __name__ == "__main__":
    main()
