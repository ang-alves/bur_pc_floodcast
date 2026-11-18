
"""Handler registry utilities for Floodcast data components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from floodcast.core.registry import ComponentManifest

from . import DATA_REVISION, DATA_VERSION

if TYPE_CHECKING:
    from floodcast.core.registries import Registries
    from floodcast.core.registry import ComponentRegistry


class BaseRegistry:
    """Access data handlers through Floodcast's central registry."""

    registry_name: str = ""

    def __init__(self, registries: Registries) -> None:
        self.R = registries

    @property
    def registry(self) -> ComponentRegistry:
        if not self.registry_name:
            raise NotImplementedError(
                "A registry_name must be defined."
            )
        return getattr(self.R, self.registry_name)

    def list_handlers(self) -> tuple[str, ...]:
        """Return registered handler identifiers."""
        return tuple(
            sorted(
                manifest.component_id
                for manifest in self.registry.manifests()
            )
        )

    def is_registered(self, name: str) -> bool:
        """Check whether a handler is registered."""
        return name.strip().lower() in self.list_handlers()

    def get_handler(
        self,
        name: str,
        config: Any,
        logger: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Resolve and instantiate a registered handler."""
        key = name.strip().lower()

        if not self.is_registered(key):
            available = ", ".join(self.list_handlers())
            raise ValueError(
                f"Unknown handler {name!r}. Available: {available}"
            )

        handler_class = self.registry.resolve(key).factory()

        return handler_class(config, logger, **kwargs)


def register_class(
    registry: ComponentRegistry,
    name: str,
    handler_class: type,
) -> None:
    """Register a handler class in Floodcast's component registry."""
    if not isinstance(handler_class, type):
        raise TypeError("Handler must be a class.")

    key = name.strip().lower()
    if not key:
        raise ValueError("Handler name cannot be empty.")

    registry.register(
        ComponentManifest(
            component_id=key,
            contract_id=registry.contract_id,
            implementation_version=DATA_VERSION,
            source_revision=DATA_REVISION,
        ),
        lambda cls=handler_class: cls,
    )
