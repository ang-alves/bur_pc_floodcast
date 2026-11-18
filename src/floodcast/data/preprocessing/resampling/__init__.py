"""Area-weighted meteorological remapping for Floodcast.

The forecast workflow owns grids, HRU geometry, member identity and cache
provenance. This package only builds and applies EASYMORE area weights.
"""

from __future__ import annotations

from importlib import import_module

__all__ = ["RemappingWeightGenerator", "RemappingWeightApplier"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    module = "weight_generator" if name == "RemappingWeightGenerator" else "weight_applier"
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value
