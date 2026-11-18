"""Create reusable EASYMORE polygon-overlap weights for a forecast grid."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import xarray as xr

from ._shared import (
    case_name,
    config_value,
    forcing_variables,
    new_easymore,
    setup_engine,
    wgs84_polygons,
)


class RemappingWeightGenerator:
    """Prepare weights once per grid/HRU identity, as controlled by the caller."""

    def __init__(self, config, project_dir, dataset_handler, logger=None):
        self.config = config
        self.project_dir = Path(project_dir)
        self.dataset_handler = dataset_handler
        self.logger = logger or logging.getLogger(__name__)
        self.cached_target_shp_wgs84: Path | None = None
        self.cached_hru_field: str | None = None

    def create_weights(
        self,
        sample_forcing_file: Path,
        intersect_path: Path,
        source_shp_path: Path,
        target_shp_path: Path,
    ) -> Path:
        """Return a new CSV; never trust pre-existing unversioned weights."""
        sample = Path(sample_forcing_file)
        output_dir = Path(intersect_path)
        source = Path(source_shp_path)
        target = Path(target_shp_path)
        field = config_value(self.config, "paths", "catchment_hruid")
        latitude, longitude = self.dataset_handler.get_coordinate_names()
        names = forcing_variables(sample, latitude, longitude)
        wgs84_polygons(source)
        wgs84_polygons(target, id_field=field)

        label = case_name(self.config)
        weight = output_dir / f"{label}_{field}_remapping.csv"
        if weight.exists() or weight.with_suffix(".nc").exists():
            raise FileExistsError(f"Unverified weights already exist: {weight}")
        output_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory(prefix="fc-weights-", dir=self.project_dir) as directory:
            work = Path(directory)
            engine = new_easymore()
            setup_engine(engine, label, work)
            engine.source_shp = str(source)
            engine.source_shp_lat = config_value(self.config, "forcing", "shape_lat_name")
            engine.source_shp_lon = config_value(self.config, "forcing", "shape_lon_name")
            engine.source_shp_ID = config_value(self.config, "forcing", "shape_id_name")
            engine.target_shp = str(target)
            engine.target_shp_ID = field
            engine.target_shp_lat = config_value(self.config, "paths", "catchment_lat")
            engine.target_shp_lon = config_value(self.config, "paths", "catchment_lon")
            engine.source_nc = str(sample)
            engine.var_names = names
            engine.var_lat, engine.var_lon, engine.var_time = latitude, longitude, "time"

            # EASYMORE needs source spacing for some small regular grids.
            with xr.open_dataset(sample) as ds:
                if min(ds.sizes[latitude], ds.sizes[longitude]) <= 2:
                    lat = np.asarray(ds[latitude].values, dtype=float)
                    lon = np.asarray(ds[longitude].values, dtype=float)
                    if min(len(lat), len(lon)) < 2:
                        raise ValueError("At least two grid centres per direction are required")
                    engine.source_nc_resolution = max(
                        abs(float(lat[1] - lat[0])), abs(float(lon[1] - lon[0]))
                    )

            engine.only_create_remap_csv = True
            if hasattr(engine, "only_create_remap_nc"):
                engine.only_create_remap_nc = True
            engine.save_csv = True
            engine.save_temp_shp = True
            engine.nc_remapper()

            generated_csv = work / f"{label}_remapping.csv"
            generated_nc = work / f"{label}_remapping.nc"
            if not generated_csv.is_file() or not generated_nc.is_file():
                raise FileNotFoundError("EASYMORE must produce CSV and NetCDF weight files")
            generated_csv.replace(weight)
            generated_nc.replace(weight.with_suffix(".nc"))
            attributes = work / f"{label}_attributes.nc"
            if attributes.is_file():
                attributes.replace(output_dir / attributes.name)

        self.cached_target_shp_wgs84 = target
        self.cached_hru_field = field
        self.logger.debug("Created forecast weight files: %s", weight)
        return weight
