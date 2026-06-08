"""Test dailyerosion.workflows.wepsrun module."""

from dailyerosion.workflows.wepsrun import WEPSJobPayload


def test_wepsjobpayload_valid():
    """Test WEPSJobPayload with valid data."""
    payload = WEPSJobPayload(
        wepsexe="wepp20240930",
        for_sweep=False,
        windfile="/dev/null",
        manfile="",
        huc_12="123456789012",
        clifile="/dev/null",
        scenario=0,
        field_id=1,
        fpath=1,
        dt=None,
        lon=0.0,
        lat=0.0,
    )
    assert payload.wepsexe == "wepp20240930"
    assert payload.for_sweep is False
