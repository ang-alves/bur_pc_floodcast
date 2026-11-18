from pathlib import Path

import pytest

from floodcast.core.config import RuntimeConfig
from floodcast.core.registry import ComponentManifest
from floodcast.core.workflow_contracts import StepResult, WorkflowRequest
from floodcast.project import Floodcast


@pytest.fixture
def app(tmp_path: Path) -> Floodcast:
    return Floodcast(RuntimeConfig(data_root=tmp_path / "data"), code_identity="test-revision-1")


@pytest.fixture
def request_spec() -> WorkflowRequest:
    return WorkflowRequest(domain_id="synthetic-domain", purpose="demo")


@pytest.fixture
def register(app):
    def add(name, callback, *, version="1", revision="test-revision-1"):
        class Handler:
            def execute(self, context):
                return callback(context)

        app.R.steps.register(
            ComponentManifest(
                component_id=name,
                contract_id="ffw.step/v1",
                implementation_version=version,
                source_revision=revision,
            ),
            Handler,
        )

    return add


@pytest.fixture
def success() -> StepResult:
    return StepResult(reason_codes=("TEST_ONLY",))
