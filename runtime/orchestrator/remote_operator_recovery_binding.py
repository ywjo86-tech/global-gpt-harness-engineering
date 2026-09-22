"""Durable non-authoritative binding between an OCP delivery and canonical execution.

The store never declares Harness completion.  It records the exact remote identity that
was about to enter the canonical registered-Full-Plan resume path so a later process can
ask canonical state whether that exact action completed.  Only canonical state may answer
that question.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import (
    DurableIOError,
    canonical_json_bytes,
    durable_json_load,
    durable_json_save,
    sha256_bytes,
)
from .remote_operator_envelope import RemoteOperatorEnvelopeV2


_BINDING_SCHEMA = "orchestration.remote-execution-binding.v1"
_STATUSES = frozenset({"PENDING", "OUTBOXED", "PROJECTED"})


class RemoteExecutionBindingError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 200 or "/" in text or "\\" in text or ".." in text:
        raise RemoteExecutionBindingError(f"unsafe {label}")
    return text


def _digest(value: object, label: str, *, lengths: tuple[int, ...] = (64,)) -> str:
    text = str(value or "")
    if len(text) not in lengths or any(ch not in "0123456789abcdef" for ch in text):
        raise RemoteExecutionBindingError(f"invalid {label}")
    return text


@dataclass(frozen=True, slots=True)
class RemoteExecutionBindingV1:
    message_id: str
    source_message_id: str
    control_content_sha256: str
    envelope_sha256: str
    directive_digest: str
    project_id: str
    run_id: str
    gate_id: str
    task_id: str
    task_execution_id: str
    expected_state_sha256: str
    expected_owner_epoch: int
    expected_source_head: str
    expected_runtime_release_digest: str
    status: str
    projection_id: str
    bound_at: str
    updated_at: str
    binding_sha256: str = ""
    schema_version: str = _BINDING_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.message_id, "message ID"),
            (self.source_message_id, "source message ID"),
            (self.project_id, "project ID"),
            (self.run_id, "run ID"),
            (self.gate_id, "Gate ID"),
            (self.task_id, "task ID"),
            (self.task_execution_id, "task execution ID"),
        ):
            _safe_id(value, label)
        _digest(self.control_content_sha256, "control content digest")
        _digest(self.envelope_sha256, "envelope digest")
        _digest(self.directive_digest, "directive digest")
        _digest(self.expected_state_sha256, "expected state digest")
        _digest(self.expected_source_head, "expected source HEAD", lengths=(40, 64))
        _digest(self.expected_runtime_release_digest, "runtime release digest")
        if isinstance(self.expected_owner_epoch, bool) or int(self.expected_owner_epoch) <= 0:
            raise RemoteExecutionBindingError("invalid expected owner epoch")
        if self.status not in _STATUSES:
            raise RemoteExecutionBindingError("invalid recovery binding status")
        if self.status == "OUTBOXED" and not self.projection_id:
            raise RemoteExecutionBindingError("OUTBOXED binding requires projection ID")
        if self.projection_id:
            _safe_id(self.projection_id, "projection ID")
        if self.schema_version != _BINDING_SCHEMA:
            raise RemoteExecutionBindingError("binding schema mismatch")
        if not self.bound_at or not self.updated_at:
            raise RemoteExecutionBindingError("binding timestamps are required")
        if self.binding_sha256:
            expected = sha256_bytes(canonical_json_bytes(self._unsigned_dict()))
            if self.binding_sha256 != expected:
                raise RemoteExecutionBindingError("binding digest mismatch")

    def _unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("binding_sha256", None)
        return value

    def to_dict(self) -> dict[str, Any]:
        value = self._unsigned_dict()
        value["binding_sha256"] = sha256_bytes(canonical_json_bytes(value))
        return value

    def sealed(self) -> "RemoteExecutionBindingV1":
        value = self.to_dict()
        return replace(self, binding_sha256=str(value["binding_sha256"]))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteExecutionBindingV1":
        expected = {
            "message_id", "source_message_id", "control_content_sha256",
            "envelope_sha256", "directive_digest", "project_id", "run_id",
            "gate_id", "task_id", "task_execution_id", "expected_state_sha256",
            "expected_owner_epoch", "expected_source_head", "expected_runtime_release_digest",
            "status", "projection_id", "bound_at", "updated_at", "binding_sha256",
            "schema_version",
        }
        if set(value) != expected:
            raise RemoteExecutionBindingError("binding fields mismatch")
        raw_epoch = value["expected_owner_epoch"]
        if isinstance(raw_epoch, bool) or not isinstance(raw_epoch, int):
            raise RemoteExecutionBindingError("invalid expected owner epoch")
        return cls(
            message_id=str(value["message_id"]),
            source_message_id=str(value["source_message_id"]),
            control_content_sha256=str(value["control_content_sha256"]),
            envelope_sha256=str(value["envelope_sha256"]),
            directive_digest=str(value["directive_digest"]),
            project_id=str(value["project_id"]),
            run_id=str(value["run_id"]),
            gate_id=str(value["gate_id"]),
            task_id=str(value["task_id"]),
            task_execution_id=str(value["task_execution_id"]),
            expected_state_sha256=str(value["expected_state_sha256"]),
            expected_owner_epoch=raw_epoch,
            expected_source_head=str(value["expected_source_head"]),
            expected_runtime_release_digest=str(value["expected_runtime_release_digest"]),
            status=str(value["status"]),
            projection_id=str(value["projection_id"]),
            bound_at=str(value["bound_at"]),
            updated_at=str(value["updated_at"]),
            binding_sha256=str(value["binding_sha256"]),
            schema_version=str(value["schema_version"]),
        )

    @classmethod
    def from_envelope(cls, envelope: RemoteOperatorEnvelopeV2) -> "RemoteExecutionBindingV1":
        now = _now()
        expected = envelope.expected
        canonical_control = canonical_json_bytes(envelope.to_dict())
        return cls(
            message_id=envelope.message_id,
            source_message_id=envelope.transport.source_message_id,
            control_content_sha256=sha256_bytes(canonical_control),
            envelope_sha256=envelope.envelope_sha256,
            directive_digest=envelope.directive_digest,
            project_id=envelope.project_id,
            run_id=envelope.run_id,
            gate_id=envelope.gate_id,
            task_id=envelope.task_id,
            task_execution_id=envelope.task_execution_id,
            expected_state_sha256=str(expected.canonical_run_state_sha256 or ""),
            expected_owner_epoch=int(expected.continuation_owner_epoch),
            expected_source_head=str(expected.source_head or ""),
            expected_runtime_release_digest=str(expected.runtime_release_digest or ""),
            status="PENDING",
            projection_id="",
            bound_at=now,
            updated_at=now,
        ).sealed()


class RemoteExecutionBindingStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RemoteExecutionBindingError("unsafe recovery binding root")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise RemoteExecutionBindingError("unsafe recovery binding root")

    def _path(self, message_id: str) -> Path:
        return self.root / f"{_safe_id(message_id, 'message ID')}.json"

    def _load_path(self, path: Path) -> RemoteExecutionBindingV1 | None:
        previous = path.with_suffix(path.suffix + ".prev")
        if path.is_symlink() or previous.is_symlink():
            raise RemoteExecutionBindingError("recovery binding state is a symlink")
        if not path.exists() and not previous.exists():
            return None
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteExecutionBindingError("recovery binding state is invalid") from exc
        return RemoteExecutionBindingV1.from_mapping(value)

    def get(self, message_id: str) -> RemoteExecutionBindingV1 | None:
        return self._load_path(self._path(message_id))

    def record(self, envelope: RemoteOperatorEnvelopeV2) -> RemoteExecutionBindingV1:
        candidate = RemoteExecutionBindingV1.from_envelope(envelope)
        path = self._path(candidate.message_id)
        existing = self._load_path(path)
        if existing is not None:
            immutable = (
                existing.source_message_id,
                existing.control_content_sha256,
                existing.envelope_sha256,
                existing.directive_digest,
                existing.project_id,
                existing.run_id,
                existing.gate_id,
                existing.task_id,
                existing.task_execution_id,
                existing.expected_state_sha256,
                existing.expected_owner_epoch,
                existing.expected_source_head,
                existing.expected_runtime_release_digest,
            )
            requested = (
                candidate.source_message_id,
                candidate.control_content_sha256,
                candidate.envelope_sha256,
                candidate.directive_digest,
                candidate.project_id,
                candidate.run_id,
                candidate.gate_id,
                candidate.task_id,
                candidate.task_execution_id,
                candidate.expected_state_sha256,
                candidate.expected_owner_epoch,
                candidate.expected_source_head,
                candidate.expected_runtime_release_digest,
            )
            if immutable != requested:
                raise RemoteExecutionBindingError("conflicting recovery binding")
            return existing
        try:
            durable_json_save(path, candidate.to_dict())
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteExecutionBindingError("recovery binding write failed") from exc
        loaded = self._load_path(path)
        assert loaded is not None
        return loaded

    def pending(self) -> tuple[RemoteExecutionBindingV1, ...]:
        result = []
        for path in sorted(self.root.glob("*.json")):
            if path.name.endswith(".prev"):
                continue
            binding = self._load_path(path)
            if binding is not None and binding.status != "PROJECTED":
                result.append(binding)
        return tuple(result)

    def _transition(self, message_id: str, *, status: str, projection_id: str | None = None) -> RemoteExecutionBindingV1:
        current = self.get(message_id)
        if current is None:
            raise RemoteExecutionBindingError("recovery binding missing")
        if status not in _STATUSES:
            raise RemoteExecutionBindingError("invalid recovery binding status")
        projected = current.projection_id if projection_id is None else str(projection_id)
        if current.projection_id and projection_id is not None and current.projection_id != projected:
            raise RemoteExecutionBindingError("projection binding conflict")
        updated = replace(
            current,
            status=status,
            projection_id=projected,
            updated_at=_now(),
            binding_sha256="",
        ).sealed()
        try:
            durable_json_save(self._path(message_id), updated.to_dict())
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteExecutionBindingError("recovery binding update failed") from exc
        loaded = self.get(message_id)
        assert loaded is not None
        return loaded

    def mark_outboxed(self, message_id: str, projection_id: str) -> RemoteExecutionBindingV1:
        return self._transition(message_id, status="OUTBOXED", projection_id=projection_id)

    def mark_projected(self, message_id: str, projection_id: str | None = None) -> RemoteExecutionBindingV1:
        return self._transition(message_id, status="PROJECTED", projection_id=projection_id)
