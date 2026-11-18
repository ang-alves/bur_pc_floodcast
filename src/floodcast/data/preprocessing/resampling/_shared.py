"""Input contracts shared by the Floodcast EASYMORE boundary.

No implicit unit conversion, longitude shifting, point extraction or HRU
renumbering is permitted. The caller supplies canonical forecast data and
validated domain polygons.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import xarray as xr

from ...catalog import PRODUCTS, variables
from ..cfif.variables import CFIF_VARIABLES


def config_value(config: Any, section: str, name: str) -> str:
    group = getattr(config, section, None)
    value = getattr(group, name, None)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Remapping requires {section}.{name} as a nonempty string")
    return value


def case_name(config: Any) -> str:
    domain = config_value(config, "domain", "name")
    product = config_value(config, "forcing", "dataset")
    for part in (domain, product):
        if not all(c.isalnum() or c in "-_" for c in part):
            raise ValueError("Remapping domain and dataset require safe identifiers")
    return f"{domain}_{product}"


def canonical_units() -> dict[str, str]:
    result = {name: spec["units"] for name, spec in CFIF_VARIABLES.items()}
    for product in PRODUCTS:
        for spec in variables(product).values():
            previous = result.setdefault(spec.canonical_name, spec.units)
            if previous != spec.units:
                raise ValueError(f"Inconsistent canonical units for {spec.canonical_name}")
    return result


def forcing_variables(file: Path, latitude: str, longitude: str) -> list[str]:
    """Require complete, finite CFIF fields on a 1D geographic grid."""
    known = canonical_units()
    with xr.open_dataset(file) as ds:
        names = list(ds.data_vars)
        if not names or any(name not in known for name in names):
            raise ValueError(f"Noncanonical forcing variables in {file}: {names}")
        if not all(axis in ds.dims for axis in ("time", latitude, longitude)):
            raise ValueError("Input forcing requires time and geographic dimensions")
        if any(ds.sizes[axis] < 1 for axis in ("time", latitude, longitude)):
            raise ValueError("Empty forcing dimension")
        for axis in (latitude, longitude):
            coordinate = np.asarray(ds[axis].values, dtype=float)
            if (
                coordinate.ndim != 1
                or coordinate.size < 2
                or not np.isfinite(coordinate).all()
                or not np.all(np.diff(coordinate) > 0)
            ):
                raise ValueError(f"{axis} needs at least two increasing finite centres")
        times = ds["time"].values
        if len(np.unique(times)) != len(times) or (
            len(times) > 1 and not np.all(times[1:] > times[:-1])
        ):
            raise ValueError("Forcing timestamps must be unique and increasing")
        for name in names:
            field = ds[name]
            if field.attrs.get("units") != known[name]:
                raise ValueError(f"{name}: expected canonical units {known[name]!r}")
            if set(field.dims) != {"time", latitude, longitude}:
                raise ValueError(f"{name}: expected time, {latitude}, {longitude} dimensions")
            if not np.isfinite(field.values).all():
                raise ValueError(f"{name}: missing or nonfinite data")
        return names


def wgs84_polygons(path: Path, *, id_field: str | None = None) -> None:
    """Check staged polygons without changing the authoritative geometry."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe geometry: {path}")
    frame = gpd.read_file(path)
    if frame.empty or frame.crs is None or frame.crs.to_epsg() != 4326:
        raise ValueError(f"Geometry must be nonempty EPSG:4326 polygons: {path}")
    shape = frame.geometry
    if (
        shape.isna().any()
        or shape.is_empty.any()
        or not shape.is_valid.all()
        or not shape.geom_type.isin(("Polygon", "MultiPolygon")).all()
        or frame.total_bounds[0] < -180
        or frame.total_bounds[2] > 180
    ):
        raise ValueError(f"Invalid polygons or -180..180 longitudes: {path}")
    if id_field is not None:
        if id_field not in frame:
            raise ValueError(f"Missing target HRU ID field: {id_field}")
        ids = frame[id_field]
        if (
            not np.issubdtype(ids.dtype, np.integer)
            or ids.isna().any()
            or (ids <= 0).any()
            or ids.duplicated().any()
        ):
            raise ValueError("HRU IDs must be unique positive integers")


def validate_remapped(path: Path, expected: list[str]) -> None:
    """Check every requested variable and output axis before publication."""
    with xr.open_dataset(path) as ds:
        if ds.sizes.get("time", 0) < 1 or ds.sizes.get("hru", 0) < 1:
            raise ValueError("Remapped forcing needs nonempty time and hru dimensions")
        if "hruId" not in ds:
            raise ValueError("Remapped forcing is missing hruId")
        ids = np.asarray(ds.hruId.values)
        if (
            ids.ndim != 1
            or len(ids) != ds.sizes["hru"]
            or not np.issubdtype(ids.dtype, np.integer)
            or (ids <= 0).any()
            or len(np.unique(ids)) != len(ids)
        ):
            raise ValueError("Remapped forcing contains invalid HRU IDs")
        times = np.asarray(ds.time.values)
        if len(np.unique(times)) != len(times) or (
            len(times) > 1 and not np.all(times[1:] > times[:-1])
        ):
            raise ValueError("Remapped forcing timestamps are not increasing and unique")
        for name in expected:
            if name not in ds.data_vars:
                raise ValueError(f"Remapped forcing is missing variable {name}")
            field = ds[name]
            if set(field.dims) != {"time", "hru"} or not np.isfinite(field.values).all():
                raise ValueError(f"Invalid remapped values or dimensions for {name}")


def new_easymore():
    try:
        import easymore
    except ImportError as exc:
        raise RuntimeError("EASYMORE is required for spatial remapping") from exc
    factory = getattr(easymore, "Easymore", None) or getattr(easymore, "easymore", None)
    if factory is None:
        raise RuntimeError("Installed EASYMORE exposes no supported constructor")
    return factory()


def setup_engine(engine: Any, case: str, workdir: Path) -> None:
    engine.case_name = case
    engine.author_name = "Floodcast"
    engine.correction_shp_lon = False
    engine.temp_dir = str(workdir) + "/"
    engine.output_dir = str(workdir) + "/"
    engine.remapped_dim_id = "hru"
    engine.remapped_var_id = "hruId"
    engine.sort_ID = False
    engine.format_list = ["f4"]
    engine.fill_value_list = ["-9999"]
    engine.numcpu = 1
