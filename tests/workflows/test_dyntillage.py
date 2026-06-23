"""Exercise our dynamic tillage mess."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from pyiem.database import get_sqlalchemy_conn, sql_helper

from dailyerosion.workflows.dyntillage import do_huc12, do_planting, do_tillage


@pytest.fixture
def fields() -> pd.DataFrame:
    """Return our test dataframe."""
    return pd.DataFrame(
        {
            "acres": np.ones(10) * 100,
            "crop": ["C"] * 5 + ["B"] * 5,
            "plant_needed": [True] * 10,
            "till_needed": [True] * 10,
            "till1": pd.to_datetime([date(2000, 7, 1)] * 10),  # Future
            "till2": pd.to_datetime([date(2000, 7, 1)] * 10),
            "till3": pd.to_datetime([date(2000, 7, 1)] * 10),
            "plant": pd.to_datetime([date(2000, 7, 1)] * 10),
            "operation_done": [False] * 10,
        },
    )


def reset_field_operations(conn):
    """Set things back to normal."""
    conn.execute(
        sql_helper("""
    update field_operations SET
    till1 = case when till1 is not null then '2025-06-10'::date else null end,
    till2 = case when till2 is not null then '2025-06-11'::date else null end,
    till3 = case when till3 is not null then '2025-06-12'::date else null end,
    plant = case when plant is not null then '2025-06-13'::date else null end
    where year = 2025
    """)
    )


def test_do_huc12_alldone():
    """Test what happens when all the work is done!"""
    with get_sqlalchemy_conn("dep") as conn:
        reset_field_operations(conn)
        for dy in range(1, 30):
            dt = date(2025, 5, dy)
            df, acres_planted, acres_tilled = do_huc12(
                conn, -1, dt, "070801050902"
            )
            if dy == 29:
                assert not df.empty
                assert not df["plant_needed"].any()
                assert acres_planted == 0
                assert acres_tilled == 0


def test_do_huc12_nodata():
    """Test something that yields no data."""
    with get_sqlalchemy_conn("dep") as conn:
        df, _, _ = do_huc12(conn, -1, date(2000, 1, 1), "AAAA")
    assert df.empty


def test_do_huc12_season():
    """Run for many days."""
    with get_sqlalchemy_conn("dep") as conn:
        reset_field_operations(conn)
        dates = [date(2025, 4, 14), date(2025, 4, 15), date(2025, 4, 16)]
        for dt in dates:
            df, _acres_planted, acres_tilled = do_huc12(
                conn, -1, dt, "070801050902"
            )
            total_acres = df["acres"].sum()
            assert acres_tilled >= (total_acres * 0.1)


def test_do_huc12():
    """Can we do_huc12 ?"""
    with get_sqlalchemy_conn("dep") as conn:
        reset_field_operations(conn)
        df, acres_planted, _acres_tilled = do_huc12(
            conn, -1, date(2025, 6, 13), "070801050902"
        )
    total_acres = df["acres"].sum()
    assert len(df.index) == 306
    assert acres_planted >= (total_acres * 0.1)


def test_soybeans_early_too_aggressive(fields):
    """Test that we are not too aggressive early in season with soybeans."""
    # Scenario is 9 fields of soybeans and one of corn
    fields["crop"] = ["B"] * 9 + ["C"]
    # Goose acres to get a three pass result
    fields["acres"] = [1, 1, 1, 1, 1, 1, 1, 1, 100, 1]
    # Clear out tillage
    fields["till_needed"] = False
    # We are early in the season, so the ratio is small for soybeans
    dt = date(2000, 4, 30)
    acres_planted = do_planting(fields, dt, False, 0)
    # Only the first soybean field should have been planted
    assert (
        len(fields[(fields["crop"] == "B") & fields["operation_done"]].index)
        == 1
    )
    assert acres_planted == 2


def test_mud_it_in(fields):
    """Test scenario with all fields that should get planted."""
    # No tillage needed
    fields["till_needed"] = False
    dt = date(2000, 6, 11)
    acres_planted = do_planting(fields, dt, True, 0)
    assert acres_planted == 1000.0


def test_mud_it_in_no_planting(fields):
    """Test scenario with all fields getting tilled, none should be planted."""
    dt = date(2000, 6, 11)
    acres_tilled = do_tillage(fields, dt, True, 0)
    assert acres_tilled == 1000.0
    acres_planted = do_planting(fields, dt, True, 0)
    assert acres_planted == 0.0


def test_no_soybeans_planted_before_season_starts(fields):
    """Test scenario with no soybeans planted, hopefully."""
    # Set everything to soybeans, ready to plant
    fields["crop"] = "B"
    fields["till_needed"] = False
    dt = date(2000, 4, 4)
    acres_planted = do_planting(fields, dt, False, 0)
    assert acres_planted == 0


def test_no_soybeans_planted_preferred_corn_fields(fields):
    """Test scenario with no soybeans planted, hopefully."""
    # No tillage needed
    fields["till_needed"] = False
    dt = date(2000, 4, 16)
    acres_planted = do_planting(fields, dt, False, 0)
    assert acres_planted == 100.0
    assert fields[fields["operation_done"]].iloc[0]["crop"] == "C"


def test_one_field_tilled(fields):
    """Should have one field tilled, nothing planted."""
    dt = pd.Timestamp(date(2000, 5, 1))
    acres_tilled = do_tillage(fields, dt, False, 0)
    assert acres_tilled == 100.0
    assert fields[fields["operation_done"]].iloc[0]["till1"] == dt
