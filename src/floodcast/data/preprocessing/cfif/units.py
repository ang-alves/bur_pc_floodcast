"""
Meteorological unit conversions for Floodcast.

Converts forecast variables to canonical SI units used by CFIF
and hydrological forcing adapters.

Canonical units
---------------
Temperature       K
Precipitation     kg m-2 s-1
Pressure          Pa
Radiation         W m-2
Specific humidity kg kg-1
Wind speed        m s-1

Forecast accumulations are handled separately from rate conversions.
A cumulative forecast field must first be converted into interval
amounts by the forecast preprocessing layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

import numpy as np

if TYPE_CHECKING:
    import xarray as xr


ArrayLike: TypeAlias = "np.ndarray | float | xr.DataArray"


class UnitConverter:
    """Convert meteorological fields to and from canonical units.

    Conversions are affine:

        canonical_value = input * scale + offset

    The inverse transformation is applied for the target units.

    This class does not interpret GRIB step ranges or accumulation
    resets. Those belong to forecast preprocessing.
    """

    # Each unit maps to (scale, offset) relative to its SI base.
    UNIT_TABLES: dict[str, dict[str, tuple[float, float]]] = {
        "temperature": {
            "K": (1.0, 0.0),
            "degC": (1.0, 273.15),
            "degF": (5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
        },
        "precipitation": {
            "kg m-2 s-1": (1.0, 0.0),
            "mm/s": (1.0, 0.0),
            "mm/hr": (1.0 / 3600.0, 0.0),
            "mm/h": (1.0 / 3600.0, 0.0),
            "mm/day": (1.0 / 86400.0, 0.0),
            "m/s": (1000.0, 0.0),
        },
        "pressure": {
            "Pa": (1.0, 0.0),
            "hPa": (100.0, 0.0),
            "kPa": (1000.0, 0.0),
            "mbar": (100.0, 0.0),
        },
        "radiation": {
            "W m-2": (1.0, 0.0),
            "J m-2 s-1": (1.0, 0.0),
            "MJ m-2 day-1": (1.0e6 / 86400.0, 0.0),
        },
        "wind": {
            "m s-1": (1.0, 0.0),
            "km/hr": (1.0 / 3.6, 0.0),
            "km/h": (1.0 / 3.6, 0.0),
            "mph": (0.44704, 0.0),
            "knots": (0.514444, 0.0),
        },
        "specific_humidity": {
            "kg kg-1": (1.0, 0.0),
            "g/kg": (0.001, 0.0),
        },
        "relative_humidity": {
            "fraction": (1.0, 0.0),
            "%": (0.01, 0.0),
        },
    }

    TYPE_ALIASES = {
        "wind_speed": "wind",
    }

    @classmethod
    def _resolve_type(
        cls,
        var_type: str,
        from_units: str,
        to_units: str,
    ) -> str:
        kind = cls.TYPE_ALIASES.get(var_type, var_type)

        if kind == "humidity":
            specific = cls.UNIT_TABLES["specific_humidity"]
            relative = cls.UNIT_TABLES["relative_humidity"]

            if from_units in specific and to_units in specific:
                return "specific_humidity"

            if from_units in relative and to_units in relative:
                return "relative_humidity"

            raise ValueError(
                "Specific and relative humidity cannot be converted "
                "using unit scaling alone."
            )

        if kind not in cls.UNIT_TABLES:
            raise ValueError(f"Unknown variable type: {var_type}")

        return kind

    @staticmethod
    def _set_units(data: ArrayLike, units: str) -> ArrayLike:
        """Preserve xarray metadata without mutating the input."""
        if hasattr(data, "assign_attrs") and hasattr(data, "attrs"):
            return data.assign_attrs({**data.attrs, "units": units})
        return data

    def convert(
        self,
        var_type: str,
        data: ArrayLike,
        from_units: str,
        to_units: str,
    ) -> ArrayLike:
        """Convert values between compatible units."""
        kind = self._resolve_type(
            var_type, from_units, to_units
        )
        table = self.UNIT_TABLES[kind]

        if from_units not in table or to_units not in table:
            raise ValueError(
                f"Unsupported {kind} conversion: "
                f"{from_units!r} -> {to_units!r}"
            )

        if from_units == to_units:
            return data

        source_scale, source_offset = table[from_units]
        target_scale, target_offset = table[to_units]

        canonical = data * source_scale + source_offset
        converted = (canonical - target_offset) / target_scale

        return self._set_units(converted, to_units)

    def get_supported_units(self, var_type: str) -> set[str]:
        """Return supported units for a variable category."""
        if var_type == "humidity":
            return (
                set(self.UNIT_TABLES["specific_humidity"])
                | set(self.UNIT_TABLES["relative_humidity"])
            )

        kind = self.TYPE_ALIASES.get(var_type, var_type)
        return set(self.UNIT_TABLES.get(kind, {}))


def convert_accumulation(
    var_type: str,
    data: ArrayLike,
    from_units: str,
    interval_seconds: ArrayLike,
) -> ArrayLike:
    """Convert an interval amount into a mean SI flux.

    This function accepts INTERVAL amounts, not an unprocessed
    cumulative series.

    For IFS forecasts accumulated since the model initialization,
    the preprocessing layer must first recover each interval amount
    using the GRIB startStep/endStep and reset semantics.

    Parameters
    ----------
    var_type:
        "precipitation" or "radiation".
    data:
        Amount accumulated within the specified interval.
    from_units:
        "m", "mm", "kg m-2", "J m-2", or "kJ m-2".
    interval_seconds:
        Positive interval duration in seconds. May be an xarray
        DataArray aligned with the temporal dimension.

    Returns
    -------
    Flux in kg m-2 s-1 or W m-2.
    """
    factors = {
        "precipitation": {
            "m": 1000.0,
            "mm": 1.0,
            "kg m-2": 1.0,
        },
        "radiation": {
            "J m-2": 1.0,
            "kJ m-2": 1000.0,
        },
    }

    if var_type not in factors:
        raise ValueError(
            "Accumulation conversion requires "
            "'precipitation' or 'radiation'."
        )

    if from_units not in factors[var_type]:
        raise ValueError(
            f"Unsupported accumulated {var_type} units: "
            f"{from_units}"
        )

    durations = np.asarray(interval_seconds)

    if (
        durations.size == 0
        or durations.dtype.kind not in "iuf"
        or not np.all(np.isfinite(durations))
        or np.any(durations <= 0)
    ):
        raise ValueError(
            "interval_seconds must contain finite, positive seconds."
        )

    scale = factors[var_type][from_units]
    flux = data * scale / interval_seconds

    target_units = {
        "precipitation": "kg m-2 s-1",
        "radiation": "W m-2",
    }

    return UnitConverter._set_units(
        flux, target_units[var_type]
    )


# Public CFIF-compatible convenience API.

def convert_temperature(
    data: ArrayLike,
    from_units: str = "degC",
    to_units: str = "K",
) -> ArrayLike:
    return UnitConverter().convert(
        "temperature", data, from_units, to_units
    )


def convert_precipitation(
    data: ArrayLike,
    from_units: str = "mm/hr",
    to_units: str = "kg m-2 s-1",
) -> ArrayLike:
    return UnitConverter().convert(
        "precipitation", data, from_units, to_units
    )


def convert_pressure(
    data: ArrayLike,
    from_units: str = "hPa",
    to_units: str = "Pa",
) -> ArrayLike:
    return UnitConverter().convert(
        "pressure", data, from_units, to_units
    )


def convert_radiation(
    data: ArrayLike,
    from_units: str,
    to_units: str,
) -> ArrayLike:
    return UnitConverter().convert(
        "radiation", data, from_units, to_units
    )


def convert_humidity(
    data: ArrayLike,
    from_units: str = "g/kg",
    to_units: str = "kg kg-1",
) -> ArrayLike:
    return UnitConverter().convert(
        "humidity", data, from_units, to_units
    )


def convert_wind(
    data: ArrayLike,
    from_units: str = "km/hr",
    to_units: str = "m s-1",
) -> ArrayLike:
    return UnitConverter().convert(
        "wind", data, from_units, to_units
    )
