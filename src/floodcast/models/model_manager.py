"""Prepare/postprocess through an adapter; delegate runs to the Stage 1 runtime."""

from __future__ import annotations

from collections.abc import Callable

from floodcast.core.contracts import RunRequest, RunResult, RunStatus
from floodcast.core.errors import FloodcastError
from floodcast.core.registries import Registries
from floodcast.core.storage import atomic_json, evidence
from floodcast.core.workflow_contracts import StepContext, StepResult


class ModelManager:
    """The injected run function can be RuntimeManager.run or a local-run binding.

    No installation, process launcher, flood policy or implicit scientific validation
    lives here. Real adapters and runtime integration tests are separate increments.
    """

    def __init__(
        self, *, registries: Registries, run_model: Callable[[RunRequest], RunResult]
    ) -> None:
        self.registries = registries
        self.run_model = run_model

    def run(self, adapter_id: str, context: StepContext) -> StepResult:
        adapter = self.registries.model_adapters.resolve(adapter_id).factory()
        request = adapter.prepare(context)
        if not isinstance(request, RunRequest):
            raise FloodcastError("INVALID_CONFIG", "model-adapter", "Expected Stage 1 RunRequest")
        request = RunRequest.model_validate_json(request.model_dump_json())
        if request.model_id != adapter.model_id:
            raise FloodcastError("IDENTITY_MISMATCH", "model-adapter", "Adapter/model mismatch")
        # Persist the Stage 1 run ID before dispatch so an interrupted run is traceable.
        request_path = context.work_dir / "model-request.json"
        atomic_json(request_path, request)
        request_ref = evidence(request_path)
        result = self.run_model(request)
        if not isinstance(result, RunResult):
            raise FloodcastError("INVALID_CONFIG", "model-runtime", "Expected Stage 1 RunResult")
        result = RunResult.model_validate_json(result.model_dump_json())
        if result.run_id != request.run_id:
            raise FloodcastError("IDENTITY_MISMATCH", "model-runtime", "Runtime run ID mismatch")
        result_path = context.work_dir / "model-result.json"
        atomic_json(result_path, result)
        result_ref = evidence(result_path)
        if result.status != RunStatus.SUCCEEDED:
            code = "MODEL_FAILED" if result.status.terminal else "CANCEL_UNCONFIRMED"
            raise FloodcastError(
                code,
                "model-runtime",
                f"Model execution: {result.status}",
                evidence_paths=(request_path, result_path),
            )
        outcome = adapter.postprocess(context, result)
        if not isinstance(outcome, StepResult):
            raise FloodcastError("INVALID_CONFIG", "model-adapter", "Expected StepResult")
        outcome = StepResult.model_validate_json(outcome.model_dump_json())
        refs = {ref.path: ref for ref in outcome.outputs}
        for ref in (request_ref, result_ref):
            if evidence(ref.path).sha256 != ref.sha256:
                raise FloodcastError("IDENTITY_MISMATCH", "model-adapter", "Provenance changed")
            if ref.path in refs and refs[ref.path] != ref:
                raise FloodcastError("IDENTITY_MISMATCH", "model-adapter", "Conflicting provenance")
            refs[ref.path] = ref
        return StepResult.model_validate(
            {
                **outcome.model_dump(),
                "outputs": tuple(refs.values()),
            }
        )
