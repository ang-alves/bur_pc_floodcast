# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose built-in data families atomically, with no global registry state."""


def register_data_handlers(registries):
    """Load and validate both families before mutating the application.

    Custom nonconflicting handlers may already be present. A missing module or
    conflicting built-in leaves both target families exactly as they were.
    Registration is a composition-time operation, before workflow execution.
    """
    from floodcast.core.registries import Registries
    from floodcast.core.registry import ComponentManifest

    from . import DATA_VERSION
    from .acquisition.handlers import register_handlers as acquisition
    from .model_ready import FORCING_REVISION
    from .preprocessing.dataset_handlers import register_handlers as datasets

    staged = Registries()
    acquisition(staged)
    datasets(staged)
    staged.forcing_adapters.register(
        ComponentManifest(
            component_id="summa",
            contract_id="ffw.forcing-adapter/v1",
            implementation_version=DATA_VERSION,
            source_revision=FORCING_REVISION,
        ),
        _summa_forcing_adapter,
    )
    pending = []
    for name in ("acquisition_handlers", "dataset_handlers", "forcing_adapters"):
        target = getattr(registries, name)
        source = getattr(staged, name)
        existing = {item.component_id for item in target.manifests()}
        for manifest in source.manifests():
            if manifest.component_id in existing:
                raise ValueError(f"Data handler already registered: {manifest.component_id}")
            if manifest.contract_id != target.contract_id:
                raise ValueError(f"Data registry contract mismatch: {name}")
            pending.append((target, source.resolve(manifest.component_id)))
    for target, registration in pending:
        target.register(registration.manifest, registration.factory)


def _summa_forcing_adapter():
    # Numerical imports happen only when model-ready processing selects SUMMA.
    from floodcast.models.summa.forcing_adapter import SUMMAForcingAdapter

    return SUMMAForcingAdapter
