"""Select an unambiguous compatible T0 package; do not simulate or update it."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from floodcast.core.errors import FloodcastError
from floodcast.core.state_contracts import (
    HydrologicalState,
    StateModelIdentity,
    StateRequirements,
)
from floodcast.project.run_store import verify_references


class StateService:
    @staticmethod
    def _compatible(state: HydrologicalState, required: StateRequirements) -> bool:
        if (state.domain_id, state.domain_sha256, state.valid_at) != (
            required.domain_id,
            required.domain_sha256,
            required.t0,
        ):
            return False
        actual = {
            item.model_id: StateModelIdentity.model_validate(item.model_dump(exclude={"restart"}))
            for item in state.models
        }
        expected = {item.model_id: item for item in required.models}
        return actual == expected

    def validate(self, state: HydrologicalState, required: StateRequirements) -> HydrologicalState:
        if not self._compatible(state, required):
            raise FloodcastError(
                "IDENTITY_MISMATCH", "state", "Restart identity or valid time differs from T0"
            )
        verify_references(tuple(model.restart for model in state.models))
        return state

    def select(
        self,
        states: Iterable[HydrologicalState],
        required: StateRequirements,
        *,
        state_id: UUID | None = None,
    ) -> HydrologicalState:
        candidates = [
            state
            for state in states
            if (state_id is None or state.state_id == state_id)
            and self._compatible(state, required)
        ]
        if len(candidates) != 1:
            raise FloodcastError(
                "VALIDATION_FAILED",
                "state",
                f"Expected one compatible state package, found {len(candidates)}; "
                "select an explicit state_id when ambiguous",
            )
        return self.validate(candidates[0], required)
