from pathlib import Path

import pytest

from floodcast.core.errors import FloodcastError
from floodcast.core.registry import ComponentManifest
from floodcast.core.storage import evidence
from floodcast.core.workflow_contracts import (
    DecisionCondition,
    DecisionResult,
    StepResult,
    StepSpec,
    WorkflowDefinition,
    WorkflowRequest,
)
from floodcast.project import Floodcast


def graph(*steps):
    return WorkflowDefinition(workflow_id="test", version="1", steps=steps)


def step(name, *needs, component=None, **kwargs):
    return StepSpec(step_id=name, component_id=component or name, needs=needs, **kwargs)


def indexed(record):
    return {item.step_id: item for item in record.steps}


def test_plan_is_side_effect_free(app, request_spec):
    constructed = []
    app.R.steps.register(
        ComponentManifest(
            component_id="a",
            contract_id="ffw.step/v1",
            implementation_version="1",
            source_revision="1",
        ),
        lambda: constructed.append(1),
    )
    plan = app.plan(graph(step("a")), request_spec)
    assert len(plan.fingerprint) == 64
    assert not constructed
    assert not app.config.data_root.exists()


def test_missing_component_fails_before_creating_run(app, request_spec):
    with pytest.raises(FloodcastError, match="Unknown"):
        app.run(graph(step("a")), request_spec)
    assert not app.config.data_root.exists()


@pytest.mark.parametrize(
    "outcome,expected_status,hydraulic_status,executed",
    [
        ("activate", "succeeded", "succeeded", True),
        ("do_not_activate", "succeeded", "skipped", False),
        ("indeterminate", "indeterminate", "indeterminate", False),
    ],
)
def test_three_way_policy_and_multiple_model_steps(
    app,
    register,
    request_spec,
    success,
    outcome,
    expected_status,
    hydraulic_status,
    executed,
):
    calls = []
    register("models", lambda ctx: calls.append(ctx.step.step_id) or success)
    register(
        "decision",
        lambda ctx: StepResult(
            reason_codes=("POLICY_EVALUATED",),
            decision=(
                DecisionResult(
                    outcome=outcome,
                    policy_id="test",
                    policy_version="1",
                    reason_codes=("TEST_ONLY",),
                )
            ),
        ),
    )
    register("report", lambda ctx: calls.append("report") or success)
    definition = graph(
        step("hydrology", component="models"),
        step("decision", "hydrology"),
        step(
            "hydraulics",
            "decision",
            component="models",
            condition=DecisionCondition(decision_step="decision"),
        ),
        step("report", "hydraulics", dependency_mode="all_settled"),
    )
    record = app.run(definition, request_spec)
    assert record.status == expected_status
    assert indexed(record)["hydraulics"].result.status == hydraulic_status
    assert ("hydraulics" in calls) is executed
    assert calls[-1] == "report"
    if not executed:
        assert not indexed(record)["hydraulics"].attempts


def test_missing_decision_does_not_mean_no_risk(app, register, request_spec, success):
    calls = []
    register("decision", lambda ctx: success)
    register("hydraulics", lambda ctx: calls.append(1) or success)
    record = app.run(
        graph(
            step("decision"),
            step("hydraulics", "decision", condition=DecisionCondition(decision_step="decision")),
        ),
        request_spec,
    )
    assert record.status == "indeterminate"
    assert not calls
    assert indexed(record)["hydraulics"].result.reason_codes == ("DECISION_UNAVAILABLE",)


def test_failure_blocks_dependents_but_not_state_maintenance_or_reporting(
    app,
    register,
    request_spec,
    success,
):
    calls = []

    def fail(ctx):
        raise RuntimeError("provider unavailable")

    register("forecast", fail)
    for name in ("hydrology", "state_update", "report"):
        register(name, lambda ctx: calls.append(ctx.step.step_id) or success)
    record = app.run(
        graph(
            step("forecast"),
            step("hydrology", "forecast"),
            step("state_update"),
            step("report", "hydrology", "state_update", dependency_mode="all_settled"),
        ),
        request_spec,
    )
    assert record.status == "failed"
    records = indexed(record)
    assert records["forecast"].result.status == "failed"
    assert records["hydrology"].result.status == "blocked"
    assert records["state_update"].result.status == "succeeded"
    assert calls == ["state_update", "report"]
    assert app.inspect(request_spec.run_id) == record


def test_skip_propagation_has_a_reason(app, register, request_spec, success):
    calls = []
    register("a", lambda ctx: StepResult(status="skipped", reason_codes=("NOT_SELECTED",)))
    register("b", lambda ctx: calls.append(1) or success)
    record = app.run(graph(step("a"), step("b", "a")), request_spec)
    assert indexed(record)["b"].result.reason_codes == ("DEPENDENCY_SKIPPED",)
    assert not calls


def test_indeterminate_propagates_without_execution(app, register, request_spec, success):
    register("a", lambda ctx: StepResult(status="indeterminate", reason_codes=("MISSING_DATA",)))
    register("b", lambda ctx: success)
    record = app.run(graph(step("a"), step("b", "a")), request_spec)
    assert record.status == "indeterminate"
    assert not indexed(record)["b"].attempts


@pytest.mark.parametrize("invalid", [None, False, {}, "success"])
def test_invalid_handler_return_is_a_technical_failure(app, register, request_spec, invalid):
    register("a", lambda ctx: invalid)
    record = app.run(graph(step("a")), request_spec)
    assert record.status == "failed"
    assert indexed(record)["a"].result.error is not None


def test_no_overwrite_without_explicit_resume(app, register, request_spec, success):
    calls = []
    register("a", lambda ctx: calls.append(1) or success)
    definition = graph(step("a"))
    first = app.run(definition, request_spec)
    path = app.run_store.manifest_path(request_spec.run_id)
    before = path.read_bytes()
    with pytest.raises(FloodcastError, match="already exists"):
        app.run(definition, request_spec)
    assert app.run(definition, request_spec, resume=True) == first
    assert path.read_bytes() == before
    assert calls == [1]


def test_terminal_failure_is_not_silently_retried(app, register, request_spec):
    calls = []

    def fail(ctx):
        calls.append(1)
        raise RuntimeError("failed")

    register("a", fail)
    definition = graph(step("a", retry_safe=True))
    first = app.run(definition, request_spec)
    assert app.run(definition, request_spec, resume=True) == first
    assert len(calls) == 1


def test_safe_interruption_resume_preserves_completed_steps_and_attempt_history(
    app,
    register,
    request_spec,
    success,
):
    calls = []

    def interrupt_once(ctx):
        calls.append("b")
        if calls.count("b") == 1:
            raise KeyboardInterrupt
        return success

    register("a", lambda ctx: calls.append("a") or success)
    register("b", interrupt_once)
    definition = graph(step("a"), step("b", "a", retry_safe=True))
    with pytest.raises(KeyboardInterrupt):
        app.run(definition, request_spec)
    assert app.inspect(request_spec.run_id).status == "running"
    result = app.run(definition, request_spec, resume=True)
    assert result.status == "succeeded"
    assert calls == ["a", "b", "b"]
    attempts = indexed(result)["b"].attempts
    assert len(attempts) == 2
    assert attempts[0].finished_at is None and attempts[0].result is None
    assert attempts[1].result.status == "succeeded"


def test_external_interrupted_step_is_not_relaunched(app, register, request_spec):
    calls = []

    def interrupted(ctx):
        calls.append(1)
        raise KeyboardInterrupt

    register("a", interrupted)
    definition = graph(step("a"))
    with pytest.raises(KeyboardInterrupt):
        app.run(definition, request_spec)
    with pytest.raises(FloodcastError, match="not replay-safe"):
        app.run(definition, request_spec, resume=True)
    assert calls == [1]


@pytest.mark.parametrize("change", ["configuration", "graph", "code", "component"])
def test_changed_identity_prevents_resume(app, register, request_spec, success, change):
    register("a", lambda ctx: success)
    definition = graph(step("a"))
    app.run(definition, request_spec)
    if change == "configuration":
        request_spec = request_spec.model_copy(update={"configuration": {"new": True}})
    elif change == "graph":
        definition = graph(step("a", retry_safe=True))
    elif change == "code":
        app.orchestrator.code_identity = "different-revision"
    else:
        second = Floodcast(app.config, code_identity="test-revision-1")
        entry = app.R.steps.resolve("a")
        second.R.steps.register(
            entry.manifest.model_copy(
                update={
                    "implementation_version": "2",
                }
            ),
            entry.factory,
        )
        app = second
    with pytest.raises(FloodcastError, match="same inputs"):
        app.run(definition, request_spec, resume=True)


def test_input_hash_checked_before_any_step(app, register, success, tmp_path):
    path = tmp_path / "input.bin"
    path.write_bytes(b"original")
    req = WorkflowRequest(domain_id="synthetic", purpose="demo", inputs=(evidence(path),))
    path.write_bytes(b"changed")
    calls = []
    register("a", lambda ctx: calls.append(1) or success)
    with pytest.raises(FloodcastError, match="Content changed"):
        app.run(graph(step("a")), req)
    assert not calls
    assert not app.config.data_root.exists()


@pytest.mark.parametrize("damage", ["change", "remove"])
def test_completed_output_is_verified_on_resume(app, register, request_spec, damage):
    def produce(ctx):
        path = ctx.work_dir / "output.txt"
        path.write_text("original")
        return StepResult(reason_codes=("TEST_ONLY",), outputs=(evidence(path),))

    register("a", produce)
    definition = graph(step("a"))
    result = app.run(definition, request_spec)
    path = indexed(result)["a"].result.outputs[0].path
    if damage == "change":
        path.write_text("changed")
    else:
        path.unlink()
    with pytest.raises(FloodcastError):
        app.run(definition, request_spec, resume=True)


def test_manifest_corruption_is_not_a_cache_miss(app, register, request_spec, success):
    register("a", lambda ctx: success)
    definition = graph(step("a"))
    app.run(definition, request_spec)
    app.run_store.manifest_path(request_spec.run_id).write_text("broken JSON")
    with pytest.raises(FloodcastError, match="Cannot read"):
        app.run(definition, request_spec, resume=True)


def test_single_writer_lock(app, register, request_spec, success):
    register("a", lambda ctx: success)
    with app.run_store.lock(request_spec.run_id):
        with pytest.raises(FloodcastError, match="Another process"):
            app.run(graph(step("a")), request_spec)


def test_context_mutation_cannot_rewrite_plan_or_parent_result(
    app,
    register,
    request_spec,
    success,
):
    def mutate(ctx):
        ctx.request.configuration["tampered"] = True
        ctx.step.configuration["tampered"] = True
        with pytest.raises(TypeError):
            ctx.dependencies["fake"] = success
        return success

    register("a", mutate)
    result = app.run(graph(step("a")), request_spec)
    assert result.plan.request.configuration == {}
    assert result.plan.definition.steps[0].configuration == {}


def test_verification_is_a_new_linked_run_and_original_is_unchanged(
    app,
    register,
    request_spec,
    success,
):
    register("a", lambda ctx: success)
    definition = graph(step("a"))
    original = app.run(definition, request_spec)
    path = app.run_store.manifest_path(original.plan.request.run_id)
    before = path.read_bytes()
    verification = WorkflowRequest(
        domain_id=request_spec.domain_id,
        purpose="verification",
        parent_run_id=request_spec.run_id,
        inputs=(evidence(path),),
    )
    after = app.run(definition, verification)
    assert after.plan.request.parent_run_id == request_spec.run_id
    assert after.plan.request.run_id != request_spec.run_id
    assert path.read_bytes() == before


def test_absolute_input_symlink_is_rejected(app, register, success, tmp_path: Path):
    target = tmp_path / "target.txt"
    target.write_text("value")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Host cannot create symlinks")
    ref = evidence(target).model_copy(update={"path": link})
    req = WorkflowRequest(domain_id="synthetic", purpose="demo", inputs=(ref,))
    register("a", lambda ctx: success)
    with pytest.raises(FloodcastError, match="Linked"):
        app.run(graph(step("a")), req)


def test_finished_record_cannot_be_rewritten_through_store(
    app,
    register,
    request_spec,
    success,
):
    register("a", lambda ctx: success)
    record = app.run(graph(step("a")), request_spec)
    changed = record.model_copy(update={"started_at": request_spec.issued_at})
    with pytest.raises(FloodcastError, match="immutable"):
        app.run_store.save(changed)


def test_false_success_in_corrupt_manifest_is_rejected(app, register, request_spec):
    import json

    register("a", lambda ctx: StepResult(status="indeterminate", reason_codes=("MISSING",)))
    app.run(graph(step("a")), request_spec)
    path = app.run_store.manifest_path(request_spec.run_id)
    payload = json.loads(path.read_text())
    payload["status"] = "succeeded"
    path.write_text(json.dumps(payload))
    with pytest.raises(FloodcastError, match="Cannot read"):
        app.inspect(request_spec.run_id)


@pytest.mark.parametrize("problem", ["wrong_domain", "unrelated_input", "unfinished_parent"])
def test_verification_parent_is_checked(app, register, request_spec, success, tmp_path, problem):
    def handler(ctx):
        if problem == "unfinished_parent":
            raise KeyboardInterrupt
        return success

    register("a", handler)
    definition = graph(step("a"))
    if problem == "unfinished_parent":
        with pytest.raises(KeyboardInterrupt):
            app.run(definition, request_spec)
    else:
        app.run(definition, request_spec)
    path = app.run_store.manifest_path(request_spec.run_id)
    if problem == "unrelated_input":
        path = tmp_path / "unrelated.txt"
        path.write_text("Not the original forecast manifest")
    request = WorkflowRequest(
        domain_id="other" if problem == "wrong_domain" else request_spec.domain_id,
        purpose="verification",
        parent_run_id=request_spec.run_id,
        inputs=(evidence(path),),
    )
    with pytest.raises(FloodcastError, match="Verification"):
        app.run(definition, request)
