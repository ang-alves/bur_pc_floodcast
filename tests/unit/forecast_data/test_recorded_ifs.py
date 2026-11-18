"""Replay a small, attributed subset of an actually retrieved IFS forecast."""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from floodcast.data.config import DataConfig, ForecastConfig
from floodcast.data.data_manager import DataManager

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "ecmwf" / "ifs_20261117T00Z"


def test_recorded_provider_grib_reproduces_live_canonical_values(tmp_path):
    pytest.importorskip("eccodes")
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    assets = {asset["part_id"]: asset for asset in provenance["assets"]}
    parts = {part["part_id"]: part for part in provenance["parts"]}
    assert provenance["original_download_bytes"] == 20_102_931
    assert sum(len(asset["messages"]) for asset in assets.values()) == 42

    class RecordedTransport:
        calls = 0

        def retrieve(self, part, config, target):
            # Only transport is substituted; production ecCodes parsing,
            # validation, normalization, file publication and caching all run.
            assert part.model_dump(mode="json") == parts[part.part_id]
            asset = assets[part.part_id]
            source = FIXTURE / asset["file"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == asset["sha256"]
            shutil.copyfile(source, target)
            self.calls += 1

    service = RecordedTransport()
    config = DataConfig(
        domain_id="recorded_ifs",
        data_root=tmp_path,
        forecast=ForecastConfig.model_validate(provenance["forecast"]),
    )
    manager = DataManager(config, services=service)
    raw = manager.acquire_forcings()
    canonical = manager.run_model_agnostic_preprocessing(raw.manifest_path)
    assert service.calls == 16
    assert len(canonical.files) == 8
    for field, expected in provenance["expected_canonical"].items():
        with xr.open_dataset(
            canonical.manifest_path.parent / f"{field}.nc", decode_timedelta=False
        ) as ds:
            variable = ds[expected["name"]]
            assert list(variable.shape) == expected["shape"]
            assert variable.attrs["units"] == expected["units"]
            assert (
                hashlib.sha256(variable.values.astype("<f8").tobytes()).hexdigest()
                == expected["values_sha256"]
            )
            bounds = ds.valid_time_bounds.values.astype("datetime64[ns]").astype("<i8")
            assert (
                hashlib.sha256(bounds.tobytes()).hexdigest() == expected["valid_time_bounds_sha256"]
            )
            np.testing.assert_array_equal(ds.member, [0, 1])
            assert ds.attrs["ifs_cycle"] == "50r1"
    assert manager.acquire_forcings() == raw
    assert manager.run_model_agnostic_preprocessing(raw.manifest_path) == canonical
    assert service.calls == 16
