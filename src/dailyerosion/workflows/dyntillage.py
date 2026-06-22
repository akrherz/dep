"""Dynamic Tillage Stuff."""

from datetime import date

import numpy as np
import pandas as pd
from pyiem.database import sql_helper
from sqlalchemy.engine import Connection


def get_soybeans_planting_fraction() -> np.ndarray:
    """Returns the ratio of acres planted to soybeans for a given doy."""
    res = np.zeros(366)
    # ~ Apr 22
    res[112:129] = np.linspace(0, 0.25, 17)
    # ~ May 8
    res[129:146] = np.linspace(0.25, 0.5, 17)
    # ~ May 25
    res[146:] = 0.5
    return res


def get_planting_fraction() -> np.ndarray:
    """Returns what our hard coded thresholds are for planting rate limit."""
    res = np.zeros(366)
    config = [
        (date(2000, 4, 11), 0.02),
        (date(2000, 4, 24), 0.04),
        (date(2000, 5, 1), 0.07),
        (date(2000, 5, 8), 0.1),
    ]
    for dt, val in config:
        doy = dt.timetuple().tm_yday
        res[doy - 1 :] = val
    return res


def do_tillage(
    fields: pd.DataFrame,
    dt: date,
    mud_it_in: bool,
    acres_already_tilled: float,
) -> float:
    """Handle tillage operations."""
    dt = pd.Timestamp(dt)
    total_acres = fields["acres"].sum()
    # NB: Crude assessment of NASS peak daily planting rate, was 10%
    limit = (total_acres * 0.1) if not mud_it_in else total_acres

    acres_tilled = acres_already_tilled

    if acres_tilled < limit:
        # Work on tillage first, so to avoid planting on tilled fields
        for fbndid, row in fields[fields["till_needed"]].iterrows():
            acres_tilled += row["acres"]
            fields.at[fbndid, "operation_done"] = True
            for i in [1, 2, 3]:
                if row[f"till{i}"] >= dt:
                    fields.at[fbndid, f"till{i}"] = dt
                    break
            if acres_tilled >= limit:
                break

    return acres_tilled


def do_planting(
    fields: pd.DataFrame,
    dt: date,
    mud_it_in: bool,
    acres_already_planted: float,
) -> float:
    """Handle planting operations."""
    dt = pd.Timestamp(dt)
    total_acres = fields["acres"].sum()
    doy = dt.timetuple().tm_yday - 1
    # What ratio of available planting acres should attempt soybeans?
    soybeans_fract = get_soybeans_planting_fraction()[doy]
    # What is our hard limit on planting rate?
    planting_acres_fract = get_planting_fraction()[doy]

    planting_acres_limit = total_acres * planting_acres_fract
    soybean_acres_limit = planting_acres_limit * soybeans_fract
    # Tricky, the soybeans limit is first tested and then corn is free to fill
    # up until the full limit is it.
    corn_acres_limit = planting_acres_limit
    if mud_it_in:
        planting_acres_limit = 1e9
        soybean_acres_limit = 1e9
        corn_acres_limit = 1e9

    acres_planted = acres_already_planted
    # Nothing to do.
    if acres_planted >= planting_acres_limit:
        return acres_planted

    # Tricky, we need to iterate 3 times
    # 1. Plant soybeans up to soybean_acres_limit
    # 2. Plant corn up to corn_acres_limit
    # 3. Try again with soybeans up to planting_acres_limit, but only early
    #    in the season, otherwise we don't maintain the ratios
    second_pass_limit = planting_acres_limit if soybeans_fract >= 0.5 else 0
    for crop, limit in zip(
        ["B", "C", "B"],
        [soybean_acres_limit, corn_acres_limit, second_pass_limit],
        strict=True,
    ):
        if acres_planted >= planting_acres_limit:
            break
        iter_planted = 0
        # Can only consider fields of this crop type, that need planted
        # and have not yet been planted or tilled or need tillage GH251
        cropfields = fields[
            (fields["crop"] == crop)
            & (fields["plant_needed"])
            & (~fields["operation_done"])
            & (~fields["till_needed"])
        ]
        for fbndid, row in cropfields.iterrows():
            if iter_planted >= limit or acres_planted >= planting_acres_limit:
                break
            # Track what has been done over this iteration
            iter_planted += row["acres"]
            # Keep track of overall progress
            acres_planted += row["acres"]
            fields.at[fbndid, "plant"] = dt
            fields.at[fbndid, "operation_done"] = True

    return acres_planted


def do_huc12(
    conn: Connection, scenario: int, dt: date, huc12: str
) -> list[pd.DataFrame, int, int]:
    """Process a HUC12.

    Returns the number of acres planted and tilled.  A negative value is a
    sentinel that the HUC12 failed due to soil moisture constraint.
    """
    dt = pd.Timestamp(dt)
    dbcolidx = dt.year - 2007 + 1
    # Only concerned about soybeans/corn for now
    crops = ["B", "C"]
    # No limits, other than 1 operation per field per day
    mud_it_in = f"{dt:%m%d}" >= "0610"
    # build up the cross reference of everyhing we need to know
    df = pd.read_sql(
        sql_helper(
            """
        with myofes as (
            select o.ofe, p.fpath, o.field_id
            from flowpaths p, flowpath_ofes o, gssurgo g
            WHERE o.flowpath = p.fid and p.huc_12 = :huc12
            and p.scenario = :scenario and o.gssurgo_id = g.id),
        agg as (
            SELECT ofe, fpath, f.fbndid, f.landuse,
            f.management, f.acres, f.field_id
            from fields f LEFT JOIN myofes m on (f.field_id = m.field_id)
            WHERE f.huc12 = :huc12 and
            substr(landuse, :dbcolidx, 1) = ANY(:crops)
            ORDER by fpath, ofe)
        select a.*, o.till1, o.till2, o.till3, o.plant, o.year,
        plant >= :dt as plant_needed,
        coalesce(
            greatest(till1, till2, till3) >= :dt, false) as till_needed,
        false as operation_done, 0 as sw1,
        substr(landuse, :dbcolidx, 1) as crop,
        substr(management, :dbcolidx, 1) as tillage
        from agg a, field_operations o
        where a.field_id = o.field_id and o.year = :year
        and o.plant is not null
        """
        ),
        conn,
        params={
            "huc12": huc12,
            "year": dt.year,
            "dt": dt.date(),
            "crops": crops,
            "dbcolidx": dbcolidx,
            "scenario": scenario,
        },
        index_col=None,
        parse_dates=["till1", "till2", "till3", "plant"],
    )
    if df.empty:
        return df, 0, 0

    # Screen out when there are no fields that need planting or tilling
    if (
        not df["plant_needed"].any()
        and not df["till_needed"].any()
        and f"{dt:%m%d}" < "0614"
    ):
        return df, 0, 0

    # There is an entry per OFE + field combination, but we only want 1
    fields = df.groupby("fbndid").first().copy()

    # We could be re-running for a given date, so we first total up the acres
    acres_planted = fields[fields["plant"] == dt]["acres"].sum()
    acres_tilled = (
        fields[fields["till1"] == dt]["acres"].sum()
        + fields[fields["till2"] == dt]["acres"].sum()
        + fields[fields["till3"] == dt]["acres"].sum()
    )
    # Note, a check for NaN/None acres was removed as unreachable, hopefully

    acres_tilled = do_tillage(fields, dt, mud_it_in, acres_tilled)
    acres_planted = do_planting(fields, dt, mud_it_in, acres_planted)

    # Update the database
    df2 = fields[fields["operation_done"]].reset_index()
    for _, row in df2.iterrows():
        conn.execute(
            sql_helper(
                "update field_operations set plant = :plant, till1 = :till1, "
                "till2 = :till2, till3 = :till3 where field_id = :field_id "
                "and year = :year"
            ),
            {
                "plant": row["plant"].date()
                if not pd.isnull(row["plant"])
                else None,
                "till1": row["till1"].date()
                if not pd.isnull(row["till1"])
                else None,
                "till2": row["till2"].date()
                if not pd.isnull(row["till2"])
                else None,
                "till3": row["till3"].date()
                if not pd.isnull(row["till3"])
                else None,
                "field_id": row["field_id"],
                "year": dt.year,
            },
        )
        conn.commit()
    return fields, float(acres_planted), float(acres_tilled)
