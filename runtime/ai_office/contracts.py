from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

OFFICE_STATE_SNAPSHOT_SCHEMA_V1 = "ai-office.state-snapshot.v1"
OFFICE_STATE_TRANSITION_SCHEMA_V1 = "ai-office.state-transition.v1"
ALLOWED_WORKFLOW_STATES = frozenset({
    "NEW", "INTAKE_READY", "INTAKE_BLOCKED", "CONTEXT_READY",
    "SOURCE_BINDING_BLOCKED", "PLAN_COORDINATED", "PLAN_HANDOFF_BLOCKED",
    "EXECUTION_PENDING", "WAITING_APPROVAL", "WAITING_STATE_CHANGE_AUTHORITY",
    "EXECUTION_IN_PROGRESS", "REVIEW_PENDING", "RECOVERY_COORDINATION",
    "COMPLETE", "BLOCKED", "FAILED",
})
FORBIDDEN_OWNED_STATE_KEYS = frozenset({
    "provider", "provider_ref", "model", "model_ref", "raw_payload", "raw_event",
    "stdout", "stderr", "secret", "api_key", "token", "action_truth", "provider_truth",
})


class AIOfficeContractError(ValueError):
    pass
def canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _text(value: object, label: str, *, max_length: int = 512, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AIOfficeContractError(f"{label} must be text")
    item = value.strip()
    if (not item and not allow_empty) or len(item) > max_length or any(ch in item for ch in ("\x00", "\n", "\r")):
        raise AIOfficeContractError(f"invalid {label}")
    return item


def _identity(value: object, label: str) -> str:
    item = _text(value, label, max_length=160)
    if "/" in item or "\\" in item or ".." in item:
        raise AIOfficeContractError(f"unsafe {label}")
    return item


def _digest_ref(value: object, label: str, *, allow_empty: bool = False) -> str:
    item = _text(value, label, max_length=64, allow_empty=allow_empty)
    if item and (len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item)):
        raise AIOfficeContractError(f"invalid {label}")
    return item
def reject_forbidden_owned_state_fields(value: Mapping[str, Any]) -> None:
    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if str(key).strip().lower() in FORBIDDEN_OWNED_STATE_KEYS:
                    raise AIOfficeContractError("external action/provider truth cannot be AI Office-owned state")
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
    walk(value)


@dataclass(frozen=True, slots=True)
class OfficeStateSnapshotV1:
    schema_version: str
    project_id: str
    run_id: str
    revision: int
    workflow_state: str
    approved_plan_ref: str
    baseline_ref: str
    workflow_refs: tuple[str, ...] = ()
    pending_approval_ref: str = ""
    pending_manual_action_ref: str = ""
    last_transition_digest: str = ""
    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_STATE_SNAPSHOT_SCHEMA_V1:
            raise AIOfficeContractError("unsupported state snapshot schema")
        object.__setattr__(self, "project_id", _identity(self.project_id, "project_id"))
        object.__setattr__(self, "run_id", _identity(self.run_id, "run_id"))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise AIOfficeContractError("invalid revision")
        if self.workflow_state not in ALLOWED_WORKFLOW_STATES:
            raise AIOfficeContractError("invalid workflow state")
        object.__setattr__(self, "approved_plan_ref", _text(self.approved_plan_ref, "approved_plan_ref"))
        object.__setattr__(self, "baseline_ref", _text(self.baseline_ref, "baseline_ref"))
        refs = tuple(_text(ref, "workflow_ref") for ref in self.workflow_refs)
        if len(refs) != len(set(refs)):
            raise AIOfficeContractError("duplicate workflow ref")
        object.__setattr__(self, "workflow_refs", refs)
        object.__setattr__(self, "pending_approval_ref", _text(self.pending_approval_ref, "pending_approval_ref", allow_empty=True))
        object.__setattr__(self, "pending_manual_action_ref", _text(self.pending_manual_action_ref, "pending_manual_action_ref", allow_empty=True))
        object.__setattr__(self, "last_transition_digest", _digest_ref(self.last_transition_digest, "last_transition_digest", allow_empty=True))

    def unsigned_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def snapshot_digest(self) -> str:
        return canonical_digest(self.unsigned_dict())
    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "snapshot_digest": self.snapshot_digest}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OfficeStateSnapshotV1":
        expected = {"schema_version", "project_id", "run_id", "revision", "workflow_state",
                    "approved_plan_ref", "baseline_ref", "workflow_refs", "pending_approval_ref",
                    "pending_manual_action_ref", "last_transition_digest", "snapshot_digest"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise AIOfficeContractError("state snapshot shape mismatch")
        reject_forbidden_owned_state_fields(value)
        obj = cls(str(value["schema_version"]), str(value["project_id"]), str(value["run_id"]),
                  int(value["revision"]), str(value["workflow_state"]), str(value["approved_plan_ref"]),
                  str(value["baseline_ref"]), tuple(value["workflow_refs"]),
                  str(value["pending_approval_ref"]), str(value["pending_manual_action_ref"]),
                  str(value["last_transition_digest"]))
        if str(value["snapshot_digest"]) != obj.snapshot_digest:
            raise AIOfficeContractError("state snapshot digest mismatch")
        return obj


@dataclass(frozen=True, slots=True)
class OfficeStateTransitionV1:
    schema_version: str
    project_id: str
    run_id: str
    sequence: int
    from_revision: int
    to_revision: int
    from_state: str
    to_state: str
    reason_ref: str
    previous_transition_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_STATE_TRANSITION_SCHEMA_V1:
            raise AIOfficeContractError("unsupported transition schema")
        object.__setattr__(self, "project_id", _identity(self.project_id, "project_id"))
        object.__setattr__(self, "run_id", _identity(self.run_id, "run_id"))
        if (self.sequence < 1 or self.from_revision < 0 or
                self.to_revision != self.from_revision + 1 or self.sequence != self.to_revision):
            raise AIOfficeContractError("invalid transition revision sequence")
        if self.from_state not in ALLOWED_WORKFLOW_STATES or self.to_state not in ALLOWED_WORKFLOW_STATES:
            raise AIOfficeContractError("invalid transition state")
        object.__setattr__(self, "reason_ref", _text(self.reason_ref, "reason_ref"))
        object.__setattr__(self, "previous_transition_digest",
                           _digest_ref(self.previous_transition_digest, "previous_transition_digest", allow_empty=True))

    def unsigned_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def transition_digest(self) -> str:
        return canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "transition_digest": self.transition_digest}
