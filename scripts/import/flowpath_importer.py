"""Process provided GeoJSON files into the database.

Brian Gelder provides me some archive of processed HUC12s, this archive is
dumped to disk and then glob'd by this script.  It then creates a `myhucs.txt`
file, which provides the downstream scripts the data domain to limit processing
to.
"""

import glob
import json
import logging
import os
import sys
from typing import Optional

import click
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from pyiem.database import get_dbconn
from pyiem.util import logger
from shapely.geometry import LineString
from tqdm import tqdm

from dailyerosion.util import (
    clear_huc12data,
    compute_management_for_groupid,
    get_cli_fname,
    get_kwfact_class,
    get_slope_class,
)

LOG = logger()
print(" * BE CAREFUL!  The GeoJSON files may not be 5070, but 26915")
print(" * VERIFY that the GeoJSON is the 5070 grid value")
print(" * This will generate a `myhucs.txt` file with found HUCs")

# Things we can control via command line
KNOBS = {
    "MAX_POINTS_OFE": 97,
    "CONSTANT_LANDUSE": None,
    "CONSTANT_MANAGEMENT": None,
    "TRUNC_GRIDORDER_AT": 4,
    "CLIMATE_SCENARIO": 0,
}

YEARS = 2026 - 2007 + 1
SOILFY = 2025
ROTATION_FIELD = "CropRotatn_CY_2024"  # Tied to ACPF
SOILCOL = f"SOL_FY_{SOILFY}"
GENLU_CODES = {}
PROCESSING_COUNTS = {
    "flowpaths_found": 0,
    "flowpaths_good": 0,
    "flowpaths_deduped": 0,
    "flowpaths_tooshort": 0,
    "flowpaths_toosteep": 0,
    "flowpaths_toomanydupes": 0,
    "flowpaths_invalidgeom": 0,
    "flowpaths_not_start_len_zero": 0,
    "flowpaths_inconsistent_gridorder": 0,
    "flowpaths_deleted": 0,
    "flowpath_ofes_deleted": 0,
    "fields_deleted": 0,
    "fields_inserted": 0,
    "field_operations_deleted": 0,
}
TRANSFORMER = pyproj.Transformer.from_crs(
    "epsg:5070", "epsg:4326", always_xy=True
)
# First call returns inf for unknown reasons
TRANSFORMER.transform(223279, 2071344)
MAX_SLOPE_RATIO = 0.9


def create_flowpath_id(cursor, scenario, huc12, fpath) -> int:
    """Create a database flowpath identifier

    Args:
      cursor (psycopg.cursor): database cursor
      huc12 (str): HUC12 identifier
      fpath (int): the flowpath id value for this HUC12

    Returns:
      int the value of this huc12 flowpath
    """
    cursor.execute(
        "INSERT into flowpaths(huc_12, fpath, scenario) "
        "values (%s, %s, %s) RETURNING fid",
        (huc12, fpath, scenario),
    )
    return cursor.fetchone()[0]


def fillout_codes(df):
    """ "Get the right full-string codes."""
    if KNOBS["CONSTANT_LANDUSE"] is None:
        s = df[ROTATION_FIELD].str
        df["landuse"] = s[1] + s[0] + s[1] + s[:] + s[-1] + s[-2]
        if df["landuse"].str.len().min() != YEARS:
            raise ValueError(f"landuse is not {YEARS} chars")
    else:
        df["landuse"] = KNOBS["CONSTANT_LANDUSE"] * YEARS
    if KNOBS["CONSTANT_MANAGEMENT"] is None:
        s = df["Management_CY_2024"].str
        df["management"] = s[1] + s[0] + s[1] + s[:] + s[-1] + s[-2]
        if df["management"].str.len().min() != YEARS:
            raise ValueError(f"management is not {YEARS} chars")
    else:
        df["management"] = KNOBS["CONSTANT_MANAGEMENT"] * YEARS

    if "CP_2018" in df.columns:
        df.loc[df["CP_2018"] == "CP-8A", "landuse"] = "8" * YEARS
        df.loc[df["CP_2018"] == "CP-43", "landuse"] = "4" * YEARS


def read_flowpaths(progress: tqdm, filename: str) -> pd.DataFrame | bool:
    """Basics of filepath reading and moidification."""
    df = gpd.read_file(filename, engine="pyogrio")
    if df.empty:
        progress.write(f"WARNING: {filename} had no flowpaths")
        return False
    # smpl3m_mean18040302011002
    huc12 = os.path.basename(filename)[13:25]
    df["huc12"] = huc12
    # Rename columns to make things simplier
    df = df.rename(
        columns={
            f"fpLen{huc12}": "len",
            f"ep3m{huc12}": "elev",
            f"gord_{huc12}": "gorder",
            f"fp{huc12}": "fp",
        },
        errors="raise",
    )
    if "irrigated" not in df.columns:
        progress.write(f"{filename} has no `irrigated` column, setting 0")
        df["irrigated"] = 0
    if ROTATION_FIELD not in df.columns:
        progress.write(
            f"{filename} missing {ROTATION_FIELD} in cols {df.columns}"
        )
        return False

    # Ensure that landuse and management columns are of expected size.
    fillout_codes(df)

    return df


def read_fields(filename: str) -> pd.DataFrame:
    """Basics of field reading and moidification."""
    df = gpd.read_file(filename, engine="pyogrio").drop(
        columns=["OBJECTID"],
    )
    # Forgive the provider
    if "CropRotatn" in df.columns and ROTATION_FIELD not in df.columns:
        df = df.rename(columns={"CropRotatn": ROTATION_FIELD}, errors="raise")
    if ROTATION_FIELD not in df.columns:
        errmsg = f"{filename} missing {ROTATION_FIELD} in cols {df.columns}"
        raise ValueError(errmsg)

    return df


def get_data(progress: tqdm, filename: str):
    """Converts a GeoJSON file into a pandas dataframe

    Args:
      filename (str): The geojson filename to process

    Returns:
      gpd.DataFrame with the geojson data included.
    """
    df = read_flowpaths(progress, filename)
    if df is False:
        LOG.warning("FATAL: %s has no flowpaths, stopping", filename)
        sys.exit(3)
    # Count up unique flowpaths
    PROCESSING_COUNTS["flowpaths_found"] += len(df["fp"].unique())

    # Ensure that len is not an object
    if df["len"].dtype == object:
        df["len"] = pd.to_numeric(df["len"])
    # Can't deal with int32 dtypes
    for col in df.select_dtypes(np.int32).columns:
        df[col] = df[col].astype(int)

    # Any null FBndID (mostly forest?) get set to -1
    df["FBndID"] = (
        df["FBndID"].fillna("FUNUSED_-1").str.split("_").str[1].astype(int)
    )
    fillout_codes(df)
    fld_df = None
    fldfn = filename.replace("smpl3m_mean18", "FB")
    if os.path.isfile(fldfn):
        # Get the field bounds dataframe as well
        fld_df = read_fields(fldfn)
        fld_df.index = fld_df["FBndID"].str.split("_").str[1].astype(int)
        # Placeholder for capturing database insert
        fld_df["field_id"] = -1
        # Check for bad geometries
        if not fld_df["geometry"].is_valid.all():
            LOG.info(
                "Found %s invalid geomtries, calling buffer(0)",
                len(fld_df.index) - fld_df["geometry"].is_valid.sum(),
            )
            fld_df["geometry"] = fld_df["geometry"].buffer(0)
        fillout_codes(fld_df)
    else:
        LOG.warning("Missing %s", fldfn)
    return df, fld_df


def load_genlu_codes(cursor):
    """Populate dict."""
    cursor.execute("SELECT id, label from general_landuse")
    for row in cursor:
        GENLU_CODES[row[1]] = row[0]


def get_genlu_code(cursor, label):
    """Find or create the code for this label."""
    if label not in GENLU_CODES:
        cursor.execute("SELECT max(id) from general_landuse")
        row = cursor.fetchone()
        newval = 0 if row[0] is None else row[0] + 1
        LOG.info("Inserting new general landuse code: %s [%s]", newval, label)
        cursor.execute(
            "INSERT into general_landuse(id, label) values (%s, %s)",
            (newval, label),
        )
        GENLU_CODES[label] = newval
    return GENLU_CODES[label]


def dedupe(df):
    """Deduplicate by removing duplicated points."""
    dups = df["len"].duplicated(keep=False)
    if dups.sum() > 7:
        PROCESSING_COUNTS["flowpaths_toomanydupes"] += 1
        return None
    PROCESSING_COUNTS["flowpaths_deduped"] += 1
    df = df[~dups].copy()
    # Ensure we are zero based.
    if df["len"].min() > 0:
        df["len"] = df["len"] - df["len"].min()
    return df


def compute_ofe(df):
    """Figure out what the OFE should be after prj2wepp does magic."""
    # Default
    df["ofe"] = 1
    # OFEs are breaks in management, landuse and or soils
    cols = ["FBndID", SOILCOL, "management", "landuse"]
    locs = df[cols].ne(df[cols].shift()).apply(lambda x: x.index[x].tolist())
    indices = locs.apply(pd.Series).stack().unique()
    ofeid = 0
    values = df.index.to_list()
    for idx in values:
        # Last index should not bump OFE, it is quasi ignored
        if idx in indices and idx != values[-1]:
            ofeid += 1
        df.at[idx, "ofe"] = ofeid
    return df


def simplify(df):
    """WEPP can only handle 100 slope points per OFE."""
    df["useme"] = False
    for _ofe, gdf in df.groupby("ofe"):
        if len(gdf.index) < KNOBS["MAX_POINTS_OFE"]:
            df.loc[gdf.index, "useme"] = True
            continue
        # Any hack is a good hack here, take the first and last point
        df.at[gdf.index[0], "useme"] = True
        df.at[gdf.index[-1], "useme"] = True
        # Take the top 16 values by slope
        df.loc[
            gdf.sort_values("slope", ascending=False).index[
                : KNOBS["MAX_POINTS_OFE"]
            ],
            "useme",
        ] = True

    return df[df["useme"]].copy()


def compute_slope(df):
    """Figure out the slope values."""
    # Compute slope
    df["slope"] = (df["elev"] - df["elev"].shift()) / (
        df["len"].shift() - df["len"]
    )
    # Duplicate the first value, for now?
    df.iat[0, df.columns.get_loc("slope")] = df["slope"].values[1]
    return df


def insert_ofe(cursor, gdf, db_fid, ofe, ofe_starts):
    """Add database entry."""
    pts = list(
        zip(
            gdf.geometry.x,
            gdf.geometry.y,
            gdf.elev.values / 100.0,
            strict=False,
        )
    )
    next_ofe = ofe + 1
    firstpt = gdf.iloc[0]
    lastpt = gdf.iloc[-1]
    if next_ofe in ofe_starts.index:
        lastpt = ofe_starts.loc[next_ofe]
        # append on next
        pts.extend(
            [(lastpt.geometry.x, lastpt.geometry.y, lastpt.elev / 100.0)]
        )
    line = LineString(pts)

    bulk_slope = (firstpt["elev"] - lastpt["elev"]) / (
        lastpt["len"] - firstpt["len"]
    )
    res = cursor.execute(
        "select id, kwfact from gssurgo where fiscal_year = %s and mukey = %s",
        (SOILFY, int(firstpt[SOILCOL])),
    )
    gssurgo_id, kwfact = res.fetchone()
    # dailyerosion/dep/issues/298
    groupid = "_".join(
        [
            str(get_slope_class(bulk_slope * 100.0)),
            "N" if kwfact is None else str(get_kwfact_class(kwfact)),
            # Need to apply some logic to deal with mixed mans with 0s
            compute_management_for_groupid(firstpt["management"][0]),
            firstpt["GenLU"],
        ]
    )
    cursor.execute(
        """
    INSERT into flowpath_ofes (flowpath, ofe, geom, bulk_slope, max_slope,
    gssurgo_id, management, landuse, real_length, field_id, groupid)
    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            db_fid,
            ofe,
            f"SRID=5070;{line.wkt}",
            bulk_slope,
            gdf["slope"].max(),
            gssurgo_id,
            firstpt["management"],
            firstpt["landuse"],
            (lastpt["len"] - firstpt["len"]) / 100.0,
            firstpt["field_id"],
            groupid,
        ),
    )


def get_cli_fname_and_id(cursor, lon, lat) -> tuple[str, int]:
    """Get database entry or add one."""
    clifn = get_cli_fname(lon, lat, KNOBS["CLIMATE_SCENARIO"])
    cursor.execute(
        "select id from climate_files where scenario = %s and filepath = %s",
        (KNOBS["CLIMATE_SCENARIO"], clifn),
    )
    if cursor.rowcount == 0:
        # Danger, we are doing lame things from the database on my laptop to
        # how it syncs to the server, so we need to manually track the next
        # sequence value
        cursor.execute("select max(id) + 1 from climate_files")
        cli_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT into climate_files(id, scenario, filepath, geom) "
            "values (%s, %s, %s, ST_Point(%s, %s, 4326))",
            (cli_id, KNOBS["CLIMATE_SCENARIO"], clifn, lon, lat),
        )
    else:
        cli_id = cursor.fetchone()[0]
    return clifn, cli_id


def process_flowpath(
    cursor, scenario, db_fid, df: pd.DataFrame
) -> pd.DataFrame:
    """Do one flowpath please."""
    # Sort along the length column, which orders the points from top
    # to bottom, rename columns to simplify further code.
    df = df.sort_values("len", ascending=True)
    if df.iloc[0]["len"] > 0:
        PROCESSING_COUNTS["flowpaths_not_start_len_zero"] += 1
        df["len"] = df["len"] - df.iloc[0]["len"]
    # remove duplicate points due to a bkgelder sampling issue whereby some
    # points exist in two fields
    if df["len"].duplicated().any():
        df = dedupe(df)
        if df is None:
            return None

    # Ensure that the gorder field is monotonic
    if not df["gorder"].is_monotonic_increasing:
        PROCESSING_COUNTS["flowpaths_inconsistent_gridorder"] += 1
        return None

    # Truncate at grid order
    df = df[df["gorder"] <= KNOBS["TRUNC_GRIDORDER_AT"]]

    if len(df.index) < 3:
        PROCESSING_COUNTS["flowpaths_tooshort"] += 1
        return None

    compute_slope(df)

    # Compute the OFE value
    compute_ofe(df)

    # WEPP has a 100 point per OFE limit, so if we detect this, simplification
    # is necessary, we are cautious to be well below 100
    if (
        df[["ofe", "landuse"]].groupby("ofe").count().max()["landuse"]
        > KNOBS["MAX_POINTS_OFE"]
    ):
        df = simplify(df)
        # Need to recompute slopes
        compute_slope(df)

    if df["slope"].max() > MAX_SLOPE_RATIO:
        PROCESSING_COUNTS["flowpaths_toosteep"] += 1
        return None

    if len(df.index) < 3:
        PROCESSING_COUNTS["flowpaths_tooshort"] += 1
        return None

    # Need OFE start points in order to create the end point for the previous
    # OFE
    ofe_starts = df.groupby("ofe").first()

    # reset_index to get a sequential id
    for ofe, gdf in df.reset_index().groupby("ofe"):
        # Insert OFE information
        insert_ofe(cursor, gdf, db_fid, ofe, ofe_starts)

    # Update flowpath info
    ls = LineString(zip(df.geometry.x, df.geometry.y, strict=False))
    if not ls.is_valid:
        PROCESSING_COUNTS["flowpaths_invalidgeom"] += 1
        return None
    # pylint: disable=not-an-iterable
    lon, lat = TRANSFORMER.transform(
        df.iloc[0].geometry.x,
        df.iloc[0].geometry.y,
    )
    clifn, clifn_id = get_cli_fname_and_id(cursor, lon, lat)
    cursor.execute(
        """
        UPDATE flowpaths SET geom = %s, irrigated = %s,
        max_slope = %s, bulk_slope = %s, ofe_count = %s, climate_file_id = %s,
        real_length = %s
        WHERE fid = %s returning huc_12, fpath
        """,
        (
            f"SRID=5070;{ls.wkt}",
            bool(df["irrigated"].sum() > 0),
            df["slope"].max(),
            (df["elev"].max() - df["elev"].min())
            / (df["len"].max() - df["len"].min()),
            df["ofe"].max(),
            clifn_id,
            df["len"].max() / 100.0,
            db_fid,
        ),
    )
    huc12, fpath = cursor.fetchone()
    # Write metadata file
    # grab first row to get some OFE metadata for bundling
    ofemeta = (
        df[["ofe", "landuse", "management", "FBndID"]]
        .groupby("ofe")
        .first()
        .reset_index()
        .to_dict(orient="records")
    )
    # A bit of chicken/egg here as this scripts initializes a list of HUC12s
    # which may not be setup within the /i/ filesystem yet
    metadir = f"/i/{scenario}/meta/{huc12[:8]}/{huc12[8:]}"
    if not os.path.isdir(metadir):
        os.makedirs(metadir, exist_ok=True)
    with open(f"/{metadir}/{huc12}_{fpath}.json", "w", encoding="ascii") as fh:
        meta = {
            "lon": round(lon, 2),
            "lat": round(lat, 2),
            "climate_file": clifn,
            "ofes": ofemeta,
        }
        json.dump(meta, fh)
    PROCESSING_COUNTS["flowpaths_good"] += 1
    return df


def delete_flowpath(cursor, fid):
    """Delete the flowpath."""
    cursor.execute("DELETE from flowpath_ofes where flowpath = %s", (fid,))
    cursor.execute("DELETE from flowpaths where fid = %s", (fid,))


def process_fields(cursor, scenario, huc12, fld_df):
    """Database update this information."""
    for fbndid, row in fld_df.iterrows():
        if row["geometry"] is None:
            print("null geom", row)
            continue
        cursor.execute(
            """
            INSERT into fields (scenario, huc12, fbndid, acres, isag, geom,
            management, landuse, genlu)
            VALUES (%s, %s, %s, %s, %s, st_multi(%s), %s, %s, %s)
            RETURNING field_id
            """,
            (
                scenario,
                huc12,
                fbndid,
                row["Acres"],
                row["isAG"],
                row["geometry"].wkt,
                row["management"],
                row["landuse"],
                get_genlu_code(cursor, row["GenLU"]),
            ),
        )
        fld_df.at[fbndid, "field_id"] = cursor.fetchone()[0]
    PROCESSING_COUNTS["fields_inserted"] += len(fld_df.index)


def process(cursor, scenario, huc12df, fld_df):
    """Processing of a HUC12's data into the database

    Args:
      cursor (psycopg.cursor): database cursor
        scenario (int): the scenario to process
      huc12df (pd.DataFrame): the dataframe containing the data
      fld_df (gpd.GeoDataFrame): The associated fields.

    Returns:
      None
    """
    # Hack compute the huc12 by finding the fp field name
    huc12 = huc12df.iloc[0]["huc12"]
    fod, fpd, fopd, fldd = clear_huc12data(cursor, huc12, scenario)
    PROCESSING_COUNTS["flowpath_ofes_deleted"] += fod
    PROCESSING_COUNTS["flowpaths_deleted"] += fpd
    PROCESSING_COUNTS["field_operations_deleted"] += fopd
    PROCESSING_COUNTS["fields_deleted"] += fldd
    if fld_df is not None:
        process_fields(cursor, scenario, huc12, fld_df)
    # With fields processed, we can join the field_id to the flowpath points
    huc12df["field_id"] = huc12df["FBndID"].map(fld_df["field_id"])

    for flowpath_num, df in huc12df.groupby("fp"):
        # These are upstream errors I should ignore
        if flowpath_num == 0 or len(df.index) < 3:
            continue
        # Create the flowpathid in the database
        db_fid = create_flowpath_id(cursor, scenario, huc12, flowpath_num)
        try:
            if process_flowpath(cursor, scenario, db_fid, df) is None:
                delete_flowpath(cursor, db_fid)
        except Exception as exp:
            LOG.info("flowpath_num: %s hit exception", flowpath_num)
            logging.error(exp, exc_info=True)
            delete_flowpath(cursor, db_fid)
    return huc12


def scan_file_attributes(fns: list):
    """A first pass checking if the files have the expected attributes."""
    LOG.info("Scanning file attributes")
    progress = tqdm(fns)
    errors = False
    for fn in progress:
        progress.set_description(os.path.basename(fn))
        try:
            read_flowpaths(progress, fn)
            read_fields(fn.replace("smpl3m_mean18", "FB"))
        except Exception as exp:
            logging.error(exp, exc_info=True)
            errors = True
    if errors:
        raise ValueError("Found errors in file processing, aborting")


@click.command()
@click.option("--scenario", "-s", type=int, required=True)
@click.option("--datadir", "-d", type=str, required=True)
@click.option("--max-points-ofe", "mpe", type=int, default=97)
@click.option("--constant-landuse", "cl", type=str, default=None)
@click.option("--constant-management", "cm", type=str, default=None)
@click.option("--skipscan", is_flag=True)
@click.option("--gorder", type=int, default=4, help="Truncate at grid order")
def main(
    scenario,
    datadir,
    mpe: int,
    cl: Optional[str],
    cm: Optional[str],
    skipscan: bool,
    gorder: int,
):
    """Our main function, the starting point for code execution"""
    KNOBS["MAX_POINTS_OFE"] = mpe
    KNOBS["CONSTANT_LANDUSE"] = cl
    KNOBS["CONSTANT_MANAGEMENT"] = cm
    KNOBS["TRUNC_GRIDORDER_AT"] = gorder
    pgconn = get_dbconn("idep")
    cursor = pgconn.cursor()
    load_genlu_codes(cursor)
    datadir = os.path.join("..", "..", "data", datadir)
    # collect up the GeoJSONs in that directory
    fns = glob.glob(f"{datadir}/smpl3m_*.json")
    fns.sort()
    if not skipscan:
        scan_file_attributes(fns)
    i = 0
    # Allow for processing to restart
    done = []
    if os.path.isfile("myhucs.txt-done"):
        with open("myhucs.txt-done", encoding="utf8") as fh:
            done = [x.strip() for x in fh]

    progress = tqdm(fns)
    # track our work
    with open("myhucs.txt", "w", encoding="utf8") as fh:
        for fn in progress:
            progress.set_description(os.path.basename(fn))
            huc12 = fn[-17:-5]
            if huc12 in done:
                continue
            # Save our work every 100 HUC12s,
            # so to keep the database transaction
            # at a reasonable size
            if i > 0 and i % 100 == 0:
                pgconn.commit()
                cursor = pgconn.cursor()
            try:
                fp_df, fld_df = get_data(progress, fn)
            except Exception as exp:
                logging.error(exp, exc_info=True)
                continue
            # Sometimes we get no flowpaths, so skip writing those
            huc12 = process(cursor, scenario, fp_df, fld_df)
            if not fp_df.empty:
                fh.write(f"{huc12}\n")
            i += 1

    # Commit the database changes
    cursor.close()
    pgconn.commit()

    print("Processing accounting:")
    for key, val in PROCESSING_COUNTS.items():
        print(f"    {key}: {val}")


if __name__ == "__main__":
    main()
