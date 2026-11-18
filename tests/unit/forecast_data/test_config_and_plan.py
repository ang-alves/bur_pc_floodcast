import pytest

from floodcast.core.registries import Registries
from floodcast.data.acquisition.registry import AcquisitionRegistry
from floodcast.data.catalog import IFS, S2S, SEASONAL
from floodcast.data.config import DataConfig
from floodcast.data.data_manager import DataManager
from floodcast.data.registration import register_data_handlers


@pytest.mark.parametrize("product", [IFS, S2S, SEASONAL])
def test_products_have_distinct_handlers(config_factory, product):
    app = DataManager(config_factory(product))
    assert len(app.R.acquisition_handlers.manifests()) == 3
    assert len(app.R.dataset_handlers.manifests()) == 3
    assert app.plan().config.product == product
    assert app.validate_readiness()["model_ready"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"members": [0, 0]},
        {"members": [True]},
        {"members": [-1]},
        {"members": [1, 0]},
        {"members": [51]},
        {"fields": {}},
        {"fields": {"tp": [0, 3]}},
        {"fields": {"tp": [6, 3]}},
        {"fields": {"tp": [1]}},
        {"fields": {"bad": [6]}},
        {"cycle": "2026-11-17T00:00:00"},
        {"cycle": "2026-11-17T00:30:00Z"},
        {"cycle": "2026-11-17T03:00:00Z"},
        {"cycle": "2026-01-01T00:00:00Z"},
        {"resolution": None},
        {"system": "51"},
        {"originating_centre": "ukmo"},
    ],
)
def test_bad_ifs_configs_rejected(config_factory, changes):
    with pytest.raises(ValueError):
        config_factory(**changes)


def test_ifs_uses_post50r1_control_and_pf(config_factory):
    plan = DataManager(config_factory()).plan()
    control, perturbed = plan.parts
    assert (control.payload["stream"], control.payload["type"]) == ("oper", "fc")
    assert (perturbed.payload["stream"], perturbed.payload["type"]) == ("enfo", "pf")
    assert "number" not in control.payload
    assert perturbed.payload["number"] == [1]
    assert control.payload["date"] == "20261117"
    assert "area" not in control.payload


@pytest.mark.parametrize(
    "product, transport, dataset",
    [(S2S, "ecds", "s2s-forecasts"), (SEASONAL, "cds", "seasonal-original-single-levels")],
)
def test_stores_no_fake_member_selection(config_factory, product, transport, dataset):
    plan = DataManager(config_factory(product)).plan()
    for part in plan.parts:
        assert part.transport == transport and part.dataset == dataset
        assert "number" not in part.payload
        assert part.payload["data_format"] == "grib"
    if product == SEASONAL:
        assert plan.parts[0].payload["system"] == "51"
        assert plan.parts[0].payload["originating_centre"] == "ecmwf"
    else:
        assert plan.parts[0].payload["origin"] == "ecmwf"
        assert plan.parts[0].payload["forecast_type"] == "control_forecast"


@pytest.mark.parametrize(
    "product,changes",
    [
        (S2S, {"system": "51"}),
        (S2S, {"resolution": "0p25"}),
        (S2S, {"fields": {"2t": [6]}}),
        (S2S, {"fields": {"sp": [24]}}),
        (S2S, {"fields": {"msl": [6]}}),
        (SEASONAL, {"system": None}),
        (SEASONAL, {"system": "latest"}),
        (SEASONAL, {"fields": {"sp": [6]}}),
        (SEASONAL, {"fields": {"tp": [6]}}),
        (SEASONAL, {"cycle": "2026-11-02T00:00:00Z"}),
    ],
)
def test_bad_store_configs_rejected(config_factory, product, changes):
    with pytest.raises(ValueError):
        config_factory(product, **changes)


def test_ifs_06_cycle_horizon(config_factory):
    with pytest.raises(ValueError):
        config_factory(cycle="2026-11-17T06:00:00Z", fields={"tp": [150]})
    config_factory(cycle="2026-11-17T06:00:00Z", fields={"tp": [144]})


def test_01_resolution_guard(config_factory):
    config_factory(resolution="0p1")
    with pytest.raises(ValueError):
        config_factory(resolution="0p1", cycle="2026-10-19T00:00:00Z")


def test_registry_is_application_scoped(config_factory, logger):
    one, two = (Registries(), Registries())
    register_data_handlers(one)
    assert two.acquisition_handlers.manifests() == ()
    handler = AcquisitionRegistry(one).get_handler(
        "IFS_MEDIUM_RANGE", config_factory().forecast, logger
    )
    assert handler.product == IFS
    with pytest.raises(ValueError):
        register_data_handlers(one)
    with pytest.raises(ValueError, match="Unknown handler"):
        AcquisitionRegistry(two).get_handler(IFS, config_factory().forecast, logger)


def test_request_identity_changes(config_factory):
    first = DataManager(config_factory()).plan().request_sha256
    changes = [
        {"members": [0]},
        {"source": "aws"},
        {"fields": {"tp": [6]}},
        {"resolution": "0p1"},
        {"cycle": "2026-11-17T12:00:00Z"},
        {"bbox": {"north": 41, "west": -10, "south": 38, "east": -7}},
    ]
    assert all(
        DataManager(config_factory(**change)).plan().request_sha256 != first for change in changes
    )
    assert DataManager(config_factory()).plan().request_sha256 == first


def test_chunking_retains_explicit_coverage(config_factory):
    plan = DataManager(config_factory(fields={"tp": [3, 6, 9, 12, 15]}, leads_per_request=2)).plan()
    assert len(plan.parts) == 6
    assert [h for p in plan.parts if p.role == "control" for h in p.payload["step"]] == [
        3,
        6,
        9,
        12,
        15,
    ]


def test_toml_paths_resolved_relative_to_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'domain_id="x"\ndata_root="local-data"\n[forecast]\nproduct="ifs_medium_range"\ncycle="2026-11-17T00:00:00Z"\nmembers=[0]\nresolution="0p25"\n[forecast.fields]\ntp=[3,6]\n'
    )
    assert DataConfig.from_file(path).data_root == tmp_path / "local-data"


def test_seasonal_mixed_cadences_not_replaced_with_hourly(config_factory):
    config = config_factory(SEASONAL, fields={"2t": [6, 12, 18, 24], "tp": [24, 48]})
    plan = DataManager(config).plan()
    assert plan.config.fields["tp"] == (24, 48)
    assert plan.config.fields["2t"] == (6, 12, 18, 24)
