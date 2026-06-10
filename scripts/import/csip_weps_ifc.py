"""Query CSU CSIP for its soil file for WEPS."""

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
    with get_sqlalchemy_conn("idep") as conn:
        depsoils = pd.read_sql(
            sql_helper("""
            -- hacky
            SELECT mukey, max(cokey) as cokey from gssurgo25.dep_soilparameters
            group by mukey
            """),
            conn,
            index_col="mukey",
        )
    progress = tqdm(depsoils.itertuples(), total=len(depsoils.index))
    for row in progress:
        depfn = Path("/i/0/weps_soil_fy2025") / f"{row[0]}.ifc"
        if depfn.exists():
            continue
        url = get_url_by_cokey(row.cokey)
        if url is None:
            progress.write(f"cokey {row.cokey} failed.")
            continue
        resp = requests.get(url)
        if resp.status_code == 200:
            with open(depfn, "wb") as fh:
                fh.write(resp.content)


if __name__ == "__main__":
    main()
