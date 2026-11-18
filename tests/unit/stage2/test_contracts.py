from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from floodcast.core.errors import ErrorInfo
from floodcast.core.workflow_contracts import (
    DecisionCondition,
    DecisionOutcome,
    DecisionResult,
    StepResult,
    StepSpec,
    WorkflowDefinition,
    WorkflowRequest,
)


def definition(*steps):
    return WorkflowDefinition(workflow_id="test", version="1", steps=steps)


def step(name, *needs, **kwargs):
    return StepSpec(step_id=name, component_id="test", needs=needs, **kwargs)


def test_topological_order_not_diagram_position():
    graph = definition(step("c", "b"), step("a"), step("b", "a"), step("independent"))
    assert [s.step_id for s in graph.ordered_steps()] == ["a", "independent", "b", "c"]


@pytest.mark.parametrize(
    "steps",
    [
        (step("a"), step("a")),
        (step("a", "missing"),),
        (step("a", "b"), step("b", "a")),
    ],
)
def test_invalid_graph(steps):
    with pytest.raises(ValidationError):
        definition(*steps)


def test_empty_graph_rejected():
    with pytest.raises(ValidationError):
        definition()


@pytest.mark.parametrize("needs", [("a",), ("b", "b")])
def test_self_or_duplicate_dependency_rejected(needs):
    with pytest.raises(ValidationError):
        step("a", *needs)


def test_decision_dependency_is_explicit():
    with pytest.raises(ValidationError):
        step("hydraulics", condition=DecisionCondition(decision_step="decision"))


def test_condition_cannot_use_unknown_as_activation():
    with pytest.raises(ValidationError):
        DecisionCondition(decision_step="decision", expected="indeterminate")


@pytest.mark.parametrize("outcome", list(DecisionOutcome))
def test_decision_cannot_silently_become_a_boolean(outcome):
    result = DecisionResult(
        outcome=outcome,
        policy_id="test",
        policy_version="1",
        reason_codes=("TEST_ONLY",),
    )
    with pytest.raises(TypeError, match="explicitly"):
        bool(result)


def test_failure_requires_error_and_success_cannot_hide_error():
    with pytest.raises(ValidationError):
        StepResult(status="failed", reason_codes=("BROKEN",))
    with pytest.raises(ValidationError):
        StepResult(
            reason_codes=("BROKEN",),
            error=ErrorInfo(
                code="VALIDATION_FAILED",
                phase="test",
                message="failed",
            ),
        )


def test_unknown_contract_fields_fail():
    with pytest.raises(ValidationError):
        step("a", threshold=42)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_configuration_rejected(value):
    with pytest.raises(ValidationError):
        step("a", configuration={"value": value})


def test_forecast_requires_cycle_and_t0():
    with pytest.raises(ValidationError):
        WorkflowRequest(domain_id="test", purpose="forecast")


def test_verification_requires_lineage_and_hashed_inputs():
    with pytest.raises(ValidationError):
        WorkflowRequest(domain_id="test", purpose="verification", parent_run_id=uuid4())


def test_naive_time_rejected():
    with pytest.raises(ValidationError):
        WorkflowRequest(domain_id="test", purpose="demo", issued_at=datetime(2026, 11, 17))


def test_utc_time_supported():
    request = WorkflowRequest(
        domain_id="test",
        purpose="forecast",
        cycle_time=datetime(2026, 11, 17, tzinfo=UTC),
        t0=datetime(2026, 11, 17, tzinfo=UTC),
    )
    assert request.cycle_time == request.t0


def test_external_steps_are_not_replay_safe_by_default():
    assert step("a").retry_safe is False
