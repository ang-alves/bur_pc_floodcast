# SPDX-License-Identifier: GPL-3.0-or-later
"""ECMWF product policy reused from the source-reuse migration package.

This module neither downloads nor preprocesses data. It separates model cycle,
product family, access representation and seasonal catalogue system. It must not
be mistaken for a replacement DataManager, registry, CFIF layer or remapper.

"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

REFERENCE_COMMIT = "df9b6447080b85ec6566dc7ad4ed901a623ad0bc"
POLICY_VERSION = "ecmwf-source-reuse-review-2026-11-17"
REVIEWED_THROUGH = datetime(2026, 11, 17, 23, 59, 59, tzinfo=UTC)
MEDIUM_48R1 = datetime(2023, 6, 27, 6, tzinfo=UTC)
MEDIUM_49R1 = datetime(2024, 11, 12, 6, tzinfo=UTC)
MEDIUM_50R1 = datetime(2026, 5, 12, 6, tzinfo=UTC)
# Product-specific dates from the ECMWF S2S model history. In particular, these
# are not the medium-range 06 UTC clock.
SUBSEASONAL_48R1 = datetime(2023, 6, 27, 0, tzinfo=UTC)
SUBSEASONAL_49R1_VERIFIED_FROM = datetime(2024, 11, 12, 0, tzinfo=UTC)
SUBSEASONAL_50R1 = datetime(2026, 5, 13, 0, tzinfo=UTC)
OPEN_DATA_CHANGE_DAY = datetime(2026, 10, 20, tzinfo=UTC).date()
SEASONAL_51_REALTIME = datetime(2022, 11, 1, tzinfo=UTC)


class Product(StrEnum):
    MEDIUM_RANGE = "ifs_medium_range"
    SUBSEASONAL = "s2s_ecds"
    SEASONAL = "seasonal_ecmwf"


class ProfileError(ValueError):
    """Selection is ambiguous, outside reviewed coverage, or mixes identities."""


@dataclass(frozen=True)
class ModelProfile:
    product: Product
    reference_time: datetime
    ifs_cycle: str | None
    seasonal_system: str | None
    cycle_evidence: str
    hres_control_scientifically_identical: bool | None
    separate_hres_production: bool | None
    policy_version: str = POLICY_VERSION

    def record(self) -> dict:
        result = asdict(self)
        result["product"] = self.product.value
        result["reference_time"] = self.reference_time.isoformat()
        return result


@dataclass(frozen=True)
class AccessProfile:
    product: Product
    client: str
    dataset: str | None
    endpoint: str | None
    origin_field: str | None
    origin_value: str | None
    control_selection: tuple[tuple[str, str], ...]
    perturbed_selection: tuple[tuple[str, str], ...]
    delivery_grid: str | None
    distribution_profile: str
    seasonal_system: str | None
    availability_verified: bool = False
    notes: tuple[str, ...] = ()


def _reference_time(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ProfileError("reference_time must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ProfileError("reference_time must explicitly use UTC")
    if value.minute or value.second or value.microsecond:
        raise ProfileError("reference_time must be an exact initialization hour")
    if value > REVIEWED_THROUGH:
        raise ProfileError("Initialization is beyond the reviewed operational history")
    return value


def resolve_model_profile(
    product: Product | str,
    reference_time: datetime,
    *,
    kind: Literal["forecast", "reforecast"] = "forecast",
    expected_ifs_cycle: str | None = None,
    seasonal_system: str | None = None,
) -> ModelProfile:
    """Resolve operational forecast provenance, never catalogue availability.

    Reforecasts need their own model/reference-date schedule. Inferring their IFS
    cycle from the historical initialization date would be incorrect, so this first
    policy rejects that use rather than silently applying operational boundaries.
    """
    product = Product(product)
    when = _reference_time(reference_time)
    if kind != "forecast":
        raise ProfileError("Reforecast cycle selection requires its own production schedule")
    if product == Product.SEASONAL:
        if expected_ifs_cycle is not None:
            raise ProfileError("A seasonal catalogue system is not the operational IFS cycle")
        if not isinstance(seasonal_system, str) or seasonal_system not in {"5", "51"}:
            raise ProfileError("Select a reviewed ECMWF seasonal system explicitly: '5' or '51'")
        if seasonal_system == "5" and when >= SEASONAL_51_REALTIME:
            raise ProfileError(
                "From November 2022 the reviewed CDS real-time profile uses system=51"
            )
        return ModelProfile(
            product, when, None, seasonal_system, "explicit_catalogue_system", None, None
        )
    if seasonal_system is not None:
        raise ProfileError("seasonal_system is invalid for medium-range or S2S forecasts")
    if product == Product.MEDIUM_RANGE:
        if when.hour not in {0, 6, 12, 18}:
            raise ProfileError("Medium-range initialization must be 00, 06, 12 or 18 UTC")
        if when < MEDIUM_48R1:
            raise ProfileError("Medium-range history before 48r1 is not included in this policy")
        cycle = "50r1" if when >= MEDIUM_50R1 else "49r1" if when >= MEDIUM_49R1 else "48r1"
        identical = cycle in {"49r1", "50r1"}
        separate = cycle != "50r1"
    else:
        if when.hour != 0:
            raise ProfileError("This reviewed S2S profile initializes at 00 UTC")
        if when < SUBSEASONAL_48R1:
            raise ProfileError("S2S history before 48r1 is outside this reviewed profile")
        cycle = (
            "50r1"
            if when >= SUBSEASONAL_50R1
            else "49r1"
            if when >= SUBSEASONAL_49R1_VERIFIED_FROM
            else "48r1"
        )
        identical = separate = None
    if expected_ifs_cycle is not None and expected_ifs_cycle != cycle:
        raise ProfileError(
            f"Configured IFS cycle {expected_ifs_cycle} conflicts with documented {cycle}"
        )
    return ModelProfile(
        product, when, cycle, None, "documented_operational_timeline", identical, separate
    )


def resolve_access_profile(
    profile: ModelProfile,
    *,
    delivery_grid: str | None = None,
    distribution_profile: str | None = None,
) -> AccessProfile:
    """Describe native request keys, NOT a complete or submitted API request.

    The 20 October Open Data announcement is a publication date, not an exact
    initialization cutover. On that day the caller must provide the distribution
    profile explicitly rather than this function inventing a transition hour.
    """
    if profile.policy_version != POLICY_VERSION:
        raise ProfileError("Model profile was resolved by another policy version")
    when = _reference_time(profile.reference_time)
    if profile.product == Product.MEDIUM_RANGE:
        if delivery_grid not in {"0p25", "0p1"}:
            raise ProfileError(
                "Choose the distributed grid explicitly, separately from native model resolution"
            )
        # This access slice deliberately does not claim historical Open Data schemas.
        if when < MEDIUM_50R1:
            raise ProfileError(
                "Historical scientific profiles are known; "
                "their Open Data access profile is not enabled here"
            )
        current = "open-data-2026-10-20"
        previous = "open-data-pre-2026-10-20"
        if when.date() == OPEN_DATA_CHANGE_DAY:
            if distribution_profile not in {previous, current}:
                raise ProfileError(
                    "20 October cutover needs an explicitly confirmed distribution profile"
                )
            selected = distribution_profile
        else:
            selected = current if when.date() > OPEN_DATA_CHANGE_DAY else previous
            if distribution_profile is not None and distribution_profile != selected:
                raise ProfileError(
                    "Distribution profile conflicts with the reviewed publication period"
                )
        if delivery_grid == "0p1" and selected != current:
            raise ProfileError("0p1 is not part of the older reviewed distribution profile")
        control = (("stream", "oper"), ("type", "fc"))
        notes = [
            "These are distributed regular-grid products, not the native ~9 km model mesh.",
            "Rolling-archive availability must be checked separately.",
        ]
        if delivery_grid == "0p1":
            notes.append("Surface/pressure files are separate; publication is later than 0p25.")
        return AccessProfile(
            profile.product,
            "ecmwf-opendata",
            None,
            None,
            "model",
            "ifs",
            control,
            (("stream", "enfo"), ("type", "pf")),
            delivery_grid,
            selected,
            None,
            notes=tuple(notes),
        )
    if delivery_grid is not None or distribution_profile is not None:
        raise ProfileError("Open Data grid/distribution flags do not configure ECDS or CDS")
    if profile.product == Product.SUBSEASONAL:
        return AccessProfile(
            profile.product,
            "cdsapi",
            "s2s-forecasts",
            "https://ecds.ecmwf.int/api",
            "origin",
            "ecmwf",
            (("forecast_type", "control_forecast"),),
            (("forecast_type", "perturbed_forecast"),),
            None,
            "ecds-s2s-catalogue",
            None,
            notes=(
                "Operational model-cycle provenance does not remove the S2S publication delay.",
            ),
        )
    return AccessProfile(
        profile.product,
        "cdsapi",
        "seasonal-original-single-levels",
        "https://cds.climate.copernicus.eu/api",
        "originating_centre",
        "ecmwf",
        (),
        (),
        None,
        "cds-seasonal-original",
        profile.seasonal_system,
        notes=("Keep system and actual grid identity with forecasts and hindcasts.",),
    )


def medium_control_encoding(profile: ModelProfile) -> dict[str, str]:
    """Scientific archive representation; not a guarantee of Open Data access."""
    if profile.product != Product.MEDIUM_RANGE:
        raise ProfileError("This encoding change is specific to IFS medium range")
    if profile.ifs_cycle == "50r1":
        return {"stream": "oper", "type": "fc"}
    if profile.ifs_cycle in {"48r1", "49r1"}:
        return {"stream": "enfo", "type": "cf"}
    raise ProfileError("Unreviewed IFS cycle")


def resolve_config_profiles(config) -> dict:
    """Return serializable provenance consumed by the plan and its cache key.

    The returned model cycle comes from the reviewed provider timeline, not from
    inspecting a GRIB. Actual encoding metadata is recorded separately during
    decoding; successful planning never claims data availability or validation.
    """
    beyond_review = config.cycle > REVIEWED_THROUGH
    if beyond_review:
        product = Product(config.product)
        expected = getattr(config, "expected_ifs_cycle", None)
        distribution = getattr(config, "distribution_profile", None)
        if product == Product.SEASONAL:
            if config.system != "51" or expected is not None:
                raise ProfileError(
                    "Future seasonal runs require explicit reviewed system='51' "
                    "and no IFS-cycle alias"
                )
            model = ModelProfile(
                product,
                config.cycle,
                None,
                "51",
                "explicit_pinned_profile_beyond_reviewed_history",
                None,
                None,
            )
        else:
            if expected != "50r1" or config.system is not None:
                raise ProfileError(
                    "Beyond reviewed history, explicitly pin expected_ifs_cycle='50r1'; "
                    "the GRIB must confirm it"
                )
            if product == Product.MEDIUM_RANGE and distribution != "open-data-2026-10-20":
                raise ProfileError(
                    "Future IFS runs require explicit distribution_profile='open-data-2026-10-20'"
                )
            model = ModelProfile(
                product,
                config.cycle,
                "50r1",
                None,
                "explicit_pinned_profile_beyond_reviewed_history",
                True if product == Product.MEDIUM_RANGE else None,
                False if product == Product.MEDIUM_RANGE else None,
            )
        # Resolve the explicitly pinned access representation at the reviewed
        # anchor; never send a future date into the historical inference API.
        access_model = replace(
            model, reference_time=REVIEWED_THROUGH.replace(hour=0, minute=0, second=0)
        )
    else:
        model = resolve_model_profile(
            config.product,
            config.cycle,
            expected_ifs_cycle=getattr(config, "expected_ifs_cycle", None),
            seasonal_system=config.system,
        )
        access_model = model
    access = resolve_access_profile(
        access_model,
        delivery_grid=config.resolution,
        distribution_profile=getattr(config, "distribution_profile", None),
    )
    access_record = asdict(access)
    access_record["product"] = access.product.value
    access_record["control_selection"] = dict(access.control_selection)
    access_record["perturbed_selection"] = dict(access.perturbed_selection)
    access_record["notes"] = list(access.notes)
    if beyond_review:
        access_record["notes"].append(
            "Explicit pinned profile beyond reviewed history; actual GRIB identity must match "
            "and provider availability is not established."
        )
    return {
        "source_code_commit": REFERENCE_COMMIT,
        "policy_version": POLICY_VERSION,
        "reviewed_through": REVIEWED_THROUGH.isoformat(),
        **({"beyond_reviewed_history": True} if beyond_review else {}),
        "model": model.record(),
        "access": access_record,
    }
