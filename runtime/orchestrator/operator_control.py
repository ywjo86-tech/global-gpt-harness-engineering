"""GPT Operator control and durable continuation contracts for governed HYBRID execution."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

OPERATOR_DIRECTIVE_SCHEMA = "orchestration.operator-directive.v1"
MANUAL_ACTION_AUTH_SCHEMA = "orchestration.manual-action-authorization.v1"
CONTINUATION_SCHEMA = "orchestration.operator-continuation.v1"

LOGICAL_STAGES = ("ENTRY", "PREPARE", "ACTION", "VERIFY", "REVIEW", "GATE_DECISION")
LEGAL_TRANSITIONS = {
    "ENTRY": frozenset({"PREPARE"}),
    "PREPARE": frozenset({"ACTION", "VERIFY"}),
    "ACTION": frozenset({"VERIFY"}),
    "VERIFY": frozenset({"REVIEW"}),
    "REVIEW": frozenset({"GATE_DECISION"}),
    "GATE_DECISION": frozenset(),
}
FORBIDDEN_DIRECTIVE_FIELDS = frozenset({"provider", "model", "provider_ref", "model_ref"})


class OperatorControlError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str, label: str) -> str:
    if not value or "/" in value or "\\" in value or ".." in value:
        raise OperatorControlError(f"unsafe {label}")
    return value


@dataclass(frozen=True, slots=True)
class OperatorDirectiveV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    current_stage: str
    requested_next_stage: str
    required_capabilities: tuple[str, ...]
    state_change_required: bool
    input_artifact_digests: tuple[str, ...]
    gate_id: str
    directive_id: str

    def __post_init__(self) -> None:
        if self.schema_version != OPERATOR_DIRECTIVE_SCHEMA:
            raise OperatorControlError("unsupported operator directive schema")
        for value, label in ((self.project_id, "project ID"), (self.run_id, "run ID"),
                             (self.task_id, "task ID"), (self.task_execution_id, "task execution ID"),
                             (self.gate_id, "gate ID"), (self.directive_id, "directive ID")):
            _safe_id(value, label)
        if self.current_stage not in LOGICAL_STAGES or self.requested_next_stage not in LOGICAL_STAGES:
            raise OperatorControlError("unknown operator stage")
        if self.requested_next_stage not in LEGAL_TRANSITIONS[self.current_stage]:
            raise OperatorControlError("OPERATOR_DIRECTIVE_BLOCKED: illegal transition")
        if self.current_stage == "PREPARE" and self.requested_next_stage == "ACTION":
            if not self.state_change_required or not self.input_artifact_digests:
                raise OperatorControlError("OPERATOR_DIRECTIVE_BLOCKED: ACTION requires prepared artifact lineage")
        if self.current_stage == "PREPARE" and self.requested_next_stage == "VERIFY" and self.state_change_required:
            raise OperatorControlError("OPERATOR_DIRECTIVE_BLOCKED: state-changing work requires ACTION")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "OperatorDirectiveV1":
        forbidden = FORBIDDEN_DIRECTIVE_FIELDS.intersection(payload)
        if forbidden:
            raise OperatorControlError("OPERATOR_DIRECTIVE_BLOCKED: provider/model fields are forbidden")
        required = {"schema_version", "project_id", "run_id", "task_id", "task_execution_id",
                    "current_stage", "requested_next_stage", "required_capabilities", "state_change_required",
                    "input_artifact_digests", "gate_id", "directive_id"}
        if not required.issubset(payload):
            raise OperatorControlError("OPERATOR_DIRECTIVE_BLOCKED: directive fields missing")
        return cls(
            schema_version=str(payload["schema_version"]), project_id=str(payload["project_id"]),
            run_id=str(payload["run_id"]), task_id=str(payload["task_id"]),
            task_execution_id=str(payload["task_execution_id"]), current_stage=str(payload["current_stage"]),
            requested_next_stage=str(payload["requested_next_stage"]),
            required_capabilities=tuple(sorted({str(x).strip() for x in payload["required_capabilities"] if str(x).strip()})),
            state_change_required=bool(payload["state_change_required"]),
            input_artifact_digests=tuple(str(x) for x in payload["input_artifact_digests"] if str(x)),
            gate_id=str(payload["gate_id"]), directive_id=str(payload["directive_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def directive_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ManualActionAuthorizationV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    gate_id: str
    operator: str
    action_package_digest: str
    editable_scope_digest: str
    command_digest: str
    authorization_id: str

    def __post_init__(self) -> None:
        if self.schema_version != MANUAL_ACTION_AUTH_SCHEMA or self.operator != "GPT_OPERATOR":
            raise OperatorControlError("manual action authority must be GPT_OPERATOR")
        for value in (self.project_id, self.run_id, self.task_id, self.task_execution_id, self.gate_id, self.authorization_id):
            _safe_id(value, "manual action binding")
        for value in (self.action_package_digest, self.editable_scope_digest, self.command_digest):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise OperatorControlError("manual action authorization digest is invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def authorization_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(slots=True)
class ContinuationState:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    gate_id: str
    current_stage: str
    execution_state: str
    next_action: str
    last_directive_digest: str = ""
    last_router_decision_digest: str = ""
    last_handoff_digest: str = ""
    manual_action_authorization_digest: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OperatorContinuationStore:
    """Atomic per-task checkpoint used to resume after any one-shot command or chat turn."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.base = self.project_root / "runtime" / "operator_control"

    def _path(self, run_id: str, task_id: str) -> Path:
        return self.base / _safe_id(run_id, "run ID") / f"{_safe_id(task_id, 'task ID')}.json"

    def load(self, run_id: str, task_id: str) -> ContinuationState | None:
        path = self._path(run_id, task_id)
        if not path.exists():
            return None
        if path.is_symlink():
            raise OperatorControlError("continuation checkpoint is a symlink")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != CONTINUATION_SCHEMA:
            raise OperatorControlError("continuation checkpoint schema mismatch")
        return ContinuationState(**payload)

    def save(self, state: ContinuationState) -> ContinuationState:
        if state.schema_version != CONTINUATION_SCHEMA:
            raise OperatorControlError("continuation checkpoint schema mismatch")
        state.updated_at = _utc_now()
        path = self._path(state.run_id, state.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_symlink():
            raise OperatorControlError("continuation checkpoint is a symlink")
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state.to_dict(), handle, indent=2, ensure_ascii=False)
                handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return state
