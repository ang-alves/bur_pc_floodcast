
"""Strict forecast configuration; no implicit latest cycle, system or timestep."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from .catalog import IFS, S2S, variables


class Box(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.north <= self.south or self.west == self.east:
            raise ValueError("A bbox requires north > south and nonzero longitude width")
        return self


class ForecastConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    product: Literal["ifs_medium_range", "s2s_ecds", "seasonal_ecmwf"]
    cycle: datetime
    members: tuple[StrictInt, ...] = Field(min_length=1)
    fields: dict[StrictStr, tuple[StrictInt, ...]]
    originating_centre: Literal["ecmwf"] = "ecmwf"
    system: StrictStr | None = None
    resolution: Literal["0p25", "0p1"] | None = None
    source: Literal["ecmwf", "aws", "google", "azure"] = "ecmwf"
    expected_ifs_cycle: Literal["48r1", "49r1", "50r1"] | None = None
    distribution_profile: Literal["open-data-pre-2026-10-20", "open-data-2026-10-20"] | None = None
    bbox: Box | None = None
    leads_per_request: StrictInt = Field(default=8, ge=1, le=32)
    max_messages: StrictInt = Field(default=10000, ge=1)
    max_grid_points: StrictInt = Field(default=8000000, ge=1)
    max_working_bytes: StrictInt = Field(default=1073741824, ge=1048576)

    @field_validator("cycle")
    @classmethod
    def explicit_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("cycle requires explicit UTC timezone")
        if value.minute or value.second or value.microsecond:
            raise ValueError("cycle must be an exact hour")
        return value

    @model_validator(mode="after")
    def product_contract(self) -> Self:
        if len(set(self.members)) != len(self.members) or any(m < 0 for m in self.members):
            raise ValueError("members must be distinct nonnegative native IDs")
        if tuple(sorted(self.members)) != self.members:
            raise ValueError("members must be sorted")
        if not self.fields:
            raise ValueError("At least one field with explicit lead times is required")
        specs = variables(self.product)
        for key, leads in self.fields.items():
            if key not in specs:
                raise ValueError(f"Unsupported surface field {key!r} for {self.product}")
            if not leads or leads != tuple(sorted(set(leads))) or min(leads) < 0:
                raise ValueError(f"{key}: leads must be sorted, unique, nonnegative hours")
            if specs[key].kind != "instant" and min(leads) == 0:
                raise ValueError(
                    f"{key}: zero-duration accumulations/means are not output intervals"
                )
            if self.product == IFS:
                limit = 360 if self.cycle.hour in (0, 12) else 144
                if any(h > limit or h % (3 if h <= 144 else 6) for h in leads):
                    raise ValueError(f"{key}: unsupported IFS Open Data lead")
            elif any(h % specs[key].cadence_hours for h in leads):
                raise ValueError(f"{key}: leads do not match the catalogue cadence")
        if self.product == IFS:
            if self.cycle.hour not in (0, 6, 12, 18) or self.system is not None:
                raise ValueError("IFS needs a synoptic cycle and no seasonal system")
            if self.cycle < datetime(2026, 5, 12, 6, tzinfo=UTC):
                raise ValueError("This Open Data profile targets post-50r1 cycles only")
            if max(self.members) > 50 or self.resolution is None:
                raise ValueError(
                    "IFS requires resolution and members 0 (control), 1..50 (perturbed)"
                )
            if self.resolution == "0p1" and self.cycle.date().isoformat() < "2026-10-20":
                raise ValueError("The 0p1 profile is not available before 2026-10-20")
        else:
            if self.resolution is not None or self.source != "ecmwf":
                raise ValueError(
                    "Store products use their catalogue grid and explicit ECMWF endpoint"
                )
            if self.cycle.hour != 0:
                raise ValueError("This ECMWF store profile supports 00 UTC initializations")
            if self.product == S2S:
                if self.system is not None or max(self.members) > 100:
                    raise ValueError("S2S is not seasonal CDS; no system, members at most 0..100")
            else:
                if self.system is None or not self.system.isdecimal():
                    raise ValueError("Seasonal CDS requires an explicitly selected numeric system")
                if self.cycle.day != 1:
                    raise ValueError("This ECMWF seasonal profile uses month-start initialization")
        from .ecmwf_profiles import resolve_config_profiles

        resolve_config_profiles(self)
        return self


class RemappingConfig(BaseModel):
    """Identity of the existing target HRUs, never a request to delineate a basin."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    target_path: Path
    hru_id_field: StrictStr = Field(default="hruId", min_length=1)
    geometry_version: StrictStr = Field(min_length=1)
    minimum_coverage: float = Field(default=0.999999, ge=0.99999, le=1, allow_inf_nan=False)
    cache_dir: Path | None = None
    expected_hru_ids: tuple[StrictInt, ...] | None = None

    @field_validator("target_path", "cache_dir")
    @classmethod
    def absolute_paths(cls, value):
        if value is not None and not value.is_absolute():
            raise ValueError("Remapping paths must be absolute in the Python API")
        return value

    @field_validator("expected_hru_ids")
    @classmethod
    def unique_ids(cls, value):
        if value is not None and (not value or len(set(value)) != len(value)):
            raise ValueError("expected_hru_ids must contain unique native identifiers")
        return value


class ModelForcingConfig(BaseModel):
    """Explicit temporal policies for preparing one SUMMA file per native member.

    'conservative' permits aggregation of complete native intervals only.
    'uniform' additionally permits redistribution within an interval while
    preserving its integral; it is an assumption, not recovered subhourly data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    model: Literal["SUMMA"] = "SUMMA"
    timestep_seconds: StrictInt = Field(ge=60, le=86400)
    start_lead_hour: StrictInt = Field(ge=0)
    end_lead_hour: StrictInt = Field(gt=0)
    instant_policy: Literal["exact", "linear"] = "exact"
    interval_policy: Literal["conservative", "uniform"] = "conservative"
    humidity_method: Literal["symfluence_magnus_water"] = "symfluence_magnus_water"

    @model_validator(mode="after")
    def covered_window(self):
        seconds = (self.end_lead_hour - self.start_lead_hour) * 3600
        if seconds <= 0 or seconds % self.timestep_seconds:
            raise ValueError("Forcing window must contain a positive whole number of timesteps")
        return self


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    domain_id: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    data_root: Path
    forecast: ForecastConfig
    remapping: RemappingConfig | None = None
    model_forcing: ModelForcingConfig | None = None

    @field_validator("data_root")
    @classmethod
    def absolute_root(cls, path):
        if not path.is_absolute():
            raise ValueError("data_root must be absolute in the Python API")
        return path

    @classmethod
    def from_file(cls, path: str | Path) -> DataConfig:
        path = Path(path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        if "data_root" in payload:
            payload["data_root"] = (path.parent / payload["data_root"]).resolve()
        if "remapping" in payload:
            for key in ("target_path", "cache_dir"):
                if payload["remapping"].get(key) is not None:
                    payload["remapping"][key] = (path.parent / payload["remapping"][key]).resolve()
        return cls.model_validate(payload)
