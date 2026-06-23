"""dailyerosion helper util methods."""

import json
import logging
import math
import sys
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import pika
from pika.credentials import PlainCredentials
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.iemre import get_domain
from pyiem.util import CustomFormatter
from tqdm import tqdm

from dailyerosion.reference import KWFACT_CLASSES, SLOPE_CLASSES


class TqdmLoggingHandler(logging.Handler):  # skipcq
    """Custom logging handler that uses tqdm.write() for output."""

    def emit(self, record):
        """Emit a log record."""
        tqdm.write(self.format(record))


def _logger(ch: logging.Handler) -> logging.Logger:
    """Helper to get the logger."""
    ch.setFormatter(CustomFormatter())
    # We lamely get both dailyerosion and pyiem loggers here
    log = logging.getLogger("pyiem")
    log.setLevel(logging.INFO if sys.stdout.isatty() else logging.WARNING)
    log.addHandler(ch)
    log = logging.getLogger("dailyerosion")
    log.setLevel(logging.INFO if sys.stdout.isatty() else logging.WARNING)
    log.addHandler(ch)
    return log


def tqdm_logger() -> logging.Logger:
    """Return a logger that writes to tqdm."""
    ch = TqdmLoggingHandler()
    return _logger(ch)


def logger() -> logging.Logger:
    """Return the root logger."""
    ch = logging.StreamHandler()
    return _logger(ch)


def compute_management_for_groupid(text: str) -> str:
    """Compute the management portion of the groupid."""
    if text[0] != "0":
        return text[0]
    # Find the first non-0 character in the text string
    for char in text:
        if char != "0":
            return char
    return "0"


def get_kwfact_class(kwfact: float) -> int:
    """Get kwfact class for the given kwfact."""
    return np.digitize(kwfact, KWFACT_CLASSES, right=True)


def get_slope_class(slope: float) -> int:
    """Get slope class for the given slope."""
    return np.digitize(slope, SLOPE_CLASSES, right=True)


def clear_huc12data(cursor, huc12, scenario) -> Tuple[int, int, int, int]:
    """Clear out database storage for the typical import case.

    Returns:
        deleted_ofes (int): Number of OFES rows deleted
        deleted_flowpaths (int): Number of flowpaths deleted
        deleted_field_operations (int): Number of field operations deleted
        deleted_fields (int): Number of fields deleted
    """
    cursor.execute(
        """
    delete from flowpath_ofe o using flowpath f where
    o.flowpath_id = f.flowpath_id and f.huc12_id = get_huc12_id(%s, %s)
    and f.scenario_id = %s
        """,
        (huc12, scenario, scenario),
    )
    deleted_ofes = cursor.rowcount
    cursor.execute(
        """
        DELETE from flowpath WHERE scenario_id = %s and
        huc12_id = get_huc12_id(%s, %s)
        """,
        (scenario, huc12, scenario),
    )
    deleted_flowpaths = cursor.rowcount
    cursor.execute(
        """
    delete from field_operations o using field f where
    o.field_id = f.field_id and f.huc12_id = get_huc12_id(%s, %s)
    and f.scenario_id = %s
    """,
        (huc12, scenario, scenario),
    )
    deleted_field_operations = cursor.rowcount
    cursor.execute(
        """
    DELETE from field WHERE scenario_id = %s and
    huc12_id = get_huc12_id(%s, %s)""",
        (scenario, huc12, scenario),
    )
    deleted_fields = cursor.rowcount
    return (
        deleted_ofes,
        deleted_flowpaths,
        deleted_field_operations,
        deleted_fields,
    )


def load_scenarios():
    """Build a dataframe of DEP scenarios."""
    with get_sqlalchemy_conn("dep") as conn:
        return pd.read_sql(
            sql_helper("SELECT * from scenario ORDER by scenario_id ASC"),
            conn,
            index_col="scenario_id",
        )


def get_cli_fname(lon: float, lat: float, scenario: int = 0):
    """Get the climate file name for the given lon, lat, and scenario"""
    # The trouble here is relying on rounding is problematic, so we just
    # truncate
    lat = round(lat, 2)
    lon = round(lon, 2)
    domain = get_domain(lon, lat)
    if domain is None:
        raise ValueError(f"lon: {lon} lat: {lat} outside any IEMRE domain")
    if domain in ["", "conus"]:
        # Legacy nomenclature
        return (
            f"/i/{scenario}/cli/{math.floor(abs(lon)):03.0f}x"
            f"{math.floor(lat):03.0f}/{(0 - lon):06.2f}x{lat:06.2f}.cli"
        )
    # Lots of pain to keep dashes out of the path
    return (
        f"/mnt/dep/{domain}/2/0/cli/"
        f"{'W' if lon < 0 else 'E'}{math.floor(abs(lon)):03.0f}x"
        f"{'S' if lat < 0 else 'N'}{math.floor(abs(lat)):02.0f}/"
        f"{'W' if lon < 0 else 'E'}{abs(lon):06.2f}x"
        f"{'S' if lat < 0 else 'N'}{abs(lat):05.2f}.cli"
    )


def get_rabbitmqconn(
    settings_file: str | Path = "rabbitmq.json",
) -> tuple[pika.BlockingConnection, dict[str, str]]:
    """Load the configuration."""
    # load rabbitmq.json in the cwd
    with open(settings_file, "r", encoding="utf-8") as fh:
        config = json.load(fh)
    return (
        pika.BlockingConnection(
            pika.ConnectionParameters(
                host=config["host"],
                port=config["port"],
                virtual_host=config["vhost"],
                credentials=PlainCredentials(
                    config["user"], config["password"]
                ),
            )
        ),
        config,
    )
