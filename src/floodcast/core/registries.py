"""Application-owned R facade; unrelated to the Stage 1 installation registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from floodcast.core.registry import ComponentRegistry

if TYPE_CHECKING:
    from floodcast.core.modeling.contracts import ModelAdapter
    from floodcast.core.modeling.forcing_adapter import ForcingAdapter
    from floodcast.core.workflow_contracts import StepHandler
    from floodcast.data.acquisition.base import BaseAcquisitionHandler
    from floodcast.data.preprocessing.dataset_handlers.base_dataset import BaseDatasetHandler


class Registries:
    def __init__(self) -> None:
        self.steps: ComponentRegistry[StepHandler] = ComponentRegistry("ffw.step/v1")
        self.model_adapters: ComponentRegistry[ModelAdapter] = ComponentRegistry(
            "ffw.model-adapter/v1"
        )
        self.acquisition_handlers: ComponentRegistry[type[BaseAcquisitionHandler]] = (
            ComponentRegistry("ffw.acquisition/v1")
        )
        self.dataset_handlers: ComponentRegistry[type[BaseDatasetHandler]] = ComponentRegistry(
            "ffw.dataset/v1"
        )
        self.forcing_adapters: ComponentRegistry[type[ForcingAdapter]] = ComponentRegistry(
            "ffw.forcing-adapter/v1"
        )
