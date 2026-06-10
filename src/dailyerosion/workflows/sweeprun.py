"""Elements of SWEPP Runs."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field


class SweepJobResult(BaseModel):
    """Model for result sent back to collection node."""

    field_id: Annotated[int, Field(description="Database Field Identifier")]
    dt: Annotated[date, Field(description="Date of Run")]
    scenario: Annotated[int, Field(description="Scenario ID")]
    erosion: Annotated[float, Field(description="Erosion in kg/m2")]
    max_wmps: Annotated[float, Field(description="Max Wind Speed mps")]
    avg_wmps: Annotated[float, Field(description="Average Wind Speed mps")]
    drct: Annotated[
        float, Field(description="Predominant Wind Direction in degrees")
    ]


class SweepJobPayload(BaseModel):
    """Payload for a SWEPP job."""

    sweepexe: Annotated[str, Field(description="Name of sweepexe to use")]
    huc_12: Annotated[str, Field(description="HUC12 code")]
    scenario: Annotated[int, Field(description="Scenario ID")] = 0
    field_id: Annotated[int, Field(description="Database Field Identifier")]
    fpath: Annotated[int, Field(description="Flowpath identifier in HUC12")]
    ifcfile: Annotated[str, Field(description="Path to the WEPS Soil File.")]
    crop: Annotated[str, Field(description="Crop Code for the year")]
    dt: Annotated[date, Field(description="Date to Run for")]
    lon: Annotated[float, Field(description="Longitude of Point")]
    lat: Annotated[float, Field(description="Latitude of Point")]
