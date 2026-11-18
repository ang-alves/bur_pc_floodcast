"""Validate native ECMWF field units before canonical interval processing."""

from __future__ import annotations

import numpy as np

from floodcast.data.catalog import S2S
from floodcast.data.errors import DataError


_NATIVE_UNITS = {
    "2t": {"k"},
    "2d": {"k"},
    "10u": {"ms-1", "m/s"},
    "10v": {"ms-1", "m/s"},
    "sp": {"pa"},
    "msl": {"pa"},
    "ssrd": {"jm-2", "j/m2", "wm-2s"},
    "strd": {"jm-2", "j/m2", "wm-2s"},
}


def to_base_values(field: str, message, product: str) -> np.ndarray:
    """Return field values in their defined pre-temporal-normalization units.

    Precipitation is expressed in kg m-2 of interval water equivalent.
    Radiation remains accumulated energy in J m-2. This is NOT the
    canonical CFIF flux yet; interval semantics are handled downstream.
    """
    raw_unit = str(message.units).replace("**", "").replace("^", "")
    unit = "".join(raw_unit.lower().split())
    values = np.asarray(message.values, dtype=np.float64)

    if field == "tp":
        expected = {"kgm-2", "kg/m2"} if product == S2S else {"m", "mofwaterequivalent"}
        if unit not in expected:
            raise DataError("UNITS_MISMATCH", f"Unexpected {product} precipitation units: {message.units}")
        return values if product == S2S else values * 1000.0

    expected = _NATIVE_UNITS.get(field)
    if expected is None:
        raise DataError("UNEXPECTED_VARIABLE", f"Unknown meteorological field: {field}")
    if unit not in expected:
        raise DataError("UNITS_MISMATCH", f"Unexpected units for {field}: {message.units}")
    return values
