"""Bootstrap needed climate files by copying from existing files.

The flowpath creation process creates database entries for desired climate
files. This script cross checks this with what exists on the filesystem and
then will copy the closest nearby file to this new location.  Later processing
will better localize this file with real data.

"""

import subprocess
from pathlib import Path
from shutil import copyfile

import click
import geopandas as gpd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

LOG = logger()


@click.command()
@click.option("--scenario", "-s", type=int, required=True, help="Scenario ID")
def main(scenario: int):
    """Go Main Go."""
    # Load up the climate_files
    with get_sqlalchemy_conn("dep") as conn:
        clidf = gpd.read_postgis(
            sql_helper("""
    select climate_file_id, filepath, geom,
    st_x(geom) as lon, st_y(geom) as lat
    from climate_file WHERE scenario_id = :scenario
                 """),
            conn,
            params={"scenario": scenario},
            index_col="climate_file_id",
            geom_col="geom",
        ).to_crs(epsg=5070)  # Otherwise will complain about geographic CRS
    LOG.info("Found %s climate files", len(clidf.index))

    created = 0
    failed = 0
    progress = tqdm(clidf.iterrows(), total=len(clidf.index))
    for _, row in progress:
        progress.set_description(f"Created {created}, Failed: {failed}")
        wantedfn = Path(row["filepath"])
        if wantedfn.is_file():
            continue
        # Find the nearest 1_000 files
        dist = clidf.geometry.distance(row["geom"]).sort_values(ascending=True)
        copyfn = None
        for nbrid in dist.index[1:1001]:
            nbrfn = clidf.at[nbrid, "filepath"]
            if Path(nbrfn).is_file():
                copyfn = nbrfn
                break
        if copyfn is None:
            progress.write(f"Error: {row['filepath']} has no neighbors")
            failed += 1
            continue
        wantedfn.parent.mkdir(parents=True, exist_ok=True)
        progress.write(f"Copying {copyfn} to {wantedfn}")
        copyfile(copyfn, wantedfn)
        # Now fix the header to match its location
        subprocess.run(
            [
                "python",
                "edit_cli_header.py",
                f"--filename={wantedfn}",
                f"--lat={row['lat']}",
                f"--lon={row['lon']}",
            ],
            check=True,
        )
        created += 1


if __name__ == "__main__":
    main()
