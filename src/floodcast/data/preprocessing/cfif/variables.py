"""
Floodcast CF-Intermediate Format (CFIF) variable definitions.

Defines model-neutral meteorological variable names, canonical units,
CF metadata and mappings used by forecast preprocessing and model
forcing adapters.

Supported contexts:
    - Historical meteorological forcing
    - ECMWF IFS medium-range forecasts
    - ECMWF S2S/subseasonal forecasts
    - ECMWF seasonal forecasts
    - SUMMA forcing compatibility

This module defines variable identities and validates metadata.

"""

from __future__ import annotations

import logging
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    import xarray as xr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Canonical CFIF variable definitions
# ---------------------------------------------------------------------

CFIF_VARIABLES: dict[str, dict[str, str]] = {
    # Temperature
    "air_temperature": {
        "cf_standard_name": "air_temperature",
        "units": "K",
        "long_name": "Near-surface air temperature",
        "description": "Air temperature at 2 m above surface",
    },
    "dew_point_temperature": {
        "cf_standard_name": "dew_point_temperature",
        "units": "K",
        "long_name": "Near-surface dew point temperature",
        "description": "Dew point temperature at 2 m",
    },
    "air_temperature_mean": {
        "cf_standard_name": "air_temperature",
        "units": "K",
        "long_name": "Mean air temperature",
        "description": "Air temperature averaged over a time interval",
        "cell_methods": "time: mean",
    },
    "air_temperature_min": {
        "cf_standard_name": "air_temperature",
        "units": "K",
        "long_name": "Minimum air temperature",
        "description": "Minimum air temperature over a time interval",
        "cell_methods": "time: minimum",
    },
    "air_temperature_max": {
        "cf_standard_name": "air_temperature",
        "units": "K",
        "long_name": "Maximum air temperature",
        "description": "Maximum air temperature over a time interval",
        "cell_methods": "time: maximum",
    },

    # Precipitation
    "precipitation_flux": {
        "cf_standard_name": "precipitation_flux",
        "units": "kg m-2 s-1",
        "long_name": "Precipitation rate",
        "description": "Total liquid and solid precipitation mass flux",
    },
    "rainfall_flux": {
        "cf_standard_name": "rainfall_flux",
        "units": "kg m-2 s-1",
        "long_name": "Rainfall rate",
        "description": "Liquid precipitation mass flux",
    },
    "snowfall_flux": {
        "cf_standard_name": "snowfall_flux",
        "units": "kg m-2 s-1",
        "long_name": "Snowfall rate",
        "description": "Solid precipitation mass flux",
    },

    # Radiation
    "surface_downwelling_shortwave_flux": {
        "cf_standard_name": (
            "surface_downwelling_shortwave_flux_in_air"
        ),
        "units": "W m-2",
        "long_name": "Downward shortwave radiation",
        "description": "Incoming solar radiation at the surface",
    },
    "surface_downwelling_longwave_flux": {
        "cf_standard_name": (
            "surface_downwelling_longwave_flux_in_air"
        ),
        "units": "W m-2",
        "long_name": "Downward longwave radiation",
        "description": "Incoming atmospheric thermal radiation",
    },

    # Humidity
    "specific_humidity": {
        "cf_standard_name": "specific_humidity",
        "units": "kg kg-1",
        "long_name": "Specific humidity",
        "description": "Mass of water vapour per mass of moist air",
    },
    "relative_humidity": {
        "cf_standard_name": "relative_humidity",
        "units": "%",
        "long_name": "Relative humidity",
        "description": "Ratio of actual to saturation vapour pressure",
    },

    # Wind
    "wind_speed": {
        "cf_standard_name": "wind_speed",
        "units": "m s-1",
        "long_name": "Wind speed",
        "description": "Magnitude of near-surface wind velocity",
    },
    "eastward_wind": {
        "cf_standard_name": "eastward_wind",
        "units": "m s-1",
        "long_name": "Eastward wind component",
        "description": "Eastward component of wind velocity",
    },
    "northward_wind": {
        "cf_standard_name": "northward_wind",
        "units": "m s-1",
        "long_name": "Northward wind component",
        "description": "Northward component of wind velocity",
    },

    # Pressure
    "surface_air_pressure": {
        "cf_standard_name": "surface_air_pressure",
        "units": "Pa",
        "long_name": "Surface air pressure",
        "description": "Atmospheric pressure at the surface",
    },

    # Evapotranspiration
    "potential_evapotranspiration": {
        "cf_standard_name": "water_potential_evaporation_flux",
        "units": "kg m-2 s-1",
        "long_name": "Potential evapotranspiration",
        "description": "Potential water evaporation mass flux",
    },
}


# ---------------------------------------------------------------------
# Legacy SUMMA compatibility
# ---------------------------------------------------------------------

# Preserve the original SYMFLUENCE mapping.
SUMMA_TO_CFIF_MAPPING: dict[str, str] = {
    "airtemp": "air_temperature",
    "pptrate": "precipitation_flux",
    "SWRadAtm": "surface_downwelling_shortwave_flux",
    "LWRadAtm": "surface_downwelling_longwave_flux",
    "spechum": "specific_humidity",
    "relhum": "relative_humidity",
    "windspd": "wind_speed",
    "windspd_u": "eastward_wind",
    "windspd_v": "northward_wind",
    "airpres": "surface_air_pressure",
}

CFIF_TO_SUMMA_MAPPING: dict[str, str] = {
    cfif_name: summa_name
    for summa_name, cfif_name in SUMMA_TO_CFIF_MAPPING.items()
}


# ---------------------------------------------------------------------
# ECMWF forecast field mappings
# ---------------------------------------------------------------------

# Only fields whose physical meaning is directly compatible
# with the target CFIF variable are included here.
#
# Units MUST still be checked before renaming.
# The forecast handler must also verify temporal semantics
# and the vertical level of each GRIB field.
#
# Alternative spellings cover common GRIB/xarray decoders.

ECMWF_DIRECT_CFIF_MAPPING: dict[str, str] = {
    "2t": "air_temperature",
    "t2m": "air_temperature",
    "2d": "dew_point_temperature",
    "d2m": "dew_point_temperature",
    "10u": "eastward_wind",
    "u10": "eastward_wind",
    "10v": "northward_wind",
    "v10": "northward_wind",
    "sp": "surface_air_pressure",
}


# These ECMWF variables require a physical transformation BEFORE
# they can be represented using the target CFIF variable.
#
# This dictionary is descriptive metadata, not an automatic
# conversion or renaming mechanism.

ECMWF_TRANSFORMATIONS: dict[str, dict[str, str]] = {
    "tp": {
        "target": "precipitation_flux",
        "operation": "deaccumulate_and_convert_to_flux",
        "description": (
            "Recover interval precipitation from GRIB step ranges "
            "and convert the amount to kg m-2 s-1."
        ),
    },
    "ssrd": {
        "target": "surface_downwelling_shortwave_flux",
        "operation": "deaccumulate_and_convert_to_flux",
        "description": (
            "Recover interval shortwave energy and divide "
            "by the interval duration in seconds."
        ),
    },
    "strd": {
        "target": "surface_downwelling_longwave_flux",
        "operation": "deaccumulate_and_convert_to_flux",
        "description": (
            "Recover interval longwave energy and divide "
            "by the interval duration in seconds."
        ),
    },
    "wind_speed_from_uv": {
        "target": "wind_speed",
        "operation": "calculate_wind_magnitude",
        "description": (
            "Calculate wind magnitude from compatible "
            "eastward and northward wind components."
        ),
    },
    "specific_humidity_from_dewpoint": {
        "target": "specific_humidity",
        "operation": "calculate_specific_humidity",
        "description": (
            "Calculate specific humidity from dew point "
            "temperature and actual surface air pressure."
        ),
    },
}


# ---------------------------------------------------------------------
# Variable lookup
# ---------------------------------------------------------------------

def get_cfif_variable(name: str) -> dict[str, str] | None:
    """Return a copy of the CFIF definition for a variable."""
    definition = CFIF_VARIABLES.get(name)
    return dict(definition) if definition is not None else None


def get_cfif_standard_name(name: str) -> str | None:
    """Return the CF standard_name associated with a CFIF variable."""
    definition = get_cfif_variable(name)
    return (
        definition["cf_standard_name"]
        if definition is not None
        else None
    )


def get_cfif_units(name: str) -> str | None:
    """Return the canonical units of a CFIF variable."""
    definition = get_cfif_variable(name)
    return definition["units"] if definition is not None else None


def get_cfif_attributes(name: str) -> dict[str, str] | None:
    """Return the CF attributes suitable for an xarray variable."""
    definition = get_cfif_variable(name)

    if definition is None:
        return None

    return {
        "standard_name": definition["cf_standard_name"],
        **{
            key: value
            for key, value in definition.items()
            if key != "cf_standard_name"
        },
    }


def get_supported_cfif_variables() -> tuple[str, ...]:
    """List the canonical variables supported by this module."""
    return tuple(CFIF_VARIABLES)


# ---------------------------------------------------------------------
# Variable normalization
# ---------------------------------------------------------------------

def normalize_to_cfif(
    ds: xr.Dataset,
    *,
    source: Literal["summa", "ecmwf"] = "summa",
    on_conflict: Literal["raise", "keep_cfif"] = "raise",
) -> xr.Dataset:
    """Rename compatible source variables to CFIF names.

    The default preserves the historical SUMMA workflow.

    For ECMWF, only directly compatible source fields are eligible.
    Conversion of accumulated fields is deliberately excluded.

    This function does not change numerical values or units.

    Conflicting source and canonical variables raise by default,
    preventing silent selection of inconsistent data.
    """
    if source == "summa":
        mapping = SUMMA_TO_CFIF_MAPPING
    elif source == "ecmwf":
        mapping = ECMWF_DIRECT_CFIF_MAPPING
    else:
        raise ValueError(f"Unsupported source: {source}")

    if on_conflict not in {"raise", "keep_cfif"}:
        raise ValueError(
            f"Unsupported conflict policy: {on_conflict}"
        )

    renames: dict[str, str] = {}
    targets: set[str] = set()

    for source_name, target_name in mapping.items():
        if source_name not in ds.data_vars:
            continue

        # ECMWF raw fields must have canonical units before
        # a direct rename is permitted.
        if source == "ecmwf":
            expected_units = get_cfif_units(target_name)
            actual_units = ds[source_name].attrs.get("units")

            if actual_units != expected_units:
                raise ValueError(
                    f"{source_name}: expected units "
                    f"{expected_units!r}, got {actual_units!r}. "
                    "Convert units before renaming."
                )

        if target_name in ds.variables or target_name in targets:
            if on_conflict == "raise":
                raise ValueError(
                    f"Cannot rename {source_name!r} to "
                    f"{target_name!r}: target already exists."
                )

            logger.warning(
                "Skipping %s -> %s because target already exists",
                source_name,
                target_name,
            )
            continue

        renames[source_name] = target_name
        targets.add(target_name)

    return ds.rename(renames) if renames else ds


# ---------------------------------------------------------------------
# CFIF metadata attachment
# ---------------------------------------------------------------------

def apply_cfif_attributes(ds: xr.Dataset) -> xr.Dataset:
    """Attach canonical CF metadata without modifying numerical data.

    Existing units must already match CFIF.
    Missing units and contradictory metadata are rejected.

    This function must not be used to claim that an unprocessed GRIB
    field has been physically normalized.
    """
    result = ds.copy(deep=False)

    for name in result.data_vars:
        expected = get_cfif_attributes(name)

        if expected is None:
            continue

        actual = result[name].attrs

        if actual.get("units") != expected["units"]:
            raise ValueError(
                f"{name}: cannot attach CFIF metadata. "
                f"Expected units {expected['units']!r}, "
                f"got {actual.get('units')!r}."
            )

        attributes = dict(actual)

        for key, value in expected.items():
            if key in attributes and attributes[key] != value:
                # Additional CF cell methods may coexist with the
                # required temporal method.
                if (
                    key == "cell_methods"
                    and value in str(attributes[key])
                ):
                    continue

                # Source long names/descriptions may differ without
                # changing the physical identity of the field.
                if key in {"long_name", "description"}:
                    continue

                raise ValueError(
                    f"{name}: conflicting {key!r}: "
                    f"{attributes[key]!r} != {value!r}"
                )

            attributes.setdefault(key, value)

        result[name] = result[name].assign_attrs(attributes)

    return result


# ---------------------------------------------------------------------
# CFIF validation
# ---------------------------------------------------------------------

def validate_cfif_dataset(
    ds: xr.Dataset,
    required_vars: list[str] | None = None,
    *,
    require_standard_name: bool = False,
    require_cell_methods: bool = False,
) -> list[str]:
    """Validate CFIF variable presence, units and CF metadata.

    Retains the original list-of-issues API.

    Unknown non-CFIF variables are ignored, since a dataset may
    contain additional diagnostic or provenance variables.

    Parameters
    ----------
    ds:
        Dataset to validate.
    required_vars:
        Explicit list of required canonical variable names.
    require_standard_name:
        If True, require a standard_name attribute.
    require_cell_methods:
        If True, require cell_methods for interval statistics.

    Returns
    -------
    list[str]
        Validation issues. An empty list means that the checks
        performed by this function passed.
    """
    issues: list[str] = []

    if required_vars is not None:
        for name in required_vars:
            if name not in CFIF_VARIABLES:
                issues.append(
                    f"Unknown required CFIF variable: {name}"
                )
            elif name not in ds.data_vars:
                issues.append(
                    f"Missing required variable: {name}"
                )

    for name in ds.data_vars:
        if name not in CFIF_VARIABLES:
            continue

        expected = CFIF_VARIABLES[name]
        attributes = ds[name].attrs

        # Units
        actual_units = attributes.get("units")

        if actual_units is None:
            issues.append(
                f"Variable {name}: missing 'units' attribute"
            )
        elif actual_units != expected["units"]:
            issues.append(
                f"Variable {name}: expected units "
                f"{expected['units']!r}, got {actual_units!r}"
            )

        # CF standard name
        expected_standard_name = expected["cf_standard_name"]
        actual_standard_name = attributes.get("standard_name")

        if actual_standard_name is None:
            if require_standard_name:
                issues.append(
                    f"Variable {name}: missing 'standard_name'"
                )
        elif actual_standard_name != expected_standard_name:
            issues.append(
                f"Variable {name}: expected standard_name "
                f"{expected_standard_name!r}, "
                f"got {actual_standard_name!r}"
            )

        # Temporal statistics
        expected_methods = expected.get("cell_methods")

        if expected_methods:
            actual_methods = attributes.get("cell_methods")

            if actual_methods is None:
                if require_cell_methods:
                    issues.append(
                        f"Variable {name}: missing 'cell_methods'"
                    )
            elif expected_methods not in str(actual_methods):
                issues.append(
                    f"Variable {name}: expected cell_methods "
                    f"containing {expected_methods!r}, "
                    f"got {actual_methods!r}"
                )

    return issues


def require_valid_cfif_dataset(
    ds: xr.Dataset,
    required_vars: list[str] | None = None,
    *,
    require_standard_name: bool = False,
    require_cell_methods: bool = False,
) -> None:
    """Raise an exception if CFIF validation finds issues."""
    issues = validate_cfif_dataset(
        ds,
        required_vars=required_vars,
        require_standard_name=require_standard_name,
        require_cell_methods=require_cell_methods,
    )

    if issues:
        raise ValueError(
            "Invalid CFIF dataset:\n- " + "\n- ".join(issues)
        )


# ---------------------------------------------------------------------
# SUMMA forcing requirements
# ---------------------------------------------------------------------

# Canonical variables normally consumed by the SUMMA forcing adapter.
# The definitive requirements must still come from the selected
# model configuration and adapter contract.

SUMMA_REQUIRED_CFIF_VARIABLES: tuple[str, ...] = (
    "air_temperature",
    "precipitation_flux",
    "surface_downwelling_shortwave_flux",
    "surface_downwelling_longwave_flux",
    "specific_humidity",
    "wind_speed",
    "surface_air_pressure",
)


def validate_summa_cfif_dataset(
    ds: xr.Dataset,
) -> list[str]:
    """Validate the variables required by the standard SUMMA adapter. 
    """
    return validate_cfif_dataset(
        ds,
        required_vars=list(SUMMA_REQUIRED_CFIF_VARIABLES),
        require_standard_name=True,
    )
