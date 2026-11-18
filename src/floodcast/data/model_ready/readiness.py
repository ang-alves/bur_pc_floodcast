
"""Report configuration gaps without certifying unseen forcing files."""


def assess_forcing_readiness(config):
    # Preserve the earlier ForecastConfig-only public helper.
    forecast = getattr(config, "forecast", config)
    required = {"2t", "2d", "10u", "10v", "sp", "tp", "ssrd", "strd"}
    blockers = []
    missing = sorted(required - set(forecast.fields))
    if missing:
        blockers.append("Missing native forcing inputs: " + ", ".join(missing))
    if getattr(config, "remapping", None) is None:
        blockers.append("An authoritative HRU geometry must be configured")
    if getattr(config, "model_forcing", None) is None:
        blockers.append("An explicit target timestep and temporal policies must be configured")
    if forecast.product == "s2s_ecds":
        blockers.append("S2S daily mean temperature is not an instantaneous SUMMA state")
    return {
        "assessment": "configuration_only",
        "model_ready": False,
        "implemented_stages": ["acquisition", "preprocessing", "HRU_remapping", "SUMMA_forcing"],
        "missing_native_inputs": missing,
        "configuration_blockers": blockers,
        "verification_required": "Execute the pipeline and inspect forcing_manifest.json",
        "scientific_validation": "not_run",
        "warning": "Mean sea level pressure cannot replace surface pressure.",
    }
