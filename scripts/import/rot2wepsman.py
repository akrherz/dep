"""Generate the WEPS management file.

This is very limited at the moment and only supporting Corn/Beans

"""

import glob
from pathlib import Path

import click
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

from dailyerosion.util import load_scenarios

LOG = logger()


def do_flowpath(
    scenario: int,
    weps_operations: dict[str, str],
    metadata: dict,
):
    """Process a given flowpath."""
    # Get the rotation file for OFE1, since we only process it.
    rotfn = (
        f"/i/{scenario}/rot/{metadata['huc_12'][:8]}/{metadata['huc_12'][8:]}"
        f"/{metadata['huc_12']}_{metadata['fpath']}_1.rot"
    )
    # Our generated man file.
    wepsfn = (
        Path("/i")
        / f"{scenario}"
        / "weps_man"
        / f"{metadata['huc_12'][:8]}"
        / f"{metadata['huc_12'][8:]}"
        / f"{metadata['huc_12']}_{metadata['fpath']}.man"
    )
    if not wepsfn.parent.exists():
        wepsfn.parent.mkdir(parents=True)

    # Flying a bit blind here and making life choices
    with open(wepsfn, "w") as outfh, open(rotfn) as rotfh:
        outfh.write("Version: 1.7\n*START 2\nN\n#----\nB|0\n")
        rotcode = None
        for line in rotfh:
            if line.startswith("Name = "):
                rotcode = line.split("=")[1].strip().split("-")[0]
            if line.find(" Tillage ") == -1 and line.find("Harvest") == -1:
                continue
            (month, day, year, _, oplabel, opcropdef, *_) = line.split()
            cropcode = rotcode[int(year) - 1]
            if cropcode not in ["C", "B"]:
                continue
            if oplabel == "Harvest-Annual":
                payload = weps_operations[f"HARVEST_{cropcode}"]
            else:
                opcropdef = opcropdef.replace("OpCropDef.", "")
                if opcropdef.startswith("PL"):
                    opcropdef = f"{opcropdef}_{cropcode}"
                try:
                    payload = weps_operations[opcropdef]
                except KeyError:
                    continue
            outfh.write(
                f"D {int(day):02.0f}/{int(month):02.0f}/{int(year):02.0f}\n"
            )
            outfh.write(payload + "\n#----\n")
        outfh.write("*END\n*EOF")


def get_flowpath_scenario(scenario):
    """internal accounting."""
    sdf = load_scenarios()
    return int(sdf.at[scenario, "flowpath_scenario"])


def workflow(df: pd.DataFrame, scenario: int):
    """Go main go"""
    progress = tqdm(df.iterrows(), total=len(df.index))
    weps_operations = {}
    for fn in glob.glob("weps_operations/*.txt"):
        with open(fn) as fh:
            weps_operations[fn.split("/")[1][:-4]] = fh.read().strip()
    for _idx, row in progress:
        progress.set_description(f"{row['huc_12']} {row['fpath']:04.0f}")
        do_flowpath(scenario, weps_operations, row)


@click.command()
@click.option("-s", "--scenario", type=int, help="DEP Scenario", required=True)
def main(scenario: int):
    """Go main go"""
    with get_sqlalchemy_conn("idep") as pgconn:
        df = pd.read_sql(
            sql_helper("""
        SELECT fpath, huc_12 from flowpaths f JOIN flowpath_ofes o
        on (f.fid = o.flowpath)
        WHERE f.scenario = :scenario and strpos(landuse, 'C') > 0
        ORDER by huc_12 ASC
            """),
            pgconn,
            params={"scenario": get_flowpath_scenario(scenario)},
        )

    workflow(df, scenario)


if __name__ == "__main__":
    main()
