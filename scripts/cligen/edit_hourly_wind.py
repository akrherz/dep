"""Hourly wind file editor for WEPS.

Materialize the IEMRE hourly wind information into files used by WEPS for the
Daily Erosion project to run sweep.

Storage is in /i/0/wind/{gid:06.0f[:3]}/{gid}.win

- Runs from cron for the previous day at 1 AM local
- Background --init runs with a keep-out period before 5 AM

"""

import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import click
import numpy as np
import pandas as pd
from metpy.calc import wind_direction
from metpy.units import units
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.iemre import get_hourly_ncname, hourly_offset
from pyiem.util import logger, ncopen
from tqdm import tqdm

LOG = logger()
US_CENTRAL = ZoneInfo("America/Chicago")


def init_workflow(fn: Path, iemre_x: int, iemre_y: int):
    """Initialize the file and do the lengthy processing."""
    # Load up all the wind data, Woof
    years = datetime.now().year - 2006
    # Allow some extra space
    por = np.zeros(366 * years * 24, dtype=np.float32)
    por_drct = np.zeros(366 * years * 24, dtype=np.float32)
    idx = 0
    for year in range(2007, datetime.now().year + 1):
        ncfn = Path(get_hourly_ncname(year))
        if not ncfn.is_file():
            # TODO, abort
            LOG.warning("Missing %s, aborting", ncfn)
            continue
        # Woof again
        with ncopen(ncfn) as nc:
            # meh
            uwnd = nc.variables["uwnd"][:, iemre_y, iemre_x].filled(0)
            vwnd = nc.variables["vwnd"][:, iemre_y, iemre_x].filled(0)
            data = np.hypot(uwnd, vwnd)
            drct = wind_direction(uwnd * units("m/s"), vwnd * units("m/s"))
            por[idx : idx + len(data)] = data
            por_drct[idx : idx + len(data)] = drct.magnitude
            idx += len(data)

    # Ensure that the directory tree exists
    fn.parent.mkdir(parents=True, exist_ok=True)
    with open(fn, "w", encoding="ascii") as fh:
        # WEPS baseline is picky about this format.
        fh.write("""#   WIND_GEN4
#
#
#
#
#
#\n""")
        # Take some liberties here with time zones and DST/CDT ugliness
        idx = 5
        for dt in pd.date_range("2007/01/01", f"{datetime.now().year}/12/31"):
            hourly = ""
            mxdir = 0
            maxval = 0
            for ws, drct in zip(
                por[idx : idx + 24], por_drct[idx : idx + 24], strict=True
            ):
                if ws > maxval:
                    maxval = ws
                    mxdir = drct
                hourly += f"{ws:4.1f} "
            fh.write(f" {dt:%-2d} {dt:%-2m} {dt:%Y} {mxdir:5.1f} {hourly}\n")
            idx += 24


def daily_workflow(progress: tqdm, dt: date):
    """Process a given date."""
    if f"{dt:%m%d}" == "1231":
        LOG.warning("Processing %s is a TODO, punting", dt)
        return
    tidx0 = hourly_offset(
        datetime(dt.year, dt.month, dt.day, tzinfo=US_CENTRAL)
    )
    with ncopen(get_hourly_ncname(dt.year)) as nc:
        uwnd = nc.variables["uwnd"][tidx0 : tidx0 + 24, :, :].filled(0)
        vwnd = nc.variables["vwnd"][tidx0 : tidx0 + 24, :, :].filled(0)
        data = np.hypot(uwnd, vwnd)
        drct = wind_direction(uwnd * units("m/s"), vwnd * units("m/s")).m
    needle = f" {dt:%-2d} {dt:%-2m} {dt:%Y}"
    for gid, row in progress:
        fn = Path("/i/0/wind") / f"{gid:06.0f}"[:3] / f"{gid:06.0f}.win"
        if not fn.is_file():
            progress.write(f"Missing {fn}, skipping")
            continue
        with open(fn, encoding="ascii") as fh:
            lines = fh.readlines()
        for linenum, line in enumerate(lines):
            if not line.startswith(needle):
                continue
            hourly = ""
            mxdir = 0
            maxval = 0
            for ws, thisdrct in zip(
                data[:, row["gridy"], row["gridx"]],
                drct[:, row["gridy"], row["gridx"]],
                strict=True,
            ):
                if ws > maxval:
                    maxval = ws
                    mxdir = thisdrct
                hourly += f"{ws:4.1f} "
            lines[linenum] = (
                f" {dt:%-2d} {dt:%-2m} {dt:%Y} {mxdir:5.1f} {hourly}\n"
            )
            break
        with open(fn, "w", encoding="ascii") as fh:
            fh.writelines(lines)


@click.command()
@click.option("--init", is_flag=True, help="Initialize files")
@click.option(
    "--date",
    "dt",
    type=click.DateTime(),
    help="Date to edit in YYYY-MM-DD format",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help=("For init runs, force the generation of files (overwrite)."),
)
def main(init: bool, dt: datetime | None, overwrite: bool):
    """Go Main Go."""
    # Get all the gids from IEMRE
    with get_sqlalchemy_conn("iemre") as conn:
        # Focused on Minnesota ATTM
        giddf = pd.read_sql(
            sql_helper("""
    select gid, gridx, gridy from iemre_grid where
    ST_Contains(ST_MakeEnvelope(-108, 32, -84, 52, 4326), cell_center)
                """),
            conn,
            index_col="gid",
        )
    LOG.info("Found %s IEMRE gids", len(giddf.index))
    progress = tqdm(
        giddf.iterrows(),
        total=len(giddf.index),
        disable=not sys.stdout.isatty(),
    )
    if init:
        for gid, row in progress:
            fn = Path("/i/0/wind") / f"{gid:06.0f}"[:3] / f"{gid:06.0f}.win"
            progress.set_description(str(fn))
            if fn.is_file() and not overwrite:
                continue
            while datetime.now(US_CENTRAL).hour < 5:
                progress.write("Sleeping 1200s due to keep-out period < 5AM")
                time.sleep(1200)
            init_workflow(fn, row["gridx"], row["gridy"])
        return
    daily_workflow(progress, dt.date())


if __name__ == "__main__":
    main()
