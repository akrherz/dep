"""Test dailyerosion.workflows.sweeprun module."""

from datetime import date

from dailyerosion.workflows.sweeprun import SweepJobPayload


def test_sweepjobpayload_valid():
    """Test SweepJobPayload with valid data."""
    payload = SweepJobPayload(
        sweepexe="sweep20240930",
        huc_12="123456789012",
        clifile="/dev/null",
        ifcfile="/dev/null",
        scenario=0,
        field_id=1,
        fpath=1,
        dt=date(2026, 5, 27),
        lon=0.0,
        lat=0.0,
        crop="C",
    )
    assert payload.sweepexe == "sweep20240930"
