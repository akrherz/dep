"""Elements of WEPS Run."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field


class WEPSJobPayload(BaseModel):
    """Payload for a WEPS job."""

    wepsexe: Annotated[str, Field(description="Name of wepsexe to use")]
    for_sweep: Annotated[
        bool,
        Field(
            description=(
                "Flag indicating if this job is being for the purposes of "
                "bootstraping a SWEEP run.  If True, this implies the usage "
                "of a faked wind file."
            )
        ),
    ]
    windfile: Annotated[
        str,
        Field(
            description=(
                "Find name to use for hourly wind info. This is ignored if "
                "for_sweep is True"
            )
        ),
    ]
    manfile: Annotated[
        str, Field(description="WEPS formatted management file.")
    ]
    huc_12: Annotated[str, Field(description="HUC12 code")]
    clifile: Annotated[str, Field(description="DEP breakpoint CLI file")]
    scenario: Annotated[int, Field(description="Scenario ID")] = 0
    field_id: Annotated[int, Field(description="Database Field Identifier")]
    fpath: Annotated[int, Field(description="Flowpath identifier in HUC12")]
    dt: Annotated[
        date | None,
        Field(description="Date to Run for, unused for not for_sweep"),
    ] = None
    lon: Annotated[float, Field(description="Longitude of Point")]
    lat: Annotated[float, Field(description="Latitude of Point")]
