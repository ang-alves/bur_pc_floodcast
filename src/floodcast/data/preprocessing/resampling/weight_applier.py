"""Apply validated EASYMORE weights to one canonical forecast member."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from ._shared import (
    case_name,
    config_value,
    forcing_variables,
    new_easymore,
    setup_engine,
    validate_remapped,
    wgs84_polygons,
)


class RemappingWeightApplier:
    """Apply weights once; reuse decisions belong to the forecast manifest."""

    def __init__(self, config, project_dir, output_dir, dataset_handler, logger=None):
        self.config = config
        self.project_dir = Path(project_dir)
        self.output_dir = Path(output_dir)
        self.dataset_handler = dataset_handler
        self.logger = logger or logging.getLogger(__name__)
        self.target_shp: Path | None = None
        self.hru_field: str | None = None

    def set_shapefile_cache(self, target_shp_wgs84: Path, hru_field: str) -> None:
        wgs84_polygons(target_shp_wgs84, id_field=hru_field)
        self.target_shp = Path(target_shp_wgs84)
        self.hru_field = hru_field

    def apply_weights(
        self,
        file: Path,
        remap_file: Path,
        output_file: Path,
        worker_id: int | None = None,
    ) -> bool:
        """Produce an isolated validated NetCDF file, or report failure."""
        source, weights, output = Path(file), Path(remap_file), Path(output_file)
        try:
            if output.exists():
                raise FileExistsError(f"Unverified remapping output already exists: {output}")
            if self.target_shp is None or self.hru_field is None:
                raise ValueError("Target HRU geometry must be configured before remapping")
            if not weights.is_file() or not weights.with_suffix(".nc").is_file():
                raise FileNotFoundError("The weight cache requires CSV and NetCDF weights")
            latitude, longitude = self.dataset_handler.get_coordinate_names()
            names = forcing_variables(source, latitude, longitude)
            self.project_dir.mkdir(parents=True, exist_ok=True)

            with TemporaryDirectory(prefix="fc-apply-", dir=self.project_dir) as directory:
                work = Path(directory)
                label = case_name(self.config)
                engine = new_easymore()
                setup_engine(engine, label, work)
                engine.target_shp = str(self.target_shp)
                engine.target_shp_ID = self.hru_field
                engine.target_shp_lat = config_value(self.config, "paths", "catchment_lat")
                engine.target_shp_lon = config_value(self.config, "paths", "catchment_lon")
                engine.source_nc = str(source)
                engine.var_names = names
                engine.var_lat, engine.var_lon, engine.var_time = latitude, longitude, "time"
                engine.remap_csv = str(weights)
                engine.remap_nc = str(weights.with_suffix(".nc"))
                attributes = weights.parent / f"{label}_attributes.nc"
                if attributes.is_file():
                    engine.attr_nc = str(attributes)
                engine.save_csv = False
                engine.save_temp_shp = False
                engine.nc_remapper()

                # An ambiguous output is an error, not a reason to select a
                # plausible file by its name or size.
                remapped = [
                    path for path in work.glob("*.nc")
                    if not any(token in path.name.lower() for token in
                               ("remapping", "attributes", "metadata", "static", "params"))
                ]
                if len(remapped) != 1:
                    raise ValueError(f"Expected one remapped file, got {len(remapped)}")
                validate_remapped(remapped[0], names)
                output.parent.mkdir(parents=True, exist_ok=True)
                remapped[0].replace(output)
            return True
        except Exception:
            self.logger.exception("Forecast remapping failed for %s", source)
            return False
