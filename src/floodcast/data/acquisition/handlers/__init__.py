
"""Explicit loader corresponding to acquisition import/registration loop.

Only the three product modules are imported, and SDK imports happen on retrieval.
"""

from importlib import import_module

from ...base_registry import register_class

HANDLERS = (
    ("ifs_open_data", "IFSOpenDataAcquirer", "ifs_medium_range"),
    ("s2s_ecds", "S2SECDSAcquirer", "s2s_ecds"),
    ("seasonal_cds", "SeasonalCDSAcquirer", "seasonal_ecmwf"),
)


def register_handlers(registries):
    for module_name, class_name, key in HANDLERS:
        cls = getattr(import_module(f".{module_name}", __name__), class_name)
        register_class(registries.acquisition_handlers, key, cls)
