
"""Reviewed ECMWF surface subset, not a claim to cover every catalogue field.

Catalogue facts are explicitly separate from GRIB validation. Server availability
and actual message metadata remain authoritative at execution time.
"""

from dataclasses import dataclass

IFS = "ifs_medium_range"
S2S = "s2s_ecds"
SEASONAL = "seasonal_ecmwf"
PRODUCTS = (IFS, S2S, SEASONAL)


@dataclass(frozen=True)
class VariableSpec:
    api_name: str
    canonical_name: str
    units: str
    param_ids: tuple[int, ...]
    kind: str = "instant"
    cadence_hours: int = 6


_BASE = {
    "2t": VariableSpec("2m_temperature", "air_temperature", "K", (167,)),
    "2d": VariableSpec("2m_dewpoint_temperature", "dew_point_temperature", "K", (168,)),
    "10u": VariableSpec("10m_u_component_of_wind", "eastward_wind", "m s-1", (165,)),
    "10v": VariableSpec("10m_v_component_of_wind", "northward_wind", "m s-1", (166,)),
    "sp": VariableSpec("surface_pressure", "surface_air_pressure", "Pa", (134,)),
    "msl": VariableSpec("mean_sea_level_pressure", "air_pressure_at_mean_sea_level", "Pa", (151,)),
    "tp": VariableSpec(
        "total_precipitation", "precipitation_flux", "kg m-2 s-1", (228,), "accum", 24
    ),
    "ssrd": VariableSpec(
        "surface_solar_radiation_downwards",
        "surface_downwelling_shortwave_flux_in_air",
        "W m-2",
        (169,),
        "accum",
        24,
    ),
    "strd": VariableSpec(
        "surface_thermal_radiation_downwards",
        "surface_downwelling_longwave_flux_in_air",
        "W m-2",
        (175,),
        "accum",
        24,
    ),
}


def variables(product: str) -> dict[str, VariableSpec]:
    from dataclasses import replace

    out = dict(_BASE)
    if product == IFS:
        return {key: replace(value, cadence_hours=3) for key, value in out.items()}
    if product == S2S:
        # S2S surface pressure is a control-only/static field in the parameter table;
        # do not pretend it supplies time-varying ensemble surface pressure.
        out.pop("sp")
        out.pop("msl")  # Also a control-only daily field in the S2S parameter table.
        for key in ("2t", "2d"):
            out[key] = replace(out[key], kind="avg", cadence_hours=24)
        # ecCodes' WMO/statistical definitions can expose a dedicated mean
        # parameter ID instead of the S2S compatibility ID. The handler still
        # requires stepType=avg and explicit 24-hour bounds for every alias.
        out["2t"] = replace(out["2t"], param_ids=(167, 228004, 55))
        out["2d"] = replace(out["2d"], param_ids=(168, 235168, 56))
        out["tp"] = replace(out["tp"], param_ids=(228228,), cadence_hours=6)
        return out
    if product == SEASONAL:
        out.pop("sp")  # Not in seasonal-original-single-levels. MSL is NOT a substitute.
        return out
    raise ValueError(f"Unknown forecast product: {product}")


PRODUCT_WARNINGS = {
    IFS: (
        "Open Data is a rolling archive, not an unrestricted historical archive.",
        "Spatial cropping is local; selected global GRIB fields are downloaded.",
    ),
    S2S: (
        "ECDS S2S is delayed; no assumption of operational real-time availability.",
        "ECDS member selection is local: perturbed requests retrieve all members.",
        "S2S daily-mean temperatures are not instantaneous SUMMA forcings.",
        "Non-wrapping bbox is requested at the server; dateline boxes are cropped locally.",
    ),
    SEASONAL: (
        "CDS returns the available ensemble; member selection is local.",
        "Accumulated fields are daily; no implicit hourly disaggregation.",
        "Surface pressure is absent from this catalogue subset.",
        "Non-wrapping bbox is requested at the server; dateline boxes are cropped locally.",
    ),
}
