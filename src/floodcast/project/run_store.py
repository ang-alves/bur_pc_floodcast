"""Technical workflow persistence, separate from installations and model states."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from filelock import FileLock, Timeout
from pydantic import ValidationError

from floodcast.core.contracts import EvidenceRef
from floodcast.core.errors import FloodcastError
from floodcast.core.storage import atomic_json, evidence, reject_links
from floodcast.core.workflow_contracts import WorkflowRecord


def verify_references(references: Iterable[EvidenceRef]) -> None:
    """Stream hashes rather than loading large forcing/restart files into memory."""
    for reference in references:
        reject_links(reference.path)
        if not reference.path.is_file():
            raise FloodcastError(
                "ARTIFACT_MISSING", "workflow", f"Missing regular file: {reference.path}"
            )
        if evidence(reference.path).sha256 != reference.sha256:
            raise FloodcastError(
                "IDENTITY_MISMATCH", "workflow", f"Content changed: {reference.path}"
            )


def record_references(record: WorkflowRecord) -> tuple[EvidenceRef, ...]:
    references = list(record.plan.request.inputs)
    for step in record.steps:
        if step.result is not None:
            references.extend(step.result.outputs)
            if step.result.decision is not None:
                references.extend(step.result.decision.evidence_refs)
    return tuple(references)


class RunStore:
    """Single-writer local filesystem store; shared HPC filesystems are unverified."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root != root.resolve():
            raise FloodcastError("INVALID_CONFIG", "workflow", "Store root must be resolved")
        self.root = root

    def directory(self, run_id: UUID) -> Path:
        if not isinstance(run_id, UUID):
            raise FloodcastError("INVALID_CONFIG", "workflow", "run_id must be a UUID")
        return self.root / str(run_id)

    def manifest_path(self, run_id: UUID) -> Path:
        return self.directory(run_id) / "manifest.json"

    @contextmanager
    def lock(self, run_id: UUID) -> Iterator[None]:
        self.directory(run_id)  # Validate before using the ID in a filesystem path.
        locks = self.root / ".locks"
        reject_links(locks)
        locks.mkdir(parents=True, exist_ok=True)
        lock_path = locks / f"{run_id}.lock"
        reject_links(lock_path)
        lock = FileLock(lock_path, timeout=0)
        try:
            lock.acquire()
        except Timeout as exc:
            raise FloodcastError(
                "REGISTRY_BUSY", "workflow", "Another process holds this workflow run"
            ) from exc
        try:
            yield
        finally:
            lock.release()

    def create(self, record: WorkflowRecord) -> None:
        directory = self.directory(record.plan.request.run_id)
        reject_links(directory)
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise FloodcastError(
                "REGISTRY_CONFLICT", "workflow", "Run already exists; use explicit resume"
            ) from exc
        self.save(record)

    def save(self, record: WorkflowRecord) -> None:
        path = self.manifest_path(record.plan.request.run_id)
        reject_links(path)
        # Revalidate even an instance created with Pydantic's unchecked model_copy.
        record = WorkflowRecord.model_validate_json(record.model_dump_json())
        if path.exists():
            previous = self.load(record.plan.request.run_id)
            if previous.finished_at is not None:
                if previous != record:
                    raise FloodcastError(
                        "REGISTRY_CONFLICT", "workflow", "Final workflow records are immutable"
                    )
                return
        atomic_json(path, record)

    def load(self, run_id: UUID) -> WorkflowRecord:
        path = self.manifest_path(run_id)
        reject_links(path)
        try:
            record = WorkflowRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as exc:
            raise FloodcastError(
                "VALIDATION_FAILED", "workflow", f"Cannot read workflow record: {path}", cause=exc
            ) from exc
        if record.plan.request.run_id != run_id:
            raise FloodcastError("IDENTITY_MISMATCH", "workflow", "Manifest run ID differs")
        return record
