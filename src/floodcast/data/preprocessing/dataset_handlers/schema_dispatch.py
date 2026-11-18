
from ...contracts import AcquisitionManifest
from ...errors import DataError
from .dataset_registry import DatasetRegistry


def resolve_dataset_handler(manifest_path, config, logger, registries):
    try:
        manifest = AcquisitionManifest.model_validate_json(manifest_path.read_bytes())
    except Exception:
        raise DataError(
            "INVALID_MANIFEST",
            "A valid declared acquisition schema is required; no heuristic fallback",
        ) from None
    if manifest.plan.config != config:
        raise DataError("REQUEST_MISMATCH", "Acquisition and preprocessing configurations differ")
    handler = DatasetRegistry(registries).get_handler(config.product, config, logger)
    if handler.input_schema != manifest.declared_schema:
        raise DataError("SCHEMA_MISMATCH", "Selected handler cannot consume the declared schema")
    return manifest, handler
