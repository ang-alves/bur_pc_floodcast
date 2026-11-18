
"""Serializable forecast contracts, distinct from model installation records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, field_validator

from .config import ForecastConfig


class DataContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be integer 1")
        return value


class RequestPart(DataContract):
    part_id: str = Field(pattern=r"^part-[0-9]{5}$")
    transport: Literal["open_data", "ecds", "cds"]
    dataset: str | None = None
    role: Literal["control", "perturbed", "ensemble"]
    payload: dict[str, JsonValue]


class AcquisitionPlan(DataContract):
    config: ForecastConfig
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation: str
    parts: tuple[RequestPart, ...]
    warnings: tuple[str, ...]
    provenance: dict[str, JsonValue] = Field(default_factory=dict)


class FileRecord(DataContract):
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: StrictInt = Field(gt=0)


class RawAsset(FileRecord):
    part_id: str
    messages: StrictInt = Field(gt=0)


class AcquisitionManifest(DataContract):
    declared_schema: Literal["ffw.ecmwf-grib/v1"] = "ffw.ecmwf-grib/v1"
    status: Literal["downloaded_not_scientifically_validated"] = (
        "downloaded_not_scientifically_validated"
    )
    plan: AcquisitionPlan
    created_at: datetime
    assets: tuple[RawAsset, ...]


class CanonicalVariable(FileRecord):
    source_field: str
    canonical_name: str
    units: str
    temporal_semantics: str
    members: tuple[int, ...]
    leads_hours: tuple[int, ...]


class CanonicalManifest(DataContract):
    domain_id: str
    declared_schema: Literal["ffw.canonical-forecast/v1"] = "ffw.canonical-forecast/v1"
    request_sha256: str
    implementation: str
    raw_manifest_sha256: str
    product: str
    cycle: datetime
    originating_centre: Literal["ecmwf"] = "ecmwf"
    system: str | None
    selected_members: tuple[int, ...]
    observed_members: tuple[int, ...]
    files: tuple[CanonicalVariable, ...]
    quality: Literal["requested_fields_complete"] = "requested_fields_complete"
    model_ready: Literal[False] = False
    warnings: tuple[str, ...]
    provenance: dict[str, JsonValue] = Field(default_factory=dict)


class DataResult(DataContract):
    manifest_path: Path
    files: tuple[Path, ...]
