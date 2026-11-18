"""Exercise actual geospatial remapping and NetCDF model-forcing publication."""

import json

import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import box

from floodcast.data.config import ModelForcingConfig, RemappingConfig
from floodcast.data.data_manager import DataManager
from floodcast.data.errors import DataError
from floodcast.data.model_ready.forcing_processor import ForcingManifest
from floodcast.data.model_ready.temporal import instantaneous_weights, interval_weights


def test_flux_integrals_survive_mixed_native_cadences():
    source = np.array([[0, 10800], [10800, 21600], [21600, 43200]])
    target = np.column_stack((np.arange(0, 43200, 3600), np.arange(3600, 43201, 3600)))
    matrix = interval_weights(source, target, policy="uniform")
    values = np.array([0.001, 0.002, 0.0005])
    assert np.sum(matrix @ values * 3600) == pytest.approx(np.sum(values * np.diff(source).ravel()))
    with pytest.raises(DataError, match="splits"):
        interval_weights(source, target)
    coarse = interval_weights(source, [[0, 21600], [21600, 43200]])
    np.testing.assert_allclose(coarse, [[0.5, 0.5, 0], [0, 0, 1]])


@pytest.mark.parametrize(
    "source,target",
    [
        ([[0, 3], [4, 6]], [[0, 6]]),
        ([[0, 3], [2, 6]], [[0, 6]]),
        ([[0, 3]], [[0, 6]]),
    ],
)
def test_missing_overlapping_or_short_support_fails(source, target):
    with pytest.raises(DataError):
        interval_weights(source, target, policy="uniform")


def test_instantaneous_alignment_never_extrapolates():
    np.testing.assert_allclose(
        instantaneous_weights([0, 3, 6], [0, 1, 2, 3, 6], policy="linear"),
        [[1, 0, 0], [2 / 3, 1 / 3, 0], [1 / 3, 2 / 3, 0], [0, 1, 0], [0, 0, 1]],
    )
    for target in ([-1], [7]):
        with pytest.raises(DataError, match="extrapolation"):
            instantaneous_weights([0, 3, 6], target, policy="linear")
    with pytest.raises(DataError, match="instantaneous"):
        instantaneous_weights([0, 3, 6], [1])


@pytest.fixture
def model_pipeline(config_factory, fake_services, fake_reader, message_factory, tmp_path):
    target = tmp_path / "synthetic_hrus.gpkg"
    gpd.GeoDataFrame(
        {"hruId": [41, 82]},
        geometry=[box(-9.4, 38.6, -8.6, 39.4), box(-9.4, 39.6, -7.6, 40.4)],
        crs="EPSG:4326",
    ).to_file(target, driver="GPKG")
    fields = {key: (0, 3, 6) for key in ("2t", "2d", "sp", "10u", "10v")}
    fields.update({key: (3, 6) for key in ("tp", "ssrd", "strd")})
    cfg = config_factory(fields=fields).model_copy(
        update={
            "remapping": RemappingConfig(
                target_path=target,
                geometry_version="synthetic-geometry-v1",
                expected_hru_ids=(41, 82),
            ),
            "model_forcing": ModelForcingConfig(
                timestep_seconds=3600,
                start_lead_hour=0,
                end_lead_hour=6,
                instant_policy="linear",
                interval_policy="uniform",
            ),
        }
    )

    class PhysicalReader:
        def read(self, path, part, config):
            for record in fake_reader.read(path, part, config):
                field = part.payload["param"][0]
                member, lead = record.member, record.end_hour
                values = {
                    "2t": np.array([282, 284, 283, 285]),
                    "2d": np.array([270, 280, 274, 278]),
                    "sp": np.full(4, 101325),
                    "10u": np.array([3, -3, 3, -3]) * (member + 1),
                    "10v": np.full(4, 4) * (member + 1),
                    "tp": np.full(4, lead * 0.001 * (member + 1)),
                    "ssrd": np.full(4, lead * 3600 * 200),
                    "strd": np.full(4, lead * 3600 * 300),
                }[field]
                yield message_factory(config, field, member, lead, values=values)

    manager = DataManager(cfg, services=fake_services, reader=PhysicalReader())
    raw = manager.acquire_forcings()
    canonical = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    mapped = manager.remap_forcings(canonical.manifest_path)
    return manager, mapped


def test_full_pipeline_reuses_native_remapping_and_summa_adapter(model_pipeline):
    manager, mapped = model_pipeline
    result = manager.prepare_model_forcings(mapped.manifest_path)
    saved = ForcingManifest.model_validate_json(result.manifest_path.read_bytes())
    assert saved.model_ready and saved.scientific_validation == "not_run"
    assert saved.selected_members == (0, 1)
    assert len(saved.files) == 4
    for member in (0, 1):
        target = result.manifest_path.parent / f"member-{member:04d}/forcing.nc"
        with xr.open_dataset(target) as dataset:
            assert set(
                (
                    "airtemp",
                    "pptrate",
                    "SWRadAtm",
                    "LWRadAtm",
                    "spechum",
                    "windspd",
                    "airpres",
                    "data_step",
                    "hruId",
                )
            ) <= set(dataset)
            np.testing.assert_array_equal(dataset.hruId, [41, 82])
            assert dataset.sizes["time"] == 6
            # Opposing winds in HRU 82 must not cancel before the magnitude is computed.
            np.testing.assert_allclose(dataset.windspd, 5 * (member + 1), atol=1e-5)
            np.testing.assert_allclose(dataset.pptrate.sum("time") * 3600, 6 * (member + 1))
            np.testing.assert_allclose(dataset.SWRadAtm, 200)
            np.testing.assert_allclose(dataset.LWRadAtm, 300)
            assert dataset.attrs["forcing_adapter"] == "SUMMAForcingAdapter"
            assert dataset.attrs["ensemble_member"] == member
            assert dataset.attrs["forcing_time_convention"] == "interval_start"
            assert ((dataset.spechum > 0) & (dataset.spechum < 0.05)).all()
    assert manager.prepare_model_forcings(mapped.manifest_path) == result


def test_model_publication_rejects_tampered_output(model_pipeline):
    manager, mapped = model_pipeline
    result = manager.prepare_model_forcings(mapped.manifest_path)
    result.files[0].write_bytes(b"damaged")
    with pytest.raises(DataError, match="integrity"):
        manager.prepare_model_forcings(mapped.manifest_path)


def test_missing_pressure_is_not_replaced_with_sea_level_pressure(config_factory):
    cfg = config_factory(product="seasonal_ecmwf", fields={"tp": (24,), "msl": (6,)})
    cfg = cfg.model_copy(
        update={
            "remapping": RemappingConfig(
                target_path=cfg.data_root / "does-not-exist.gpkg", geometry_version="v1"
            ),
            "model_forcing": ModelForcingConfig(
                timestep_seconds=3600, start_lead_hour=0, end_lead_hour=24
            ),
        }
    )
    with pytest.raises(DataError, match="sp"):
        DataManager(cfg).prepare_model_forcings(cfg.data_root / "missing.json")


def test_canonical_profile_tampering_is_not_accepted(
    config_factory,
    fake_services,
    fake_reader,
):
    manager = DataManager(config_factory(), services=fake_services, reader=fake_reader)
    raw = manager.acquire_forcings()
    canonical = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    payload = json.loads(canonical.manifest_path.read_bytes())
    payload["provenance"]["model"]["ifs_cycle"] = "49r1"
    canonical.manifest_path.write_text(json.dumps(payload))
    with pytest.raises(DataError, match="identity"):
        manager.run_model_agnostic_preprocessing(raw.manifest_path)
