"""Versioned MPRF checkpoint integrity facts; references only, never action/effect truth."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import MPRFContractError

CHECKPOINT_SCHEMA_V1 = "mprf.checkpoint.v1"
CHECKPOINT_VALIDATION_SCHEMA_V1 = "mprf.checkpoint-validation.v1"
CHECKPOINT_VALID = "VALID"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MPRFContractError(f"{name} must be a non-empty string")
    return value.strip()


def _refs(values: Iterable[str], name: str) -> tuple[str, ...]:
    result = tuple(str(item).strip() for item in values)
    if any(not item for item in result) or len(set(result)) != len(result):
        raise MPRFContractError(f"{name} references are invalid")
    return result


@dataclass(frozen=True, slots=True)
class MPRFCheckpointV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    stage: str
    provider_runtime_state_version: int
    artifact_digest_refs: tuple[str, ...]
    router_decision_refs: tuple[str, ...]
    effect_reconciliation_refs: tuple[str, ...]
    authorization_ref: str
    parent_checkpoint_ref: str
    integrity_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA_V1:
            raise MPRFContractError("unsupported MPRF checkpoint schema")
        for value, name in ((self.project_id, "project_id"), (self.run_id, "run_id"),
                            (self.task_id, "task_id"), (self.task_execution_id, "task_execution_id"),
                            (self.stage, "stage"), (self.authorization_ref, "authorization_ref")):
            _text(value, name)
        if isinstance(self.provider_runtime_state_version, bool) or not isinstance(self.provider_runtime_state_version, int) or self.provider_runtime_state_version < 1:
            raise MPRFContractError("provider_runtime_state_version must be positive")
        object.__setattr__(self, "artifact_digest_refs", _refs(self.artifact_digest_refs, "artifact"))
        object.__setattr__(self, "router_decision_refs", _refs(self.router_decision_refs, "Router decision"))
        object.__setattr__(self, "effect_reconciliation_refs", _refs(self.effect_reconciliation_refs, "effect reconciliation"))
        if not isinstance(self.parent_checkpoint_ref, str):
            raise MPRFContractError("parent_checkpoint_ref must be a string")
        if not isinstance(self.integrity_digest, str) or not _SHA256.fullmatch(self.integrity_digest):
            raise MPRFContractError("checkpoint integrity digest must be lowercase SHA-256")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "project_id": self.project_id, "run_id": self.run_id,
            "task_id": self.task_id, "task_execution_id": self.task_execution_id, "stage": self.stage,
            "provider_runtime_state_version": self.provider_runtime_state_version,
            "artifact_digest_refs": list(self.artifact_digest_refs),
            "router_decision_refs": list(self.router_decision_refs),
            "effect_reconciliation_refs": list(self.effect_reconciliation_refs),
            "authorization_ref": self.authorization_ref, "parent_checkpoint_ref": self.parent_checkpoint_ref,
        }

    @property
    def expected_integrity_digest(self) -> str:
        return _digest(self.unsigned_dict())

    @property
    def checkpoint_ref(self) -> str:
        return f"mprf-checkpoint://{self.task_execution_id}/{self.stage}#{self.integrity_digest}"

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "integrity_digest": self.integrity_digest}


@dataclass(frozen=True, slots=True)
class CheckpointValidationV1:
    schema_version: str
    status: str
    reason_code: str
    checkpoint_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_VALIDATION_SCHEMA_V1:
            raise MPRFContractError("unsupported checkpoint validation schema")
        if self.status not in {CHECKPOINT_VALID, RECOVERY_REQUIRED}:
            raise MPRFContractError("unknown checkpoint validation status")
        _text(self.reason_code, "reason_code")
        if not isinstance(self.checkpoint_ref, str):
            raise MPRFContractError("checkpoint_ref must be a string")


def seal_checkpoint(*, project_id: str, run_id: str, task_id: str, task_execution_id: str,
                    stage: str, provider_runtime_state_version: int,
                    artifact_digest_refs: Iterable[str], router_decision_refs: Iterable[str],
                    effect_reconciliation_refs: Iterable[str], authorization_ref: str,
                    parent_checkpoint_ref: str = "") -> MPRFCheckpointV1:
    provisional = MPRFCheckpointV1(
        CHECKPOINT_SCHEMA_V1, project_id, run_id, task_id, task_execution_id, stage,
        provider_runtime_state_version, tuple(artifact_digest_refs), tuple(router_decision_refs),
        tuple(effect_reconciliation_refs), authorization_ref, parent_checkpoint_ref, "0" * 64,
    )
    return MPRFCheckpointV1(**{**provisional.to_dict(), "integrity_digest": provisional.expected_integrity_digest})


def validate_checkpoint(checkpoint: MPRFCheckpointV1, *, project_id: str, run_id: str,
                        task_id: str, task_execution_id: str,
                        expected_parent_checkpoint_ref: str = "") -> CheckpointValidationV1:
    if not isinstance(checkpoint, MPRFCheckpointV1):
        raise MPRFContractError("MPRFCheckpoint.v1 is required")
    reason = "CHECKPOINT_VALID"
    valid = checkpoint.integrity_digest == checkpoint.expected_integrity_digest
    if not valid:
        reason = "CHECKPOINT_INTEGRITY_CORRUPT"
    elif (checkpoint.project_id, checkpoint.run_id, checkpoint.task_id, checkpoint.task_execution_id) != (
            project_id, run_id, task_id, task_execution_id):
        valid = False; reason = "CHECKPOINT_LINEAGE_MISMATCH"
    elif checkpoint.parent_checkpoint_ref != expected_parent_checkpoint_ref:
        valid = False; reason = "CHECKPOINT_PARENT_LINEAGE_MISMATCH"
    return CheckpointValidationV1(
        CHECKPOINT_VALIDATION_SCHEMA_V1,
        CHECKPOINT_VALID if valid else RECOVERY_REQUIRED,
        reason,
        checkpoint.checkpoint_ref,
    )
