"""Closed, digest-bound package for protected Full Plan operations."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "orchestration.dangerous-work-package.v1"
PROTECTED_OPERATIONS = frozenset({
    "PROTECTED_PUSH",
    "PR_MERGE",
    "TAG_RELEASE",
    "RUNTIME_CURRENT_SWITCH",
    "PRODUCTION_ACTIVATION",
    "SERVICE_RESTART",
    "BOUNDED_REBOOT",
    "P5_PREDECESSOR_QUIESCE",
    "P6_PREDECESSOR_RETIREMENT",
})
P5_OPERATION = "P5_PREDECESSOR_QUIESCE"
P6_OPERATION = "P6_PREDECESSOR_RETIREMENT"
POST_P5_SUCCESSOR_HEALTH = "SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_FIELDS = frozenset({
    "schema_version", "project_id", "run_id", "plan_digest", "source_head",
    "target_ref", "operations", "risk_classes", "precondition_evidence",
    "required_post_verifiers", "recovery_refs", "created_at", "expires_at",
})


class DangerousWorkPackageError(ValueError):
    pass


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DangerousWorkPackageError(f"{field} is required")
    if value != value.strip():
        raise DangerousWorkPackageError(f"{field} must not contain surrounding whitespace")
    return value


def _ordered_unique_strings(value: object, field: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DangerousWorkPackageError(f"{field} must be a list")
    values = tuple(_required_text(item, field) for item in value)
    if nonempty and not values:
        raise DangerousWorkPackageError(f"{field} must not be empty")
    if len(set(values)) != len(values):
        raise DangerousWorkPackageError(f"{field} must not contain duplicates")
    return values


def _timestamp(value: object, field: str) -> datetime:
    raw = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DangerousWorkPackageError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DangerousWorkPackageError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class DangerousWorkPackageV1:
    schema_version: str
    project_id: str
    run_id: str
    plan_digest: str
    source_head: str
    target_ref: str
    operations: tuple[str, ...]
    risk_classes: tuple[str, ...]
    precondition_evidence: tuple[str, ...]
    required_post_verifiers: tuple[str, ...]
    recovery_refs: tuple[str, ...]
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DangerousWorkPackageV1":
        if not isinstance(raw, Mapping):
            raise DangerousWorkPackageError("package must be a mapping")
        keys = frozenset(raw.keys())
        if keys != _FIELDS:
            missing = sorted(_FIELDS - keys)
            unknown = sorted(keys - _FIELDS)
            raise DangerousWorkPackageError(f"package fields mismatch missing={missing} unknown={unknown}")

        schema_version = _required_text(raw["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise DangerousWorkPackageError("schema_version mismatch")
        project_id = _required_text(raw["project_id"], "project_id")
        run_id = _required_text(raw["run_id"], "run_id")
        plan_digest = _required_text(raw["plan_digest"], "plan_digest")
        if not _SHA256.fullmatch(plan_digest):
            raise DangerousWorkPackageError("plan_digest must be lowercase sha256")
        source_head = _required_text(raw["source_head"], "source_head")
        if not _GIT_SHA1.fullmatch(source_head):
            raise DangerousWorkPackageError("source_head must be a lowercase 40-character git sha")
        target_ref = _required_text(raw["target_ref"], "target_ref")
        if not target_ref.startswith("refs/"):
            raise DangerousWorkPackageError("target_ref must be a fully qualified ref")

        operations = _ordered_unique_strings(raw["operations"], "operations")
        unknown_operations = [op for op in operations if op not in PROTECTED_OPERATIONS]
        if unknown_operations:
            raise DangerousWorkPackageError(f"unknown protected operation: {unknown_operations[0]}")
        risk_classes = _ordered_unique_strings(raw["risk_classes"], "risk_classes")
        precondition_evidence = _ordered_unique_strings(raw["precondition_evidence"], "precondition_evidence")
        required_post_verifiers = _ordered_unique_strings(
            raw["required_post_verifiers"], "required_post_verifiers", nonempty=False
        )
        recovery_refs = _ordered_unique_strings(raw["recovery_refs"], "recovery_refs")
        created_at = _timestamp(raw["created_at"], "created_at")
        expires_at = _timestamp(raw["expires_at"], "expires_at")
        if expires_at <= created_at:
            raise DangerousWorkPackageError("expires_at must be after created_at")

        if P6_OPERATION in operations:
            if P5_OPERATION not in operations:
                raise DangerousWorkPackageError("P6 requires P5 in the same package")
            if operations.index(P5_OPERATION) > operations.index(P6_OPERATION):
                raise DangerousWorkPackageError("P5 must precede P6")
            if POST_P5_SUCCESSOR_HEALTH not in required_post_verifiers:
                raise DangerousWorkPackageError("P6 requires post-P5 successor health verification")

        return cls(
            schema_version=schema_version,
            project_id=project_id,
            run_id=run_id,
            plan_digest=plan_digest,
            source_head=source_head,
            target_ref=target_ref,
            operations=operations,
            risk_classes=risk_classes,
            precondition_evidence=precondition_evidence,
            required_post_verifiers=required_post_verifiers,
            recovery_refs=recovery_refs,
            created_at=created_at,
            expires_at=expires_at,
        )

    def canonical_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "plan_digest": self.plan_digest,
            "source_head": self.source_head,
            "target_ref": self.target_ref,
            "operations": list(self.operations),
            "risk_classes": list(self.risk_classes),
            "precondition_evidence": list(self.precondition_evidence),
            "required_post_verifiers": list(self.required_post_verifiers),
            "recovery_refs": list(self.recovery_refs),
            "created_at": _canonical_timestamp(self.created_at),
            "expires_at": _canonical_timestamp(self.expires_at),
        }

    @property
    def package_digest(self) -> str:
        payload = json.dumps(
            self.canonical_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_mapping(self) -> dict[str, object]:
        out = self.canonical_mapping()
        out["package_digest"] = self.package_digest
        return out
