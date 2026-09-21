"""Closed, authority-bound per-Gate continuation contract."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA = "orchestration.gate-continuation-contract.v1"
MANUAL_OPERATOR = "MANUAL_OPERATOR"
AUTO_WITHIN_APPROVED_CONTRACT = "AUTO_WITHIN_APPROVED_CONTRACT"
_FIELDS = (
    "schema_version","gate_id","continuation_policy","approved_base_head",
    "source_lineage_policy","allowed_write_paths","forbidden_paths",
    "required_verifiers","required_evidence_classes","commit_policy",
    "risk_classes","approval_coverage_ref","approval_coverage_digest",
    "external_effect_policy","runtime_migration_policy",
)
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ENUMS = {
    "continuation_policy": {MANUAL_OPERATOR, AUTO_WITHIN_APPROVED_CONTRACT},
    "source_lineage_policy": {"EXACT_BASE", "APPROVED_DESCENDANT_CHAIN"},
    "commit_policy": {"NO_COMMIT", "LOCAL_COMMIT_ALLOWED"},
    "external_effect_policy": {"NO_EXTERNAL_EFFECT", "GOVERNED_REPOSITORY_EFFECTS_ONLY"},
    "runtime_migration_policy": {"NO_RUNTIME_MIGRATION", "DELEGATE_RUNTIME_MIGRATION"},
}


def _tuple_strings(value: object, field: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{field} must be a string list")
    result = tuple(str(x).strip() for x in value)
    if nonempty and not result:
        raise ValueError(f"{field} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{field} contains duplicates")
    return result


@dataclass(frozen=True, slots=True)
class GateContinuationContract:
    schema_version: str
    gate_id: str
    continuation_policy: str
    approved_base_head: str
    source_lineage_policy: str
    allowed_write_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_verifiers: tuple[str, ...]
    required_evidence_classes: tuple[str, ...]
    commit_policy: str
    risk_classes: tuple[str, ...]
    approval_coverage_ref: str
    approval_coverage_digest: str
    external_effect_policy: str
    runtime_migration_policy: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "GateContinuationContract":
        if not isinstance(raw, Mapping) or set(raw) != set(_FIELDS):
            raise ValueError("GateContinuationContract fields mismatch")
        if raw.get("schema_version") != SCHEMA:
            raise ValueError("unsupported GateContinuationContract schema_version")
        gate_id = str(raw.get("gate_id") or "")
        if not _SAFE_ID.fullmatch(gate_id):
            raise ValueError("invalid gate_id")
        for field, allowed in _ENUMS.items():
            if raw.get(field) not in allowed:
                raise ValueError(f"invalid {field}")
        approved_base_head = str(raw.get("approved_base_head") or "")
        if not _SHA.fullmatch(approved_base_head):
            raise ValueError("invalid approved_base_head")
        approval_ref = str(raw.get("approval_coverage_ref") or "").strip()
        if not approval_ref:
            raise ValueError("approval_coverage_ref is required")
        approval_digest = str(raw.get("approval_coverage_digest") or "")
        if not _SHA256.fullmatch(approval_digest):
            raise ValueError("invalid approval_coverage_digest")
        return cls(
            schema_version=SCHEMA,
            gate_id=gate_id,
            continuation_policy=str(raw["continuation_policy"]),
            approved_base_head=approved_base_head,
            source_lineage_policy=str(raw["source_lineage_policy"]),
            allowed_write_paths=_tuple_strings(raw["allowed_write_paths"], "allowed_write_paths", nonempty=True),
            forbidden_paths=_tuple_strings(raw["forbidden_paths"], "forbidden_paths"),
            required_verifiers=_tuple_strings(raw["required_verifiers"], "required_verifiers", nonempty=True),
            required_evidence_classes=_tuple_strings(raw["required_evidence_classes"], "required_evidence_classes", nonempty=True),
            commit_policy=str(raw["commit_policy"]),
            risk_classes=_tuple_strings(raw["risk_classes"], "risk_classes", nonempty=True),
            approval_coverage_ref=approval_ref,
            approval_coverage_digest=approval_digest,
            external_effect_policy=str(raw["external_effect_policy"]),
            runtime_migration_policy=str(raw["runtime_migration_policy"]),
        )

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_id": self.gate_id,
            "continuation_policy": self.continuation_policy,
            "approved_base_head": self.approved_base_head,
            "source_lineage_policy": self.source_lineage_policy,
            "allowed_write_paths": list(self.allowed_write_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "required_verifiers": list(self.required_verifiers),
            "required_evidence_classes": list(self.required_evidence_classes),
            "commit_policy": self.commit_policy,
            "risk_classes": list(self.risk_classes),
            "approval_coverage_ref": self.approval_coverage_ref,
            "approval_coverage_digest": self.approval_coverage_digest,
            "external_effect_policy": self.external_effect_policy,
            "runtime_migration_policy": self.runtime_migration_policy,
        }

    @property
    def contract_sha256(self) -> str:
        raw = json.dumps(self.canonical_projection(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()

    def require_gate(self, gate_id: str) -> None:
        if self.gate_id != str(gate_id):
            raise ValueError("GateContinuationContract gate_id mismatch")


def continuation_policy_for_gate(gate: Mapping[str, Any]) -> str:
    raw = gate.get("continuation_contract")
    if raw is None:
        return MANUAL_OPERATOR
    return GateContinuationContract.from_mapping(raw).continuation_policy
