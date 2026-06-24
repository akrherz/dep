"""Keep the CLI file headers in sync."""

import os
from pathlib import Path

import click
import numpy as np
import pandas as pd
from pyiem.grid.nav import get_nav
from pyiem.iemre import find_ij, get_dailyc_ncname
from pyiem.util import convert_value, logger, ncopen
from tqdm import tqdm

from dailyerosion.util import get_cli_fname

LOG = logger()
# Untracked here, but this version was used to fix the header column labels
REV = "HeaderRev: v20250723.1"


def monthly_avgs(lon, lat, domain):
    """Do more work."""
    i, j = find_ij(lon, lat, domain)
    with ncopen(get_dailyc_ncname(domain)) as nc:
        highc = convert_value(
            nc.variables["high_tmpk"][:, j, i], "degK", "degC"
        )
        lowc = convert_value(nc.variables["low_tmpk"][:, j, i], "degK", "degC")
        p01d = nc.variables["p01d"][:, j, i]
        # MJ to langleys
        swdn = nc.variables["swdn"][:, j, i] * 23.9
    df = pd.DataFrame(
        {
            "highc": highc,
            "lowc": lowc,
            "p01d": p01d,
            "swdn": swdn,
        },
        index=pd.date_range("2000/01/01", "2000/12/31"),
    )
    return df.resample("ME").agg(
        {"highc": "mean", "lowc": "mean", "p01d": "sum", "swdn": "mean"}
    )


def get_elevation(lon: float, lat: float) -> float:
    """Use opentopo."""
    # API services have limits, so alas
    # https://zenodo.org/records/14537811
    ncfn = Path(__file__).parent / "GMTED2010_median_30arcsec.nc4"
    if not ncfn.is_file():
        raise FileNotFoundError(f"Missing {ncfn}, download it to cwd!")
    with ncopen(ncfn) as nc:
        lons = nc.variables["lon"]  # deg E already -180 to 180
        lats = nc.variables["lat"]
        i = np.digitize(lon, lons)
        j = np.digitize(lat, lats)
        return nc.variables["surface_altitude_median"][j, i]


def process(lon: float, lat: float, clifn: str, domain: str):
    """Edit the given climate file."""
    with open(clifn, encoding="utf-8") as fh:
        lines = fh.readlines()
    # Set Station Name to something descriptive
    lines[2] = f"Station: Daily Erosion Project 0.01deg Grid Cell {REV}\n"
    # Set Lat/Lon from filename
    tokens = lines[4].strip().split()
    # Get elevation from a reference netcdf file
    elev = get_elevation(lon, lat)
    lines[4] = (
        f"{lat:.2f}  {lon:.2f}  {elev:.0f} "
        f"{tokens[3]} {tokens[4]} {tokens[5]}\n"
    )
    # Compute monthly avg high, low, radiation, rain
    df = monthly_avgs(lon, lat, domain)
    lines[6] = " ".join(f"{x:-5.1f}" for x in df["highc"].values) + "\n"
    lines[8] = " ".join(f"{x:-5.1f}" for x in df["lowc"].values) + "\n"
    if lon > 1000:  # These variables are not ready yet
        lines[10] = " ".join(f"{x:-5.1f}" for x in df["swdn"].values) + "\n"
        lines[12] = " ".join(f"{x:-5.1f}" for x in df["p01d"].values) + "\n"
    with open(clifn, "w", encoding="utf-8") as fh:
        fh.write("".join(lines))


def omnibus(domain: str):
    """Do em all."""
    nav = get_nav("IEMRE", domain)
    progress = tqdm(np.arange(nav.left_edge, nav.right_edge + 0.01, 0.01))
    for lon in progress:
        progress.set_description(f"{lon:.2f}")
        for lat in np.arange(nav.bottom_edge, nav.top_edge + 0.01, 0.01):
            try:
                clifn = get_cli_fname(lon, lat)
            except ValueError:  # outside of bounds
                continue
            if not os.path.isfile(clifn):
                continue
            process(lon, lat, clifn, domain)


@click.command()
@click.option("--domain", default="conus", help="The domain to edit")
@click.option("--filename", help="The file to edit")
@click.option("--lon", type=float, help="Longitude of the grid cell")
@click.option("--lat", type=float, help="Latitude of the grid cell")
def main(
    domain: str, filename: str | None, lon: float | None, lat: float | None
):
    """We ride or die."""
    if filename is None:
        omnibus(domain)
        return
    process(lon, lat, filename, domain)


if __name__ == "__main__":
    main()
