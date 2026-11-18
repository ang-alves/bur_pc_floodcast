
"""Explicit temporal alignment with interval-integral conservation.

Forecast accumulations have already been decoded into interval mean rates.
This module never infers their duration from the target model timestep.
"""

from __future__ import annotations

import numpy as np

from ..errors import DataError


def target_intervals(settings):
    """Return integer seconds from initialization for an exact requested window."""
    start = settings.start_lead_hour * 3600
    end = settings.end_lead_hour * 3600
    count = (end - start) // settings.timestep_seconds
    if count > 1_000_000:
        raise DataError("RESOURCE_LIMIT", "Too many target forcing intervals")
    starts = np.arange(start, end, settings.timestep_seconds, dtype=np.int64)
    return np.column_stack((starts, starts + settings.timestep_seconds))


def interval_weights(source_bounds, target_bounds, *, policy="conservative"):
    """Build target×source weights preserving precipitation/energy integrals.

    Conservative aggregation accepts whole native intervals. Uniform subdivision
    is permitted only by an explicit policy and is recorded by the caller.
    Missing support, overlapping intervals and extrapolation always fail.
    """
    source = np.asarray(source_bounds, dtype=np.int64)
    target = np.asarray(target_bounds, dtype=np.int64)
    if policy not in {"conservative", "uniform"}:
        raise DataError("INVALID_TEMPORAL_POLICY", "Unknown interval policy")
    for bounds in (source, target):
        if bounds.ndim != 2 or bounds.shape[1] != 2 or not len(bounds):
            raise DataError("INVALID_INTERVAL", "Expected nonempty interval bounds")
        if np.any(bounds[:, 1] <= bounds[:, 0]):
            raise DataError("INVALID_INTERVAL", "Intervals require positive duration")
        if np.any(bounds[1:, 0] < bounds[:-1, 1]):
            raise DataError("INVALID_INTERVAL", "Intervals overlap or are out of order")
    overlap = np.maximum(
        0,
        np.minimum(target[:, None, 1], source[None, :, 1])
        - np.maximum(target[:, None, 0], source[None, :, 0]),
    )
    duration = target[:, 1] - target[:, 0]
    if not np.array_equal(overlap.sum(axis=1), duration):
        raise DataError("TEMPORAL_COVERAGE", "Native intervals do not cover the target window")
    partial = (overlap > 0) & (overlap != source[None, :, 1] - source[None, :, 0])
    if policy == "conservative" and partial.any():
        raise DataError(
            "TEMPORAL_DISAGGREGATION_REQUIRED",
            "A target interval splits a native interval; select uniform explicitly or coarsen it",
        )
    return overlap / duration[:, None]


def instantaneous_weights(source_seconds, target_seconds, *, policy="exact"):
    """Evaluate states at interval starts; never extrapolate or forward-fill."""
    source = np.asarray(source_seconds, dtype=np.int64)
    target = np.asarray(target_seconds, dtype=np.int64)
    if source.ndim != 1 or not len(source) or np.any(np.diff(source) <= 0):
        raise DataError("INVALID_TIME_AXIS", "State times must be unique and increasing")
    if target.ndim != 1 or np.any(target < source[0]) or np.any(target > source[-1]):
        raise DataError("TEMPORAL_COVERAGE", "Instantaneous data would require extrapolation")
    if policy not in {"exact", "linear"}:
        raise DataError("INVALID_TEMPORAL_POLICY", "Unknown instantaneous policy")
    matrix = np.zeros((len(target), len(source)), dtype=np.float64)
    for row, value in enumerate(target):
        index = int(np.searchsorted(source, value))
        if source[index] == value:
            matrix[row, index] = 1.0
        elif policy == "exact":
            raise DataError(
                "TEMPORAL_INTERPOLATION_REQUIRED",
                "No instantaneous value at a target interval start",
            )
        else:
            weight = (value - source[index - 1]) / (source[index] - source[index - 1])
            matrix[row, index - 1] = 1.0 - weight
            matrix[row, index] = weight
    return matrix


def align_variable(dataset, name, settings, cycle, *, max_working_bytes=1073741824):
    """Return member×target-time×HRU, retaining each field's native support."""
    array = dataset[name]
    if set(array.dims) != {"member", "lead_time", "hru"}:
        raise DataError("DIMENSION_MISMATCH", f"Unexpected dimensions for {name}")
    targets = target_intervals(settings)
    footprint = 8 * len(targets) * (
        array.sizes["lead_time"] + array.sizes["member"] * array.sizes["hru"]
    ) + array.nbytes
    if footprint * 3 > max_working_bytes:
        raise DataError("RESOURCE_LIMIT", "Temporal alignment exceeds working memory budget")
    values = array.transpose("member", "lead_time", "hru").values
    if not np.isfinite(values).all():
        raise DataError("NONFINITE_FORCING", f"Nonfinite remapped values in {name}")
    origin = np.datetime64(cycle.replace(tzinfo=None), "ns")
    times = np.asarray(dataset.valid_time.values, dtype="datetime64[ns]")
    if np.isnat(times).any():
        raise DataError("INVALID_TIME_AXIS", "NaT in forecast valid times")
    source_seconds = (times - origin).astype("timedelta64[s]").astype(np.int64)
    bounds = np.asarray(dataset.valid_time_bounds.values, dtype="datetime64[ns]")
    if np.isnat(bounds).any():
        raise DataError("INVALID_INTERVAL", "NaT in forecast time bounds")
    seconds = (bounds - origin).astype("timedelta64[s]").astype(np.int64)
    semantics = array.attrs.get("temporal_semantics")
    if semantics == "instant":
        if not np.array_equal(seconds, np.column_stack((source_seconds, source_seconds))):
            raise DataError("INVALID_INTERVAL", "Instantaneous field has interval mean bounds")
        matrix = instantaneous_weights(
            source_seconds, targets[:, 0], policy=settings.instant_policy
        )
    elif semantics == "interval_mean_from_accumulation":
        matrix = interval_weights(seconds, targets, policy=settings.interval_policy)
    else:
        raise DataError(
            "TEMPORAL_SEMANTICS",
            f"{name}: {semantics!r} cannot be converted to SUMMA instantaneous state values",
        )
    return np.einsum("ts,msh->mth", matrix, values, optimize=True)
