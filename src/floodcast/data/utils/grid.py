"""Reconstruct regular ECMWF grids without interpolating or replicating HRUs."""

from __future__ import annotations

import numpy as np

from floodcast.data.errors import DataError


def regular_grid(message, bbox=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return increasing latitude, longitude and a matching 2-D data array."""
    lat = np.asarray(message.latitude, dtype=float).ravel()
    lon = np.asarray(message.longitude, dtype=float).ravel()
    values = np.asarray(message.values, dtype=float).ravel()

    if not values.size or lat.size != values.size or lon.size != values.size:
        raise DataError("INVALID_GRID", "GRIB coordinates and values do not align")
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()) or (np.abs(lat) > 90).any():
        raise DataError("INVALID_GRID", "Invalid geographic coordinates")

    lon = (lon + 180.0) % 360.0 - 180.0
    y, x = np.unique(lat), np.unique(lon)
    if y.size * x.size != values.size:
        raise DataError("INVALID_GRID", "Expected a complete regular grid")

    rows = np.searchsorted(y, lat)
    columns = np.searchsorted(x, lon)
    flat = rows * x.size + columns
    if np.unique(flat).size != flat.size:
        raise DataError("INVALID_GRID", "Repeated latitude-longitude pair")

    grid = np.empty((y.size, x.size), dtype=float)
    grid[rows, columns] = values

    if bbox is not None:
        ymin = (y >= bbox.south) & (y <= bbox.north)
        if bbox.west < bbox.east:
            xmin = (x >= bbox.west) & (x <= bbox.east)
        else:
            xmin = (x >= bbox.west) | (x <= bbox.east)
        if not (ymin.any() and xmin.any()):
            raise DataError("EMPTY_SUBSET", "Bounding box excludes all cell centres")
        y, x, grid = y[ymin], x[xmin], grid[np.ix_(ymin, xmin)]

    if not np.isfinite(grid).all():
        raise DataError("MISSING_VALUES", "Spatial subset contains non-finite values")
    return y, x, grid
