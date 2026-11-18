"""Stage 2 contracts, additive to the unchanged Stage 1 execution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import UUID, uuid4

from pydantic import Field, JsonValue, StrictBool, StrictStr, field_validator, model_validator

from floodcast.core.contracts import (
    Contract,
    EvidenceRef,
    Identifier,
    PositiveInt,
    Sha256,
    UtcTimestamp,
    canonical_json_bytes,
    utc_now,
)
from floodcast.core.errors import ErrorInfo
from floodcast.core.registry import ComponentManifest


class DecisionOutcome(StrEnum):
    ACTIVATE = "activate"
    DO_NOT_ACTIVATE = "do_not_activate"
    INDETERMINATE = "indeterminate"


class DecisionResult(Contract):
    """A policy conclusion, not a Boolean and not a claim of absence of risk."""

    outcome: DecisionOutcome
    policy_id: Identifier
    policy_version: StrictStr = Field(min_length=1)
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)
    evidence_refs: tuple[EvidenceRef, ...] = ()
    selected_scenarios: tuple[Identifier, ...] = ()

    def __bool__(self) -> bool:
        raise TypeError("Compare DecisionResult.outcome explicitly; indeterminate is not False")


class StepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    INDETERMINATE = "indeterminate"
    BLOCKED = "blocked"


class StepResult(Contract):
    status: StepStatus = StepStatus.SUCCEEDED
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)
    outputs: tuple[EvidenceRef, ...] = ()
    decision: DecisionResult | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        if (self.status == StepStatus.FAILED) != (self.error is not None):
            raise ValueError("Only failed steps require an error")
        if self.decision is not None and self.status != StepStatus.SUCCEEDED:
            raise ValueError("A policy result belongs to a successfully evaluated step")
        return self


class DecisionCondition(Contract):
    decision_step: Identifier
    expected: Literal["activate", "do_not_activate"] = "activate"


class StepSpec(Contract):
    step_id: Identifier = Field(max_length=80)
    component_id: Identifier
    needs: tuple[Identifier, ...] = ()
    dependency_mode: Literal["all_succeeded", "all_settled"] = "all_succeeded"
    condition: DecisionCondition | None = None
    configuration: dict[StrictStr, JsonValue] = Field(default_factory=dict)
    # False is essential for external jobs whose termination is not yet confirmed.
    retry_safe: StrictBool = False

    @field_validator("configuration")
    @classmethod
    def finite_configuration(cls, value):
        canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def explicit_dependencies(self) -> Self:
        if len(set(self.needs)) != len(self.needs) or self.step_id in self.needs:
            raise ValueError("Dependencies must be unique and must not include this step")
        if self.condition is not None and self.condition.decision_step not in self.needs:
            raise ValueError("The condition's decision step must be an explicit dependency")
        return self


class WorkflowDefinition(Contract):
    workflow_id: Identifier
    version: StrictStr = Field(min_length=1)
    steps: tuple[StepSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_graph(self) -> Self:
        ids = [step.step_id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate step ID")
        if any(set(step.needs) - set(ids) for step in self.steps):
            raise ValueError("Unknown dependency")
        self.ordered_steps()
        return self

    def ordered_steps(self) -> tuple[StepSpec, ...]:
        """Stable topological ordering, preserving declaration order where possible."""
        remaining = list(self.steps)
        ordered: list[StepSpec] = []
        done: set[str] = set()
        while remaining:
            ready = [step for step in remaining if set(step.needs) <= done]
            if not ready:
                raise ValueError("Workflow dependencies contain a cycle")
            for step in ready:
                ordered.append(step)
                done.add(step.step_id)
                remaining.remove(step)
        return tuple(ordered)


class WorkflowRequest(Contract):
    run_id: UUID = Field(default_factory=uuid4)
    domain_id: Identifier
    purpose: Literal["forecast", "state_update", "verification", "demo"]
    issued_at: UtcTimestamp = Field(default_factory=utc_now)
    cycle_time: UtcTimestamp | None = None
    t0: UtcTimestamp | None = None
    parent_run_id: UUID | None = None
    inputs: tuple[EvidenceRef, ...] = ()
    configuration: dict[StrictStr, JsonValue] = Field(default_factory=dict)

    @field_validator("configuration")
    @classmethod
    def finite_configuration(cls, value):
        canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def valid_purpose(self) -> Self:
        if self.purpose == "forecast" and (self.cycle_time is None or self.t0 is None):
            raise ValueError("A forecast requires explicit cycle_time and T0")
        if self.purpose == "verification" and (self.parent_run_id is None or not self.inputs):
            raise ValueError("Verification requires the original run ID and hashed input evidence")
        if self.parent_run_id == self.run_id:
            raise ValueError("A run cannot be its own parent")
        paths = [ref.path for ref in self.inputs]
        if len(set(paths)) != len(paths):
            raise ValueError("Duplicate input path")
        return self


class StepAttempt(Contract):
    number: PositiveInt
    started_at: UtcTimestamp
    finished_at: UtcTimestamp | None = None
    result: StepResult | None = None

    @model_validator(mode="after")
    def consistent_attempt(self) -> Self:
        if (self.result is None) != (self.finished_at is None):
            raise ValueError("An unfinished attempt cannot claim a result")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("Attempt finishes before it starts")
        return self


class StepRecord(Contract):
    step_id: Identifier
    attempts: tuple[StepAttempt, ...] = ()
    result: StepResult | None = None

    @model_validator(mode="after")
    def consistent_history(self) -> Self:
        if [a.number for a in self.attempts] != list(range(1, len(self.attempts) + 1)):
            raise ValueError("Attempt sequence is not contiguous")
        if self.attempts and self.result != self.attempts[-1].result:
            raise ValueError("Current result differs from the last attempt")
        return self


def settled_status(steps: tuple[StepRecord, ...]) -> str:
    results = [step.result for step in steps]
    if any(result is None for result in results):
        raise ValueError("Cannot finish a workflow with unsettled steps")
    if any(result.status in {StepStatus.FAILED, StepStatus.BLOCKED} for result in results):
        return "failed"
    if any(
        result.status == StepStatus.INDETERMINATE
        or (
            result.decision is not None and result.decision.outcome == DecisionOutcome.INDETERMINATE
        )
        for result in results
    ):
        return "indeterminate"
    return "succeeded"


class WorkflowPlan(Contract):
    request: WorkflowRequest
    definition: WorkflowDefinition
    code_identity: StrictStr = Field(min_length=1)
    runtime_configuration_sha256: Sha256
    components: tuple[ComponentManifest, ...]
    fingerprint: Sha256


class WorkflowRecord(Contract):
    plan: WorkflowPlan
    status: Literal["running", "succeeded", "failed", "indeterminate"] = "running"
    started_at: UtcTimestamp = Field(default_factory=utc_now)
    finished_at: UtcTimestamp | None = None
    steps: tuple[StepRecord, ...]

    @model_validator(mode="after")
    def complete_record(self) -> Self:
        expected = [step.step_id for step in self.plan.definition.ordered_steps()]
        if [step.step_id for step in self.steps] != expected:
            raise ValueError("Record steps do not match the plan")
        if (self.status == "running") != (self.finished_at is None):
            raise ValueError("Workflow status and completion timestamp differ")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("Workflow finishes before it starts")
        if self.status != "running" and self.status != settled_status(self.steps):
            raise ValueError("Workflow status does not agree with its settled step results")
        return self


@dataclass(frozen=True)
class StepContext:
    request: WorkflowRequest
    step: StepSpec
    work_dir: Path
    dependencies: Mapping[str, StepResult]
    logger: Logger


class StepHandler(Protocol):
    def execute(self, context: StepContext) -> StepResult: ...
