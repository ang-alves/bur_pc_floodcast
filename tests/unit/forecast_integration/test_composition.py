"""Public composition, evidence boundaries, and additive CLI integration."""

import json
import logging
import subprocess
import sys

import pytest

from floodcast.cli import main
from floodcast.core.config import RuntimeConfig
from floodcast.core.errors import FloodcastError
from floodcast.core.registries import Registries
from floodcast.core.registry import ComponentManifest
from floodcast.data.base_registry import BaseRegistry, register_class
from floodcast.data.config import DataConfig
from floodcast.data.contracts import DataResult
from floodcast.data.registration import register_data_handlers
from floodcast.data.workflow import (
    compose_forecast_workflow,
    make_forecast_request,
    register_forecast_steps,
)
from floodcast.project import Floodcast


@pytest.fixture
def config(tmp_path):
    geometry = tmp_path / "hrus.geojson"
    geometry.write_text('{"type":"FeatureCollection","features":[]}')
    return DataConfig.model_validate(
        {
            "domain_id": "test_basin",
            "data_root": str(tmp_path / "data"),
            "forecast": {
                "product": "ifs_medium_range",
                "cycle": "2026-11-17T00:00:00Z",
                "members": [0, 1],
                "resolution": "0p25",
                "fields": {"tp": [3, 6]},
            },
            "remapping": {"target_path": str(geometry), "geometry_version": "test-v1"},
            "model_forcing": {
                "timestep_seconds": 10800,
                "start_lead_hour": 0,
                "end_lead_hour": 6,
            },
        }
    )


def test_upstream_lookup_is_scoped_lazy_and_case_insensitive():
    constructions = []

    class Handler:
        def __init__(self, config, logger, **kwargs):
            constructions.append((config, kwargs))

    class Lookup(BaseRegistry):
        registry_name = "acquisition_handlers"

    one, two = Registries(), Registries()
    register_class(one.acquisition_handlers, "CuStOm", Handler)
    first, other = Lookup(one), Lookup(two)
    assert first.is_registered("CUSTOM")
    assert first.list_handlers() == ("custom",)
    assert constructions == []
    assert first.get_handler("CUSTOM", 12, logging.getLogger()) is not first.get_handler(
        "custom", 12, logging.getLogger()
    )
    assert len(constructions) == 2
    assert not other.is_registered("custom")
    with pytest.raises(ValueError, match="Unknown handler"):
        other.get_handler("custom", 12, logging.getLogger())


def test_data_registration_failure_leaves_every_application_family_untouched(monkeypatch):
    from floodcast.data.preprocessing import dataset_handlers

    app = Registries()

    def broken_loader(registries):
        raise ImportError("controlled missing dataset implementation")

    monkeypatch.setattr(dataset_handlers, "register_handlers", broken_loader)
    with pytest.raises(ImportError):
        register_data_handlers(app)
    assert app.acquisition_handlers.manifests() == ()
    assert app.dataset_handlers.manifests() == ()
    assert app.forcing_adapters.manifests() == ()


def test_builtin_composition_preserves_custom_handler_and_duplicate_is_atomic():
    class Custom:
        pass

    app = Registries()
    register_class(app.acquisition_handlers, "custom", Custom)
    register_data_handlers(app)
    before = (
        app.acquisition_handlers.manifests(),
        app.dataset_handlers.manifests(),
        app.forcing_adapters.manifests(),
    )
    with pytest.raises(ValueError, match="already registered"):
        register_data_handlers(app)
    assert before == (
        app.acquisition_handlers.manifests(),
        app.dataset_handlers.manifests(),
        app.forcing_adapters.manifests(),
    )
    assert app.acquisition_handlers.resolve("custom").factory() is Custom


def test_forecast_step_conflict_is_preflighted():
    app = Registries()
    register_data_handlers(app)
    app.steps.register(
        ComponentManifest(
            component_id="forecast.model_ready",
            contract_id="ffw.step/v1",
            implementation_version="custom",
            source_revision="custom",
        ),
        object,
    )
    before = app.steps.manifests()
    with pytest.raises(ValueError, match="already registered"):
        register_forecast_steps(app)
    assert app.steps.manifests() == before


def test_composed_graph_and_source_inputs_are_concrete(config):
    graph = compose_forecast_workflow(config)
    assert [s.component_id for s in graph.ordered_steps()] == [
        "forecast.acquire",
        "forecast.normalize",
        "forecast.remap",
        "forecast.model_ready",
    ]
    request = make_forecast_request(config, t0=config.forecast.cycle)
    assert [ref.path for ref in request.inputs] == [config.remapping.target_path]
    assert graph.steps[0].retry_safe is False
    assert all(step.retry_safe for step in graph.steps[1:])
    assert graph.steps[2].configuration["normalize_step"] == "normalize"
    assert graph.steps[3].configuration["remapping_step"] == "remap"


def test_shapefile_companions_are_hashed(config, tmp_path):
    shp = tmp_path / "hrus.shp"
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        shp.with_suffix(suffix).write_bytes(suffix.encode())
    values = config.model_dump(mode="python")
    values["remapping"]["target_path"] = shp
    selected = DataConfig.model_validate(values)
    request = make_forecast_request(selected, t0=config.forecast.cycle)
    assert {ref.path.suffix for ref in request.inputs} == {".shp", ".shx", ".dbf", ".prj", ".cpg"}


def test_graph_to_model_ready_and_immutable_resume(config, monkeypatch):
    calls = []

    class BoundaryManager:
        def __init__(self, selected, logger, *, registries, services, reader):
            assert selected == config
            assert registries is app.R

        def emit(self, stage, input_path=None):
            calls.append((stage, input_path.name if input_path else None))
            folder = config.data_root / stage
            folder.mkdir(parents=True)
            path = (
                folder
                / {
                    "raw": "acquisition_manifest.json",
                    "canonical": "canonical_manifest.json",
                    "remapped": "remapped_manifest.json",
                    "forcing": "forcing_manifest.json",
                }[stage]
            )
            path.write_text(json.dumps({"boundary_test": stage}))
            data = folder / "data.bin"
            data.write_bytes(stage.encode())
            return DataResult(manifest_path=path, files=(data,))

        def acquire_forcings(self):
            return self.emit("raw")

        def run_model_agnostic_preprocessing(self, path):
            return self.emit("canonical", path)

        def remap_forcings(self, path):
            return self.emit("remapped", path)

        def prepare_model_forcings(self, path):
            return self.emit("forcing", path)

    monkeypatch.setattr("floodcast.data.workflow.DataManager", BoundaryManager)
    app = Floodcast(RuntimeConfig(data_root=config.data_root), code_identity="integration-test")
    app.with_forecast_data()
    graph = compose_forecast_workflow(config)
    request = make_forecast_request(config, t0=config.forecast.cycle)
    result = app.run(graph, request)
    assert result.status == "succeeded"
    assert calls == [
        ("raw", None),
        ("canonical", "acquisition_manifest.json"),
        ("remapped", "canonical_manifest.json"),
        ("forcing", "remapped_manifest.json"),
    ]
    assert app.run(graph, request, resume=True) == result
    assert len(calls) == 4
    config.remapping.target_path.write_text("changed geometry")
    with pytest.raises(FloodcastError):
        app.run(graph, request, resume=True)
    assert len(calls) == 4


def test_forcing_adapter_revision_participates_in_workflow_identity(config):
    first, second = Registries(), Registries()
    for registry in (first, second):
        registry.steps.register(
            ComponentManifest(
                component_id="forecast.acquire",
                contract_id="ffw.step/v1",
                implementation_version="1",
                source_revision="same",
            ),
            object,
        )
        registry.steps.register(
            ComponentManifest(
                component_id="forecast.normalize",
                contract_id="ffw.step/v1",
                implementation_version="1",
                source_revision="same",
            ),
            object,
        )
    for registry, revision in ((first, "a"), (second, "b")):
        registry.forcing_adapters.register(
            ComponentManifest(
                component_id="summa",
                contract_id="ffw.forcing-adapter/v1",
                implementation_version="1",
                source_revision=revision,
            ),
            object,
        )
    runtime = RuntimeConfig(data_root=config.data_root)
    graph = compose_forecast_workflow(config, through="canonical")
    request = make_forecast_request(config, t0=config.forecast.cycle)
    a = Floodcast(runtime, code_identity="same", registries=first).plan(graph, request)
    b = Floodcast(runtime, code_identity="same", registries=second).plan(graph, request)
    assert a.fingerprint != b.fingerprint


def test_application_reuses_R_and_enforces_data_root(config):
    app = Floodcast(RuntimeConfig(data_root=config.data_root), code_identity="test")
    app.with_forecast_data()
    assert app.data(config).R is app.R
    other = DataConfig.model_validate(
        {
            **config.model_dump(mode="python"),
            "data_root": config.data_root.parent / "other",
        }
    )
    with pytest.raises(FloodcastError, match="data_root"):
        app.data(other)


@pytest.mark.parametrize("argv", [["--help"], ["data", "--help"]])
def test_data_cli_help_does_not_import_configuration_or_optional_dependencies(argv):
    code = """
import importlib.abc
import sys
class RejectHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("floodcast.core", "floodcast.data", "floodcast.services",
                                "eccodes", "xarray", "geopandas", "ecmwf", "cdsapi")):
            raise AssertionError("Help imported " + fullname)
sys.meta_path.insert(0, RejectHeavy())
from floodcast.cli import main
main(sys.argv[1:])
"""
    result = subprocess.run([sys.executable, "-c", code, *argv], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_forecast_plan_cli_uses_data_config_without_runtime_loader(tmp_path, monkeypatch, capsys):
    selected = tmp_path / "forecast.toml"
    selected.write_text("""domain_id="test"
data_root="data"
[forecast]
product="ifs_medium_range"
cycle="2026-11-17T00:00:00Z"
members=[0]
resolution="0p25"
[forecast.fields]
tp=[3,6]
""")

    def forbidden(*args, **kwargs):
        raise AssertionError("Forecast plan must not read RuntimeConfig")

    monkeypatch.setattr("floodcast.core.config.load_config", forbidden)
    assert main(["data", "plan", "--config", str(selected)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["config"]["product"] == "ifs_medium_range"
    assert not (tmp_path / "data").exists()


def test_data_cli_reports_missing_manifest_as_configuration_error(capsys):
    assert main(["data", "remap", "--config", "unused.toml", "--json"]) == 2
    assert "requires --manifest" in json.loads(capsys.readouterr().err)["message"]
