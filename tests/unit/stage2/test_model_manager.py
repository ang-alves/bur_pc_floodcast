import logging
from types import MappingProxyType
from uuid import uuid4

import pytest

from floodcast.core.contracts import RunRequest, RunResult, RunStatus, utc_now
from floodcast.core.errors import FloodcastError
from floodcast.core.registry import ComponentManifest
from floodcast.core.storage import evidence
from floodcast.core.workflow_contracts import StepContext, StepResult, StepSpec
from floodcast.models.model_manager import ModelManager


def run_result(request, status=RunStatus.SUCCEEDED):
    now = utc_now()
    complete = status in {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }
    return RunResult(
        run_id=request.run_id,
        status=status,
        submitted_at=now,
        started_at=now,
        finished_at=now if complete else None,
        exit_code=(0 if status == RunStatus.SUCCEEDED else 1) if complete else None,
    )


@pytest.fixture
def context(tmp_path, request_spec):
    work = tmp_path / "attempt"
    work.mkdir()
    return StepContext(
        request=request_spec,
        step=StepSpec(step_id="model", component_id="test"),
        work_dir=work,
        dependencies=MappingProxyType({}),
        logger=logging.getLogger("test"),
    )


@pytest.fixture
def adapter_setup(app):
    calls = []

    class Adapter:
        model_id = "summa"

        def prepare(self, context):
            calls.append("prepare")
            return RunRequest(
                model_id=self.model_id,
                arguments=("synthetic-control",),
                mounts=(),
                working_directory="/work",
            )

        def postprocess(self, context, result):
            calls.append("postprocess")
            path = context.work_dir / "synthetic-output.txt"
            path.write_text("Adapter test only; no SUMMA execution")
            return StepResult(reason_codes=("TEST_ONLY",), outputs=(evidence(path),))

    app.R.model_adapters.register(
        ComponentManifest(
            component_id="test.summa",
            contract_id="ffw.model-adapter/v1",
            implementation_version="1",
            source_revision="test-revision-1",
        ),
        Adapter,
    )
    return calls, Adapter


def test_delegates_existing_stage1_contracts_and_retains_provenance(app, adapter_setup, context):
    calls, _ = adapter_setup
    received = []

    def runtime(request):
        assert (context.work_dir / "model-request.json").is_file()
        received.append(request)
        calls.append("runtime")
        return run_result(request)

    manager = ModelManager(registries=app.R, run_model=runtime)
    result = manager.run("test.summa", context)
    assert calls == ["prepare", "runtime", "postprocess"]
    assert isinstance(received[0], RunRequest)
    assert len(result.outputs) == 3
    names = {item.path.name for item in result.outputs}
    assert {"model-request.json", "model-result.json"} <= names
    # A successful execution does not promote scientific validation.
    persisted = RunResult.model_validate_json((context.work_dir / "model-result.json").read_bytes())
    assert persisted.validation_status == "not_tested"


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
        RunStatus.TERMINATION_UNCONFIRMED,
        RunStatus.RUNNING,
        RunStatus.QUEUED,
    ],
)
def test_no_postprocessing_after_failed_or_unconfirmed_execution(
    app,
    adapter_setup,
    context,
    status,
):
    calls, _ = adapter_setup
    manager = ModelManager(registries=app.R, run_model=lambda request: run_result(request, status))
    with pytest.raises(FloodcastError) as caught:
        manager.run("test.summa", context)
    assert calls == ["prepare"]
    expected = "MODEL_FAILED" if status.terminal else "CANCEL_UNCONFIRMED"
    assert caught.value.code == expected
    assert len(caught.value.evidence_paths) == 2
    assert all(path.is_file() for path in caught.value.evidence_paths)


def test_runtime_result_must_belong_to_prepared_request(app, adapter_setup, context):
    calls, _ = adapter_setup

    def runtime(request):
        return run_result(request).model_copy(update={"run_id": uuid4()})

    with pytest.raises(FloodcastError, match="run ID mismatch"):
        ModelManager(registries=app.R, run_model=runtime).run("test.summa", context)
    assert calls == ["prepare"]


def test_adapter_cannot_hide_wrong_model_request(app, adapter_setup, context, monkeypatch):
    _, adapter = adapter_setup
    monkeypatch.setattr(
        adapter,
        "prepare",
        lambda self, ctx: RunRequest(
            model_id="fluxos",
            arguments=(),
            mounts=(),
            working_directory="/work",
        ),
    )
    received = []
    with pytest.raises(FloodcastError, match="Adapter/model mismatch"):
        ModelManager(registries=app.R, run_model=received.append).run("test.summa", context)
    assert not received


def test_postprocessor_cannot_rewrite_process_provenance(app, adapter_setup, context, monkeypatch):
    _, adapter = adapter_setup

    def postprocess(self, ctx, result):
        (ctx.work_dir / "model-result.json").write_text("changed")
        return StepResult(reason_codes=("TEST_ONLY",))

    monkeypatch.setattr(adapter, "postprocess", postprocess)
    with pytest.raises(FloodcastError, match="Provenance changed"):
        ModelManager(registries=app.R, run_model=run_result).run("test.summa", context)
