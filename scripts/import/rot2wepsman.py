"""Generate the WEPS management file.

This is very limited at the moment and only supporting Corn/Beans

"""

import glob
import sys
from pathlib import Path

import click
import pandas as pd
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from tqdm import tqdm

from dailyerosion.util import load_scenarios

LOG = logger()
YEARS = 20


def do_flowpath(
    scenario: int,
    weps_operations: dict[str, str],
    metadata: dict,
):
    """Process a given flowpath."""
    # Get the rotation file for OFE1, since we only process it.
    rotfn = (
        f"/i/{scenario}/rot/{metadata['huc12_code'][:8]}/{metadata['huc12_code'][8:]}"
        f"/{metadata['huc12_code']}_{metadata['huc12_fpath_num']}_1.rot"
    )
    # Our generated man file.
    wepsfn = (
        Path("/i")
        / f"{scenario}"
        / "weps_man"
        / f"{metadata['huc12_code'][:8]}"
        / f"{metadata['huc12_code'][8:]}"
        / f"{metadata['huc12_code']}_{metadata['huc12_fpath_num']}.man"
    )
    if not wepsfn.parent.exists():
        wepsfn.parent.mkdir(parents=True)

    # Flying a bit blind here and making life choices
    with open(wepsfn, "w") as outfh, open(rotfn) as rotfh:
        outfh.write(f"Version: 1.7\n*START {YEARS}\nN\n#----\nB|0\n")
        rotcode = None
        for line in rotfh:
            if line.startswith("Name = "):
                rotcode = line.split("=")[1].strip().split("-")[0]
            if (
                " Tillage " not in line
                and "Harvest" not in line
                and "Perennial" not in line
            ):
                continue
            (month, day, year, _, oplabel, opcropdef, *_) = line.split()
            cropcode = rotcode[int(year) - 1]
            # Can't deal with Forest yet
            if cropcode == "F":
                continue
            # Going to default to Soybean for anything we currently don't know
            # about. This will get fixed eventually.
            if cropcode not in ["C", "B", "P", "W"]:
                cropcode = "B"
            if oplabel in ["Harvest-Annual", "Cut-Perennial"]:
                payload = weps_operations[f"HARVEST_{cropcode}"]
            elif oplabel == "Plant-Perennial":
                payload = weps_operations[f"FCSTACDP_{cropcode}"]
            else:
                opcropdef = opcropdef.replace("OpCropDef.", "")
                # Handled later
                if opcropdef == "FCSTACDP" and cropcode != "W":
                    continue
                # Unhandled
                if opcropdef in ["ANHYDROS", "HASPTCT", "DRDDO", "CHISCOST"]:
                    continue
                if opcropdef.startswith("PL") or opcropdef == "DRNTFRFC":
                    opcropdef = f"{opcropdef}_{cropcode}"
                try:
                    payload = weps_operations[opcropdef]
                except KeyError:
                    LOG.warning(
                        "Unable to find operation for %s, crop %s, aborting",
                        opcropdef,
                        cropcode,
                    )
                    sys.exit(1)
            # NOTE: WEPS management files are 1 indexed, not real years!!!
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
        progress.set_description(
            f"{row['huc12_code']} {row['huc12_fpath_num']:04.0f}"
        )
        do_flowpath(scenario, weps_operations, row)


@click.command()
@click.option("-s", "--scenario", type=int, help="DEP Scenario", required=True)
def main(scenario: int):
    """Go main go"""
    with get_sqlalchemy_conn("dep") as pgconn:
        df = pd.read_sql(
            sql_helper("""
        SELECT huc12_fpath_num, huc12_code
        from flowpath p JOIN flowpath_ofe o on (p.flowpath_id = o.flowpath_id)
        JOIN field f on (o.field_id = f.field_id)
        JOIN huc12 h on (h.huc12_id = f.huc12_id)
        WHERE p.scenario_id = :scenario and (
        strpos(landuse, 'C') > 0 or strpos(landuse, 'B') > 0
        )
        ORDER by huc12_code ASC
            """),
            pgconn,
            params={"scenario": get_flowpath_scenario(scenario)},
        )

    workflow(df, scenario)


if __name__ == "__main__":
    main()
