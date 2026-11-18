
"""Base forcing adapter for Floodcast hydrological models."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import xarray as xr

from floodcast.data.preprocessing.cfif import get_cfif_units


class ForcingAdapter(ABC):
    """Base interface for model-specific forcing adapters."""

    def __init__(
        self,
        config: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(
            self.__class__.__name__
        )

    @abstractmethod
    def get_required_variables(self) -> list[str]:
        """Return the CFIF variables required by the model."""

    @abstractmethod
    def get_variable_mapping(self) -> dict[str, str]:
        """Map canonical variables to model-specific names."""

    def transform(self, data: xr.Dataset) -> xr.Dataset:
        """Validate and map canonical forcing data."""
        if not isinstance(data, xr.Dataset):
            raise TypeError("Expected an xarray.Dataset.")

        required = self.get_required_variables()
        mapping = self.get_variable_mapping()

        if len(required) != len(set(required)):
            raise ValueError("Duplicate required variables.")

        missing = sorted(set(required) - set(data.data_vars))

        if missing:
            raise ValueError(
                f"Missing required forcing variables: {missing}"
            )

        # Validate canonical units before any model-specific processing.
        variables = set(required) | (set(mapping) & set(data.data_vars))

        for name in variables:
            expected = get_cfif_units(name)

            if expected is None:
                raise ValueError(f"Unknown CFIF variable: {name}")

            actual = data[name].attrs.get("units")

            if actual != expected:
                raise ValueError(
                    f"{name}: expected units {expected!r}, "
                    f"got {actual!r}"
                )

        # Map variable names without overwriting existing data.
        renames = {}
        targets = set()

        for source, target in mapping.items():
            if source not in data.data_vars:
                continue

            if not target or target in targets:
                raise ValueError(
                    f"Invalid or duplicate target variable: {target!r}"
                )

            targets.add(target)

            if source == target:
                continue

            if target in data.variables:
                raise ValueError(
                    f"Target variable {target!r} already exists."
                )

            renames[source] = target

        result = data.rename(renames)

        result.attrs = {
            **data.attrs,
            "forcing_adapter": self.__class__.__name__,
        }

        return result
