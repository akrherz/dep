"""Stuff suppoting workflows."""

from enum import StrEnum


class QUEUES(StrEnum):
    """RabbitMQ queue names used with versioning to support payload updates."""

    WEPP = "wepp_v1"
    WEPS = "weps_v3"
    SWEEP = "sweep_v2"
