"""Adapters translate model data; Stage 1 still owns process execution."""

from __future__ import annotations

from typing import Protocol

from floodcast.core.contracts import ModelId, RunRequest, RunResult
from floodcast.core.workflow_contracts import StepContext, StepResult


class ModelAdapter(Protocol):
    model_id: ModelId

    def prepare(self, context: StepContext) -> RunRequest: ...

    def postprocess(self, context: StepContext, result: RunResult) -> StepResult: ...
