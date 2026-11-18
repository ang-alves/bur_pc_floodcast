"""S2S/CDS product integration through real GRIB decoding and GIS remapping."""

import numpy as np
import pytest
from unit.forecast_data.test_native_grib import native_grib as native_grib

from floodcast.data.catalog import S2S, SEASONAL, variables
from floodcast.data.config import ModelForcingConfig, RemappingConfig
from floodcast.data.contracts import CanonicalManifest
from floodcast.data.data_manager import DataManager
from floodcast.data.errors import DataError
from floodcast.data.model_ready.temporal import align_variable
from floodcast.data.preprocessing.forcing_resampler import ForcingResampler
from floodcast.data.preprocessing.remapping_contracts import RemappedManifest


@pytest.mark.parametrize("product,members", [(S2S, (0, 2)), (SEASONAL, (2, 7))])
def test_store_product_native_grib_to_hru_preserves_support(
    config_factory,
    native_grib,
    product,
    members,
    tmp_path,
):
    ec = pytest.importorskip("eccodes")
    gpd = pytest.importorskip("geopandas")
    xr = pytest.importorskip("xarray")
    pytest.importorskip("easymore")
    from shapely.geometry import box

    target = tmp_path / "store_hrus.gpkg"
    gpd.GeoDataFrame(
        {"hruId": [11, 37]},
        geometry=[box(-9.4, 38.6, -8.6, 39.4), box(-9.4, 39.6, -7.6, 40.4)],
        crs="EPSG:4326",
    ).to_file(target)
    settings = ModelForcingConfig(timestep_seconds=86400, start_lead_hour=0, end_lead_hour=48)
    config = config_factory(
        product,
        members=members,
        fields={"tp": (24, 48), "2t": (24, 48), "ssrd": (24, 48)},
    ).model_copy(
        update={
            "remapping": RemappingConfig(
                target_path=target, geometry_version="synthetic-store-v1", expected_hru_ids=(11, 37)
            ),
            "model_forcing": settings,
        }
    )

    class NativeGRIBTransport:
        """Only the network is replaced; bytes are real ecCodes GRIB messages."""

        calls = 0

        def retrieve(self, part, forecast, destination):
            self.calls += 1
            field = next(
                key
                for key, value in variables(product).items()
                if value.api_name == part.payload["variable"][0]
            )
            chosen = [0] if part.role == "control" else [m for m in members if m > 0]
            # Store products can return unselected ensemble members. The
            # processing path must select native IDs, not renumber them.
            if part.role != "control":
                chosen = [*chosen, 9]
            messages = []
            for member in chosen:
                for lead in map(int, part.payload["leadtime_hour"]):
                    path = native_grib(forecast, field, member, lead)
                    with path.open("rb") as stream:
                        handle = ec.codes_grib_new_from_file(stream)
                    try:
                        if field == "tp":
                            amount = lead * (member + 1)
                            value = amount if product == S2S else amount / 1000
                        elif field == "ssrd":
                            value = lead * 3600 * 100
                        else:
                            value = 270 + member + lead / 24
                        ec.codes_set_values(handle, np.full(4, value))
                        messages.append(ec.codes_get_message(handle))
                    finally:
                        ec.codes_release(handle)
            destination.write_bytes(b"".join(messages))

    transport = NativeGRIBTransport()
    manager = DataManager(config, services=transport)
    raw = manager.acquire_forcings()
    canonical = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    mapped = manager.remap_forcings(canonical.manifest_path)
    original = CanonicalManifest.model_validate_json(canonical.manifest_path.read_bytes())
    result = RemappedManifest.model_validate_json(mapped.manifest_path.read_bytes())
    assert original.selected_members == members
    assert original.observed_members == tuple(sorted((*members, 9)))
    assert result.selected_members == members
    assert result.system == ("51" if product == SEASONAL else None)
    assert result.hru_ids == (11, 37) and not result.model_ready
    origin = np.datetime64(config.forecast.cycle.replace(tzinfo=None), "ns")
    expected_bounds = origin + np.asarray([[0, 24], [24, 48]]).astype("timedelta64[h]")
    with xr.open_dataset(mapped.manifest_path.parent / "tp.nc", decode_timedelta=False) as rain:
        np.testing.assert_array_equal(rain.member, members)
        np.testing.assert_array_equal(rain.valid_time_bounds, expected_bounds)
        expected = np.asarray(members) + 1
        np.testing.assert_allclose(
            rain.precipitation_flux.sum("lead_time") * 86400,
            np.broadcast_to((48 * expected)[:, None], (len(members), 2)),
            rtol=2e-6,
        )
    with xr.open_dataset(
        mapped.manifest_path.parent / "ssrd.nc", decode_timedelta=False
    ) as radiation:
        np.testing.assert_array_equal(radiation.valid_time_bounds, expected_bounds)
        np.testing.assert_allclose(
            radiation.surface_downwelling_shortwave_flux_in_air, 100, rtol=1e-6
        )
    with xr.open_dataset(
        mapped.manifest_path.parent / "2t.nc", decode_timedelta=False
    ) as temperature:
        np.testing.assert_array_equal(temperature.member, members)
        if product == S2S:
            assert temperature.air_temperature.attrs["temporal_semantics"] == "avg"
            np.testing.assert_array_equal(temperature.valid_time_bounds, expected_bounds)
            with pytest.raises(DataError) as error:
                align_variable(temperature, "air_temperature", settings, config.forecast.cycle)
            assert error.value.code == "TEMPORAL_SEMANTICS"
        else:
            assert temperature.air_temperature.attrs["temporal_semantics"] == "instant"
            np.testing.assert_array_equal(
                temperature.valid_time_bounds[:, 0], temperature.valid_time_bounds[:, 1]
            )
            assert temperature.member_role.values.tolist() == ["ensemble", "ensemble"]
    calls_before = transport.calls

    # Verification is read-only, including when the remote transports would fail.
    def fail(*args, **kwargs):
        raise AssertionError("Read-only verification attempted retrieval")

    transport.retrieve = fail
    assert (
        ForcingResampler(manager.config, registries=manager.R).verify(mapped.manifest_path)
        == mapped
    )
    assert transport.calls == calls_before
    with pytest.raises(DataError) as error:
        manager.prepare_model_forcings(mapped.manifest_path)
    assert error.value.code == "MISSING_FORCING_INPUT"
    assert "sp" in str(error.value)
