"""Stuff suppoting workflows."""

from enum import StrEnum

# This defines which crop codes we know about, a constant shared within
# the workflows
LANDUSE_DB_RE = "[^CBPWEMGOIV]"


class QUEUES(StrEnum):
    """RabbitMQ queue names used with versioning to support payload updates."""

    WEPP = "wepp_v1"
    WEPS = "weps_v4"
    SWEEP = "sweep_v3"
    SWEEP_RESULTS = "sweep_results_v1"
