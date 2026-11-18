"""Explicit, application-scoped component discovery; never installation storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import Field, StrictStr

from floodcast.core.contracts import Contract, Identifier
from floodcast.core.errors import FloodcastError


class ComponentManifest(Contract):
    component_id: Identifier
    contract_id: StrictStr = Field(pattern=r"^ffw\.[a-z-]+/v[1-9][0-9]*$")
    implementation_version: StrictStr = Field(min_length=1)
    source_revision: StrictStr = Field(min_length=1)


@dataclass(frozen=True)
class Registration[T]:
    manifest: ComponentManifest
    factory: Callable[[], T]


class ComponentRegistry[T]:
    """Register factories explicitly; discovery never constructs an implementation.

    Registration is a composition-time operation. No module-global singleton,
    import scanning, arbitrary dotted-path loading or installation side effects.
    The declared source_revision must identify the implementation being supplied.
    """

    def __init__(self, contract_id: str) -> None:
        self.contract_id = contract_id
        self._entries: dict[str, Registration[T]] = {}

    def register(self, manifest: ComponentManifest, factory: Callable[[], T]) -> None:
        if manifest.contract_id != self.contract_id:
            raise FloodcastError("INVALID_CONFIG", "components", "Component contract mismatch")
        if not callable(factory):
            raise FloodcastError("INVALID_CONFIG", "components", "Factory must be callable")
        if manifest.component_id in self._entries:
            raise FloodcastError(
                "REGISTRY_CONFLICT", "components", f"Duplicate component: {manifest.component_id}"
            )
        self._entries[manifest.component_id] = Registration(manifest, factory)

    def resolve(self, component_id: str) -> Registration[T]:
        try:
            return self._entries[component_id]
        except KeyError as exc:
            raise FloodcastError(
                "INVALID_CONFIG", "components", f"Unknown component: {component_id}"
            ) from exc

    def manifests(self) -> tuple[ComponentManifest, ...]:
        return tuple(self._entries[key].manifest for key in sorted(self._entries))
