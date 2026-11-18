
from __future__ import annotations

import hashlib
from uuid import UUID

from floodcast.core.config import RuntimeConfig
from floodcast.core.contracts import canonical_json_bytes
from floodcast.core.errors import FloodcastError
from floodcast.core.registries import Registries
from floodcast.core.storage import evidence
from floodcast.core.workflow_contracts import (
    WorkflowDefinition,
    WorkflowPlan,
    WorkflowRecord,
    WorkflowRequest,
)
from floodcast.project.run_store import RunStore
from floodcast.project.state_service import StateService
from floodcast.project.workflow_orchestrator import WorkflowOrchestrator


class Floodcast:
    def __init__(
        self, config: RuntimeConfig, *, code_identity: str, registries: Registries | None = None
    ) -> None:
        self.config = RuntimeConfig.model_validate_json(config.model_dump_json())
        self.R = registries if registries is not None else Registries()
        self.run_store = RunStore(self.config.data_root / "workflows")
        self.states = StateService()
        self.orchestrator = WorkflowOrchestrator(
            registries=self.R,
            store=self.run_store,
            code_identity=code_identity,
            runtime_configuration_sha256=hashlib.sha256(
                canonical_json_bytes(self.config)
            ).hexdigest(),
        )

    def with_forecast_data(self, *, services=None, reader=None) -> Floodcast:
        """Compose forecast handlers and steps in this application's ``R``.

        Importing or constructing Floodcast still does not load provider SDKs,
        create data clients, acquire forecasts, or inspect Docker installations.
        """
        from floodcast.data.registration import register_data_handlers
        from floodcast.data.workflow import register_forecast_steps

        forecast_ids = {
            "forecast.acquire",
            "forecast.normalize",
            "forecast.remap",
            "forecast.model_ready",
        }
        if forecast_ids & {item.component_id for item in self.R.steps.manifests()}:
            raise ValueError("Forecast data steps are already composed")
        register_data_handlers(self.R)
        register_forecast_steps(self.R, services=services, reader=reader)
        return self

    def data(self, config, *, services=None, reader=None):
        """Construct a data facade using this application's component bindings."""
        from floodcast.data.data_manager import DataManager

        if config.data_root != self.config.data_root:
            raise FloodcastError(
                "IDENTITY_MISMATCH",
                "forecast-data",
                "The data facade must use the application's data_root",
            )
        return DataManager(config, registries=self.R, services=services, reader=reader)

    def plan(self, definition: WorkflowDefinition, request: WorkflowRequest) -> WorkflowPlan:
        return self.orchestrator.plan(definition, request)

    def run(
        self, definition: WorkflowDefinition, request: WorkflowRequest, *, resume: bool = False
    ) -> WorkflowRecord:
        if request.purpose == "verification":
            parent = self.run_store.load(request.parent_run_id)
            if parent.finished_at is None or parent.plan.request.domain_id != request.domain_id:
                raise FloodcastError(
                    "IDENTITY_MISMATCH",
                    "verification",
                    "Verification requires a final parent run in the same domain",
                )
            parent_ref = evidence(self.run_store.manifest_path(request.parent_run_id))
            if parent_ref not in request.inputs:
                raise FloodcastError(
                    "IDENTITY_MISMATCH",
                    "verification",
                    "Verification inputs must include the original final manifest and its hash",
                )
        return self.orchestrator.run(definition, request, resume=resume)

    def inspect(self, run_id: UUID) -> WorkflowRecord:
        return self.run_store.load(run_id)
