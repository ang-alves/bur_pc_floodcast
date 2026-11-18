"""Serial dependency orchestration; no model/provider-specific dispatch or thresholds."""

from __future__ import annotations

import hashlib
import logging
from types import MappingProxyType

from floodcast.core.contracts import canonical_json_bytes, utc_now
from floodcast.core.errors import ErrorInfo, FloodcastError
from floodcast.core.registries import Registries
from floodcast.core.workflow_contracts import (
    DecisionOutcome,
    StepAttempt,
    StepContext,
    StepRecord,
    StepResult,
    StepSpec,
    StepStatus,
    WorkflowDefinition,
    WorkflowPlan,
    WorkflowRecord,
    WorkflowRequest,
    settled_status,
)
from floodcast.project.run_store import RunStore, record_references, verify_references


def _without_execution(step: StepSpec, dependencies: dict[str, StepResult]) -> StepResult | None:
    if step.dependency_mode == "all_succeeded":
        statuses = {result.status for result in dependencies.values()}
        if statuses & {StepStatus.FAILED, StepStatus.BLOCKED}:
            return StepResult(status=StepStatus.BLOCKED, reason_codes=("DEPENDENCY_FAILED",))
        if StepStatus.INDETERMINATE in statuses:
            return StepResult(
                status=StepStatus.INDETERMINATE, reason_codes=("DEPENDENCY_INDETERMINATE",)
            )
        if StepStatus.SKIPPED in statuses:
            return StepResult(status=StepStatus.SKIPPED, reason_codes=("DEPENDENCY_SKIPPED",))
    if step.condition is not None:
        result = dependencies[step.condition.decision_step]
        decision = result.decision
        if result.status != StepStatus.SUCCEEDED or decision is None:
            return StepResult(
                status=StepStatus.INDETERMINATE, reason_codes=("DECISION_UNAVAILABLE",)
            )
        if decision.outcome == DecisionOutcome.INDETERMINATE:
            return StepResult(
                status=StepStatus.INDETERMINATE,
                reason_codes=("DECISION_INDETERMINATE", *decision.reason_codes),
            )
        if decision.outcome != step.condition.expected:
            return StepResult(status=StepStatus.SKIPPED, reason_codes=("POLICY_NOT_SELECTED",))
    return None


class WorkflowOrchestrator:
    def __init__(
        self,
        *,
        registries: Registries,
        store: RunStore,
        code_identity: str,
        runtime_configuration_sha256: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self.registries = registries
        self.store = store
        self.code_identity = code_identity
        self.runtime_configuration_sha256 = runtime_configuration_sha256
        self.logger = logger or logging.getLogger("floodcast.workflow")

    def plan(self, definition: WorkflowDefinition, request: WorkflowRequest) -> WorkflowPlan:
        # Deep, validated snapshots: later caller/handler mutations cannot change the plan.
        definition = WorkflowDefinition.model_validate_json(definition.model_dump_json())
        request = WorkflowRequest.model_validate_json(request.model_dump_json())
        component_ids = sorted({step.component_id for step in definition.steps})
        manifests = [self.registries.steps.resolve(key).manifest for key in component_ids]
        # Conservative for this first slice: include all composed model adapters.
        manifests.extend(self.registries.model_adapters.manifests())
        manifests.extend(self.registries.acquisition_handlers.manifests())
        manifests.extend(self.registries.dataset_handlers.manifests())
        manifests.extend(self.registries.forcing_adapters.manifests())
        body = {
            "request": request.model_dump(mode="json"),
            "definition": definition.model_dump(mode="json"),
            "code_identity": self.code_identity,
            "runtime_configuration_sha256": self.runtime_configuration_sha256,
            "components": [manifest.model_dump(mode="json") for manifest in manifests],
        }
        return WorkflowPlan.model_validate(
            {
                **body,
                "fingerprint": hashlib.sha256(canonical_json_bytes(body)).hexdigest(),
            }
        )

    def run(
        self,
        definition: WorkflowDefinition,
        request: WorkflowRequest,
        *,
        resume: bool = False,
    ) -> WorkflowRecord:
        plan = self.plan(definition, request)
        bindings = {
            step.component_id: self.registries.steps.resolve(step.component_id)
            for step in plan.definition.steps
        }
        verify_references(plan.request.inputs)
        with self.store.lock(plan.request.run_id):
            if resume:
                record = self.store.load(plan.request.run_id)
                if record.plan != plan:
                    raise FloodcastError(
                        "IDENTITY_MISMATCH",
                        "workflow",
                        "Resume requires the same inputs, configuration, graph and components",
                    )
                verify_references(record_references(record))
                if record.status != "running":
                    # Final cycles, including failures, are immutable. Start a linked new run.
                    return record
            else:
                record = WorkflowRecord(
                    plan=plan,
                    steps=tuple(
                        StepRecord(step_id=s.step_id) for s in plan.definition.ordered_steps()
                    ),
                )
                self.store.create(record)
            for index, step in enumerate(plan.definition.ordered_steps()):
                current = record.steps[index]
                if current.result is not None:
                    continue
                if current.attempts and not step.retry_safe:
                    raise FloodcastError(
                        "CANCEL_UNCONFIRMED",
                        "workflow",
                        f"Interrupted step {step.step_id} is not replay-safe; reconcile its "
                        "external execution before creating a new run",
                    )
                dependencies = {
                    item.step_id: item.result for item in record.steps if item.step_id in step.needs
                }
                if any(value is None for value in dependencies.values()):
                    raise FloodcastError("INVALID_CONFIG", "workflow", "Unsettled dependency")
                outcome = _without_execution(step, dependencies)
                if outcome is not None:
                    record = self._replace_step(
                        record,
                        index,
                        StepRecord(
                            step_id=step.step_id,
                            result=outcome,
                        ),
                    )
                    continue
                number = len(current.attempts) + 1
                attempt = StepAttempt(number=number, started_at=utc_now())
                current = StepRecord(step_id=step.step_id, attempts=(*current.attempts, attempt))
                record = self._replace_step(record, index, current)
                work_dir = (
                    self.store.directory(plan.request.run_id)
                    / "steps"
                    / f"step-{step.step_id}"
                    / f"attempt-{number:04d}"
                )
                self.logger.info("Workflow %s step %s started", plan.request.run_id, step.step_id)
                try:
                    work_dir.mkdir(parents=True, exist_ok=False)
                    handler = bindings[step.component_id].factory()
                    context = StepContext(
                        request=plan.request.model_copy(deep=True),
                        step=step.model_copy(deep=True),
                        work_dir=work_dir,
                        dependencies=MappingProxyType(
                            {
                                key: value.model_copy(deep=True)
                                for key, value in dependencies.items()
                            }
                        ),
                        logger=self.logger,
                    )
                    outcome = handler.execute(context)
                    if not isinstance(outcome, StepResult):
                        raise TypeError("Step handlers must return StepResult, never bool/None")
                    outcome = StepResult.model_validate_json(outcome.model_dump_json())
                    verify_references(outcome.outputs)
                    if outcome.decision is not None:
                        verify_references(outcome.decision.evidence_refs)
                except Exception as exc:
                    error = (
                        exc.info
                        if isinstance(exc, FloodcastError)
                        else ErrorInfo(
                            code="VALIDATION_FAILED",
                            phase="workflow-step",
                            message=f"Step {step.step_id} raised {type(exc).__name__}",
                            cause=str(exc),
                        )
                    )
                    outcome = StepResult(
                        status=StepStatus.FAILED,
                        reason_codes=("STEP_EXCEPTION",),
                        error=error,
                    )
                # KeyboardInterrupt/SystemExit deliberately leave an unfinished attempt.
                finished = StepAttempt(
                    number=number,
                    started_at=attempt.started_at,
                    finished_at=utc_now(),
                    result=outcome,
                )
                current = StepRecord(
                    step_id=step.step_id,
                    attempts=(*current.attempts[:-1], finished),
                    result=outcome,
                )
                record = self._replace_step(record, index, current)
                self.logger.info(
                    "Workflow %s step %s: %s",
                    plan.request.run_id,
                    step.step_id,
                    outcome.status,
                )
            verify_references(record_references(record))
            record = WorkflowRecord(
                plan=record.plan,
                status=settled_status(record.steps),
                started_at=record.started_at,
                finished_at=utc_now(),
                steps=record.steps,
            )
            self.store.save(record)
            return record

    def _replace_step(
        self, record: WorkflowRecord, index: int, replacement: StepRecord
    ) -> WorkflowRecord:
        steps = list(record.steps)
        steps[index] = replacement
        updated = WorkflowRecord(
            plan=record.plan,
            status=record.status,
            started_at=record.started_at,
            finished_at=record.finished_at,
            steps=tuple(steps),
        )
        self.store.save(updated)
        return updated
