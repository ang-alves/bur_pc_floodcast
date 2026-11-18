"""Integrity checks and transactional publication for forecast artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from floodcast.data.errors import DataError


def json_bytes(value) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reject_links(path: Path) -> None:
    """Reject symlinks/junctions in paths controlled by the forecast store."""
    item = Path(path)
    for ancestor in (item, *item.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise DataError("LINKED_PATH", f"Linked forecast-store path: {ancestor}")


def safe_file(root: Path, relative: str) -> Path:
    """Resolve a manifest path confined to an unlinked store root."""
    if not relative or "\\" in relative or ":" in relative:
        raise DataError("UNSAFE_PATH", "Invalid manifest relative path")
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts or part == Path("."):
        raise DataError("UNSAFE_PATH", "Manifest path escapes forecast store")
    root = Path(root)
    path = root / part
    reject_links(path)
    if not path.resolve().is_relative_to(root.resolve()):
        raise DataError("UNSAFE_PATH", "Manifest path escapes forecast store")
    return path


def atomic_json(path: Path, value) -> None:
    """Publish a complete canonical JSON payload with an atomic replacement."""
    path = Path(path)
    reject_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with staged.open("xb") as stream:
            stream.write(json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def verify_file(root: Path, record) -> Path:
    path = safe_file(root, record.relative_path)
    if not path.is_file() or path.stat().st_size != record.size:
        raise DataError("INTEGRITY_MISMATCH", f"Forecast asset integrity mismatch: {record.relative_path}")
    if file_sha256(path) != record.sha256:
        raise DataError("INTEGRITY_MISMATCH", f"Forecast asset integrity checksum mismatch: {record.relative_path}")
    return path


def write_netcdf_atomic(dataset, target: Path) -> None:
    """Commit a complete NetCDF3 file without overwriting a published one.

    The readback checks structure, not scientific CF or meteorological validity.
    """
    import xarray as xr

    target = Path(target)
    reject_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Canonical NetCDF already exists: {target}")

    staged = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    epoch = "seconds since 1970-01-01 00:00:00"
    encoding = {
        name: {"units": epoch, "calendar": "proleptic_gregorian", "dtype": "float64"}
        for name in ("forecast_reference_time", "valid_time", "valid_time_bounds")
        if name in dataset
    }
    try:
        dataset.to_netcdf(staged, engine="scipy", encoding=encoding)
        with xr.open_dataset(staged, engine="scipy", decode_timedelta=False) as check:
            if dict(check.sizes) != dict(dataset.sizes) or set(check.data_vars) != set(dataset.data_vars):
                raise ValueError("NetCDF output does not match the canonical dataset structure")
        # A hard link atomically reserves the final name without replacing existing data.
        os.link(staged, target)
    finally:
        staged.unlink(missing_ok=True)
