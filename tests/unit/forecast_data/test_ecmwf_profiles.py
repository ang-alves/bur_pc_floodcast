# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import UTC, datetime

import pytest

from floodcast.data.ecmwf_profiles import (
    Product,
    ProfileError,
    medium_control_encoding,
    resolve_access_profile,
    resolve_model_profile,
)


def dt(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.mark.parametrize(
    "when,cycle",
    [
        ("2023-06-27T06:00:00Z", "48r1"),
        ("2024-11-12T00:00:00Z", "48r1"),
        ("2024-11-12T06:00:00Z", "49r1"),
        ("2026-05-12T00:00:00Z", "49r1"),
        ("2026-05-12T06:00:00Z", "50r1"),
        ("2026-05-12T12:00:00Z", "50r1"),
        ("2026-05-12T18:00:00Z", "50r1"),
        ("2026-05-13T00:00:00Z", "50r1"),
    ],
)
def test_medium_exact_boundaries(when, cycle):
    profile = resolve_model_profile(Product.MEDIUM_RANGE, dt(when))
    assert profile.ifs_cycle == cycle
    assert profile.seasonal_system is None


@pytest.mark.parametrize(
    "when,cycle",
    [
        ("2026-05-11T00:00:00Z", "49r1"),
        ("2026-05-12T00:00:00Z", "49r1"),
        ("2026-05-13T00:00:00Z", "50r1"),
        ("2026-11-17T00:00:00Z", "50r1"),
    ],
)
def test_s2s_uses_its_own_clock(when, cycle):
    assert resolve_model_profile(Product.SUBSEASONAL, dt(when)).ifs_cycle == cycle


@pytest.mark.parametrize(
    "when,identical,separate",
    [
        ("2023-06-28T00:00:00Z", False, True),
        ("2025-01-01T00:00:00Z", True, True),
        ("2026-05-12T06:00:00Z", True, False),
    ],
)
def test_resolution_equality_is_not_control_identity(when, identical, separate):
    profile = resolve_model_profile(Product.MEDIUM_RANGE, dt(when))
    assert profile.hres_control_scientifically_identical is identical
    assert profile.separate_hres_production is separate


def test_medium_control_mapping():
    before = resolve_model_profile(Product.MEDIUM_RANGE, dt("2026-05-12T00:00:00Z"))
    after = resolve_model_profile(Product.MEDIUM_RANGE, dt("2026-05-12T06:00:00Z"))
    assert medium_control_encoding(before) == {"stream": "enfo", "type": "cf"}
    assert medium_control_encoding(after) == {"stream": "oper", "type": "fc"}
    with pytest.raises(ProfileError):
        medium_control_encoding(
            resolve_model_profile(Product.SUBSEASONAL, dt("2026-05-13T00:00:00Z"))
        )


@pytest.mark.parametrize("product", list(Product))
def test_reforecast_is_not_inferred_from_historical_initialization(product):
    with pytest.raises(ProfileError, match="Reforecast"):
        resolve_model_profile(product, dt("2026-11-01T00:00:00Z"), kind="reforecast")


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 11, 17),
        datetime(2026, 11, 17, 0, 30, tzinfo=UTC),
        dt("2027-01-01T00:00:00Z"),
    ],
)
def test_ambiguous_or_future_initialization_rejected(when):
    with pytest.raises(ProfileError):
        resolve_model_profile(Product.MEDIUM_RANGE, when)


def test_conflicting_cycle_cannot_override_documentation():
    with pytest.raises(ProfileError, match="conflicts"):
        resolve_model_profile(
            Product.MEDIUM_RANGE, dt("2026-05-12T06:00:00Z"), expected_ifs_cycle="49r1"
        )


def test_s2s_history_not_guessed():
    with pytest.raises(ProfileError, match="S2S history"):
        resolve_model_profile(Product.SUBSEASONAL, dt("2023-01-01T00:00:00Z"))
    assert (
        resolve_model_profile(Product.SUBSEASONAL, dt("2024-01-01T00:00:00Z")).ifs_cycle == "48r1"
    )
    with pytest.raises(ProfileError, match="00 UTC"):
        resolve_model_profile(Product.SUBSEASONAL, dt("2026-05-12T06:00:00Z"))


def test_seasonal_keeps_separate_system_identity():
    profile = resolve_model_profile(
        Product.SEASONAL, dt("2026-11-01T00:00:00Z"), seasonal_system="51"
    )
    assert profile.seasonal_system == "51" and profile.ifs_cycle is None
    access = resolve_access_profile(profile)
    assert access.dataset == "seasonal-original-single-levels"
    assert access.origin_field == "originating_centre" and access.origin_value == "ecmwf"
    assert access.seasonal_system == "51"
    assert not access.availability_verified


@pytest.mark.parametrize("system", [None, "latest", "50r1", "6", 51, "5"])
def test_invalid_current_seasonal_system(system):
    with pytest.raises(ProfileError):
        resolve_model_profile(Product.SEASONAL, dt("2026-11-01T00:00:00Z"), seasonal_system=system)


def test_no_operational_ifs_cycle_assigned_to_seasonal():
    with pytest.raises(ProfileError):
        resolve_model_profile(
            Product.SEASONAL,
            dt("2026-11-01T00:00:00Z"),
            seasonal_system="51",
            expected_ifs_cycle="50r1",
        )


def test_open_data_change_does_not_change_model_cycle():
    earlier = resolve_model_profile(Product.MEDIUM_RANGE, dt("2026-10-19T00:00:00Z"))
    later = resolve_model_profile(Product.MEDIUM_RANGE, dt("2026-10-21T00:00:00Z"))
    assert earlier.ifs_cycle == later.ifs_cycle == "50r1"
    assert (
        resolve_access_profile(earlier, delivery_grid="0p25").distribution_profile
        != resolve_access_profile(later, delivery_grid="0p25").distribution_profile
    )
    with pytest.raises(ProfileError):
        resolve_access_profile(earlier, delivery_grid="0p1")
    assert resolve_access_profile(later, delivery_grid="0p1").delivery_grid == "0p1"


def test_announcement_day_is_not_an_invented_utc_cutover():
    profile = resolve_model_profile(Product.MEDIUM_RANGE, dt("2026-10-20T06:00:00Z"))
    with pytest.raises(ProfileError, match="explicitly confirmed"):
        resolve_access_profile(profile, delivery_grid="0p1")
    resolved = resolve_access_profile(
        profile, delivery_grid="0p1", distribution_profile="open-data-2026-10-20"
    )
    assert resolved.control_selection == (("stream", "oper"), ("type", "fc"))
    assert not resolved.availability_verified


def test_current_access_profiles_remain_separate():
    now = dt("2026-11-17T00:00:00Z")
    medium = resolve_access_profile(
        resolve_model_profile(Product.MEDIUM_RANGE, now), delivery_grid="0p25"
    )
    s2s = resolve_access_profile(resolve_model_profile(Product.SUBSEASONAL, now))
    assert medium.client == "ecmwf-opendata"
    assert s2s.client == "cdsapi" and s2s.dataset == "s2s-forecasts"
    assert s2s.endpoint == "https://ecds.ecmwf.int/api"
    assert s2s.origin_field == "origin"
    assert s2s.control_selection == (("forecast_type", "control_forecast"),)
    with pytest.raises(ProfileError):
        resolve_access_profile(
            resolve_model_profile(Product.SUBSEASONAL, now), delivery_grid="0p25"
        )


def test_known_scientific_history_does_not_claim_historical_download_access():
    profile = resolve_model_profile(Product.MEDIUM_RANGE, dt("2025-01-01T00:00:00Z"))
    with pytest.raises(ProfileError, match="Historical"):
        resolve_access_profile(profile, delivery_grid="0p25")


@pytest.mark.parametrize("hour", [6, 12, 18])
def test_profile_is_consumed_by_forecast_config_and_plan(config_factory, hour):
    from floodcast.data.data_manager import DataManager

    config = config_factory(cycle=datetime(2026, 5, 12, hour, tzinfo=UTC))
    plan = DataManager(config).plan()
    assert plan.provenance["model"]["ifs_cycle"] == "50r1"
    assert plan.provenance["access"]["control_selection"] == {"stream": "oper", "type": "fc"}
    assert plan.provenance["access"]["availability_verified"] is False


def test_expected_cycle_is_checked_before_acquisition(config_factory):
    with pytest.raises(ValueError, match="conflicts"):
        config_factory(expected_ifs_cycle="49r1")


def test_config_requires_distribution_identity_on_announcement_day(config_factory):
    with pytest.raises(ValueError, match="explicitly confirmed"):
        config_factory(cycle="2026-10-20T06:00:00Z", resolution="0p1")
    config_factory(
        cycle="2026-10-20T06:00:00Z", resolution="0p1", distribution_profile="open-data-2026-10-20"
    )


@pytest.mark.parametrize(
    "pins", [{}, {"expected_ifs_cycle": "50r1"}, {"distribution_profile": "open-data-2026-10-20"}]
)
def test_future_ifs_needs_both_explicit_pins(config_factory, pins):
    with pytest.raises(ValueError):
        config_factory(cycle="2026-11-18T00:00:00Z", **pins)


def test_future_ifs_pin_is_not_historical_inference(config_factory):
    from floodcast.data.data_manager import DataManager

    config = config_factory(
        cycle="2026-11-18T00:00:00Z",
        expected_ifs_cycle="50r1",
        distribution_profile="open-data-2026-10-20",
    )
    provenance = DataManager(config).plan().provenance
    assert (
        provenance["model"]["cycle_evidence"] == "explicit_pinned_profile_beyond_reviewed_history"
    )
    assert provenance["beyond_reviewed_history"] is True
    assert provenance["access"]["availability_verified"] is False


@pytest.mark.parametrize(
    "product,changes",
    [
        ("s2s_ecds", {"cycle": "2026-11-18T00:00:00Z", "expected_ifs_cycle": "50r1"}),
        ("seasonal_ecmwf", {"cycle": "2026-12-01T00:00:00Z", "system": "51"}),
    ],
)
def test_future_store_products_keep_separate_explicit_identity(config_factory, product, changes):
    from floodcast.data.data_manager import DataManager

    provenance = DataManager(config_factory(product, **changes)).plan().provenance
    assert provenance["beyond_reviewed_history"] is True
    assert provenance["model"]["ifs_cycle"] == (None if product == "seasonal_ecmwf" else "50r1")
