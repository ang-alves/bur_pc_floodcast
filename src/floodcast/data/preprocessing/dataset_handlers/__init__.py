
from importlib import import_module

from ...base_registry import register_class
from .base_dataset import BaseDatasetHandler
from .dataset_registry import DatasetRegistry

HANDLERS = (
    ("ifs_utils", "IFSHandler", "ifs_medium_range"),
    ("s2s_utils", "S2SHandler", "s2s_ecds"),
    ("seasonal_utils", "SeasonalHandler", "seasonal_ecmwf"),
)


def register_handlers(registries):
    for module, name, key in HANDLERS:
        handler = getattr(import_module(f".{module}", __name__), name)
        register_class(registries.dataset_handlers, key, handler)


__all__ = ["BaseDatasetHandler", "DatasetRegistry", "register_handlers"]
