import json

import pytest

from floodcast.data.catalog import S2S, SEASONAL
from floodcast.data.contracts import FileRecord
from floodcast.data.data_manager import DataManager
from floodcast.data.errors import DataError


@pytest.mark.parametrize("schema", [True, "1", 2, 1.0])
def test_manifest_schema_version_is_not_coerced(schema):
    with pytest.raises(ValueError):
        FileRecord(schema_version=schema, relative_path="x", sha256="0" * 64, size=1)


@pytest.mark.parametrize("product", [S2S, SEASONAL])
def test_store_requests_subset_area_without_interpolating_grid(config_factory, product):
    cfg = config_factory(product, bbox={"north": 42, "west": -10, "south": 36, "east": -6})
    plan = DataManager(cfg).plan()
    assert all(p.payload["area"] == [42.0, -10.0, 36.0, -6.0] for p in plan.parts)
    if product == S2S:
        assert all(p.payload["grid"] == "1.5/1.5" for p in plan.parts)


def test_half_written_normalization_is_not_published_and_can_retry(
    config_factory, fake_services, fake_reader, monkeypatch
):
    import floodcast.data.preprocessing.forecast_processor as module

    cfg = config_factory(fields={"tp": [6, 12], "2t": [6, 12]})
    manager = DataManager(cfg, services=fake_services, reader=fake_reader)
    raw = manager.acquire_forcings()
    original = module.write_netcdf_atomic
    calls = []

    def interrupted(ds, path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("injected disk failure")
        return original(ds, path)

    monkeypatch.setattr(module, "write_netcdf_atomic", interrupted)
    with pytest.raises(OSError):
        manager.run_model_agnostic_preprocessing(raw.manifest_path)
    assert not (raw.manifest_path.parent.parent / "canonical").exists()
    assert not list(raw.manifest_path.parent.parent.glob(".canonical-*.tmp"))
    assert all(path.exists() for path in raw.files)
    monkeypatch.setattr(module, "write_netcdf_atomic", original)
    processed = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    assert len(processed.files) == 2


def test_canonical_metadata_tampering_rejected(config_factory, fake_services, fake_reader):
    manager = DataManager(config_factory(), services=fake_services, reader=fake_reader)
    raw = manager.acquire_forcings()
    result = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    payload = json.loads(result.manifest_path.read_text())
    payload["files"][0]["units"] = "not_real_units"
    result.manifest_path.write_text(json.dumps(payload))
    with pytest.raises(DataError, match="metadata"):
        manager.run_model_agnostic_preprocessing(raw.manifest_path)


def test_domain_store_cannot_be_silently_relabelled(config_factory, fake_services, fake_reader):
    cfg = config_factory()
    raw = DataManager(cfg, services=fake_services).acquire_forcings()
    cfg = cfg.model_copy(update={"domain_id": "another_basin"})
    with pytest.raises(DataError, match="domain/request"):
        DataManager(cfg, reader=fake_reader).run_model_agnostic_preprocessing(raw.manifest_path)


def test_canonical_provenance_persisted_in_netcdf(config_factory, fake_services, fake_reader):
    import xarray as xr

    cfg = config_factory()
    manager = DataManager(cfg, services=fake_services, reader=fake_reader)
    raw = manager.acquire_forcings()
    result = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    with xr.open_dataset(result.files[0], engine="scipy", decode_timedelta=False) as ds:
        assert ds.attrs["domain_id"] == cfg.domain_id
        assert ds.attrs["request_sha256"] == manager.plan().request_sha256
        assert len(ds.attrs["raw_manifest_sha256"]) == 64
