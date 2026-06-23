"""Query CSU CSIP for its soil file for WEPS.

DEP specific query:
    select distinct g.mukey, p.cokey from flowpath f, flowpath_ofe o,
    gssurgo g, gssurgo25.dep_soilparameters p where
    scenario_id = 0 and o.flowpath_id = f.flowpath_id
    and o.gssurgo_id = g.gssurgo_id and g.mukey = p.mukey::int
"""

from pathlib import Path

import pandas as pd
import requests
from pyiem.database import get_sqlalchemy_conn, sql_helper
from tqdm import tqdm


def get_cokey(lon: float, lat: float) -> str | None:
    """Fetch what it has."""
    resp = requests.post(
        "http://csip.engr.colostate.edu:8083/csip-soils/d/basicsoil/2.0",
        headers={"Content-Type": "application/json"},
        json={
            "parameter": [
                {
                    "name": "aoa_geometry",
                    "type": "Point",
                    "coordinates": [lon, lat],
                }
            ]
        },
    )
    data = resp.json()
    cokey = None
    for result in data["result"][0]["value"][0]:
        if result["name"] == "Map Units":
            for entry in result["value"][0]:
                if entry["name"] == "Components":
                    for comp in entry["value"][0]:
                        if comp["name"] == "cokey":
                            cokey = comp["value"]
                            break

    return cokey


def get_url_by_cokey(cokey: str) -> str | None:
    """Get URL by cokey."""
    resp = requests.post(
        "http://csip.engr.colostate.edu:8083/csip-soils/d/wepssoilinput/3.0",
        headers={"Content-Type": "application/json"},
        json={
            "parameter": [
                {
                    "name": "cokey",
                    "value": cokey,
                }
            ]
        },
    )
    data = resp.json()
    if "result" not in data:
        return None
    return data["result"][0]["value"]


def main():
    """Go Main"""
    # Appears web service has GSSURGO 25, so we can cross-ref DEP here.
    with get_sqlalchemy_conn("dep") as conn:
        depsoils = pd.read_sql(
            sql_helper("""
            SELECT mukey, max(cokey) as cokey from gssurgo25.dep_soilparameters
            group by mukey
            """),
            conn,
        )
    progress = tqdm(depsoils.itertuples(), total=len(depsoils.index))
    downloaded = 0
    for row in progress:
        # Present belief is that CSIP emits FY2024 files
        depfn = Path("/i/0/weps_soil_fy2024") / f"{row.mukey}.ifc"
        if depfn.exists():
            continue
        url = get_url_by_cokey(row.cokey)
        if url is None:
            progress.write(f"cokey {row.cokey} failed.")
            continue
        resp = requests.get(url)
        if resp.status_code == 200:
            downloaded += 1
            progress.set_description(f"DL: {downloaded}")
            with open(depfn, "wb") as fh:
                fh.write(resp.content)


if __name__ == "__main__":
    main()
