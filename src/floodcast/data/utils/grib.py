"""Bounded GRIB framing and ECMWF message decoding via ecCodes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from floodcast.data.ecmwf_profiles import REVIEWED_THROUGH
from floodcast.data.errors import DataError, DependencyUnavailable


_STEP_HOURS = {
    "0": 1 / 60, "m": 1 / 60,
    "1": 1.0, "h": 1.0,
    "2": 24.0, "D": 24.0,
    "10": 3.0, "3h": 3.0,
    "11": 6.0, "6h": 6.0,
    "12": 12.0, "12h": 12.0,
    "13": 1 / 3600, "s": 1 / 3600,
}


def count_grib_messages(path: Path) -> int:
    """Check concatenated GRIB framing; no claim of meteorological validity."""
    path = Path(path)
    size = path.stat().st_size
    offset = count = 0
    with path.open("rb") as stream:
        while offset < size:
            stream.seek(offset)
            header = stream.read(16)
            if len(header) < 8 or header[:4] != b"GRIB":
                raise DataError("INVALID_GRIB", "Missing GRIB header")
            edition = header[7]
            if edition == 1:
                length = int.from_bytes(header[4:7], "big")
                minimum = 12
            elif edition == 2:
                length = int.from_bytes(header[8:16], "big")
                minimum = 20
            else:
                raise DataError("INVALID_GRIB", f"Unsupported GRIB edition: {edition}")
            if length < minimum or offset + length > size:
                raise DataError("INVALID_GRIB", "Incomplete GRIB message")
            stream.seek(offset + length - 4)
            if stream.read(4) != b"7777":
                raise DataError("INVALID_GRIB", "Invalid GRIB message terminator")
            offset += length
            count += 1
    if count == 0:
        raise DataError("INVALID_GRIB", "Empty GRIB file")
    return count


@dataclass(frozen=True)
class FieldMessage:
    """Metadata and values for a single native ECMWF forecast field."""

    param_id: int
    units: str
    step_type: str
    start_hour: float
    end_hour: float
    cycle: datetime
    member: int
    role: str
    latitude: object
    longitude: object
    values: object
    source_path: str
    message_index: int
    centre: str = "ecmf"
    grid_type: str = "regular_ll"
    edition: int | None = None
    generating_process_identifier: int | None = None
    tables_version: int | None = None
    data_type: str | None = None
    stream: str | None = None
    seasonal_system: str | None = None
    type_of_level: str | None = None
    level: float | None = None


def _optional(ec, handle, name: str, convert=None):
    if not ec.codes_is_defined(handle, name):
        return None
    if hasattr(ec, "codes_is_missing") and ec.codes_is_missing(handle, name):
        return None
    value = ec.codes_get(handle, name)
    return convert(value) if convert else value


def _validate_source(ec, handle, part, config) -> tuple[str, str | None, str | None, int | None, str | None]:
    def get(name):
        return ec.codes_get(handle, name)

    if get("gridType") != "regular_ll":
        raise DataError("UNSUPPORTED_GRID", "Expected regular latitude-longitude GRIB")
    centre = str(get("centre"))
    if centre not in ("ecmf", "98"):
        raise DataError("CENTRE_MISMATCH", "GRIB field is not from ECMWF")

    data_type = _optional(ec, handle, "dataType", str)
    stream = _optional(ec, handle, "stream", str)
    process = _optional(ec, handle, "generatingProcessIdentifier", int)
    system = _optional(ec, handle, "systemNumber", str)
    if system is None:
        system = _optional(ec, handle, "system", str)

    if config.product == "ifs_medium_range":
        if data_type is not None and data_type != ("fc" if part.role == "control" else "pf"):
            raise DataError("PRODUCT_MISMATCH", "IFS forecast type differs from request")
        if stream is not None and stream != ("oper" if part.role == "control" else "enfo"):
            raise DataError("PRODUCT_MISMATCH", "IFS stream differs from request")
        if process != 161 and (process is not None or config.cycle > REVIEWED_THROUGH):
            raise DataError("MODEL_VERSION_MISMATCH", "IFS 50r1 process identifier is not 161")
    elif config.product == "s2s_ecds":
        if data_type is not None and data_type != ("cf" if part.role == "control" else "pf"):
            raise DataError("PRODUCT_MISMATCH", "S2S forecast type differs from request")
        if config.cycle > REVIEWED_THROUGH and process != 161:
            raise DataError("MODEL_VERSION_MISMATCH", "Unsupported S2S process identifier")
    elif config.product == "seasonal_ecmwf":
        if system is not None and system != config.system:
            raise DataError("SYSTEM_MISMATCH", "Seasonal system differs from request")
        if config.cycle > REVIEWED_THROUGH and system is None:
            raise DataError("SYSTEM_MISSING", "Seasonal system identifier is required")
    else:
        raise DataError("PRODUCT_MISMATCH", f"Unsupported forecast product: {config.product}")

    spacing = {"0p25": 0.25, "0p1": 0.1}.get(config.resolution)
    if spacing is None:
        spacing = 1.5 if config.product == "s2s_ecds" else 1.0
    for name in ("iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees"):
        if abs(float(get(name)) - spacing) > 1e-7:
            raise DataError("GRID_MISMATCH", "Unexpected horizontal forecast grid spacing")
    return centre, data_type, stream, process, system


class EcCodesReader:
    """Yield validated native GRIB messages; release each ecCodes handle."""

    def __init__(self, module=None):
        self.module = module

    def read(self, path: Path, part, config):
        ec = self.module
        if ec is None:
            try:
                import eccodes as ec
            except ImportError:
                raise DependencyUnavailable("eccodes (including its native library)") from None

        with Path(path).open("rb") as stream:
            index = 0
            while True:
                handle = ec.codes_grib_new_from_file(stream)
                if handle is None:
                    return
                try:
                    index += 1
                    if index > config.max_messages:
                        raise DataError("RESOURCE_LIMIT", "Maximum GRIB message count exceeded")

                    get = lambda key: ec.codes_get(handle, key)
                    centre, kind, source_stream, process, system = _validate_source(
                        ec, handle, part, config
                    )
                    count = int(get("numberOfPoints"))
                    if count <= 0 or count > config.max_grid_points or count * 32 > config.max_working_bytes:
                        raise DataError("RESOURCE_LIMIT", "Invalid or oversized GRIB grid")

                    values = np.asarray(ec.codes_get_values(handle), dtype=np.float64)
                    if values.ndim != 1 or values.size != count:
                        raise DataError("INVALID_GRIB", "Values do not match GRIB grid size")
                    if int(get("bitmapPresent")):
                        bitmap = np.asarray(ec.codes_get_array(handle, "bitmap"), dtype=bool)
                        if bitmap.shape != values.shape:
                            raise DataError("INVALID_GRIB", "Invalid GRIB missing-value bitmap")
                        values = np.where(bitmap, values, np.nan)
                    lat = np.asarray(ec.codes_get_array(handle, "latitudes"), dtype=np.float64)
                    lon = np.asarray(ec.codes_get_array(handle, "longitudes"), dtype=np.float64)
                    if lat.shape != values.shape or lon.shape != values.shape:
                        raise DataError("INVALID_GRIB", "GRIB coordinate/value length mismatch")

                    units = str(get("stepUnits"))
                    factor = _STEP_HOURS.get(units)
                    if factor is None:
                        raise DataError("UNSUPPORTED_TIME_UNIT", f"Unknown GRIB step units: {units}")
                    start = float(get("startStep")) * factor
                    end = float(get("endStep")) * factor
                    if start < 0 or end < start:
                        raise DataError("INVALID_INTERVAL", "Invalid GRIB step range")
                    stamp = f"{int(get('dataDate')):08d}{int(get('dataTime')):04d}"
                    cycle = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=UTC)

                    native_member = _optional(ec, handle, "number", int)
                    if part.role == "control":
                        if native_member not in (None, 0):
                            raise DataError("MEMBER_MISMATCH", "Control GRIB has a nonzero member")
                        member = 0
                    else:
                        if native_member is None:
                            raise DataError("MEMBER_MISSING", "Ensemble GRIB has no member number")
                        member = native_member
                        if member < 0 or (part.role == "perturbed" and member == 0):
                            raise DataError("MEMBER_MISMATCH", "Invalid native ensemble member")

                    yield FieldMessage(
                        param_id=int(get("paramId")), units=str(get("units")),
                        step_type=str(get("stepType")), start_hour=start, end_hour=end,
                        cycle=cycle, member=member, role=part.role,
                        latitude=lat, longitude=lon, values=values,
                        source_path=str(path), message_index=index,
                        centre=centre, grid_type=str(get("gridType")),
                        edition=_optional(ec, handle, "edition", int),
                        generating_process_identifier=process,
                        tables_version=_optional(ec, handle, "tablesVersion", int),
                        data_type=kind, stream=source_stream, seasonal_system=system,
                        type_of_level=_optional(ec, handle, "typeOfLevel", str),
                        level=_optional(ec, handle, "level", float),
                    )
                finally:
                    ec.codes_release(handle)
