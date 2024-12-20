"""Test things related to R-factor calculations."""

import os

from pydep.rfactor import compute_rfactor_from_cli


def get_path(name):
    """helper"""
    basedir = os.path.dirname(__file__)
    return os.path.join(basedir, "data", name)


def test_rfactor():
    """Walk before we run."""
    resultdf = compute_rfactor_from_cli(get_path("cli.txt"))
    # There is no right answer, but we can check for changes
    assert abs(resultdf.at[2007, "rfactor"] - 1252.09) < 0.1
    assert resultdf.at[2007, "storm_count"] == 76
