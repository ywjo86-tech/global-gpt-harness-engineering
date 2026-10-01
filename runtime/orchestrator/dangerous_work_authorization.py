"""Verification and approval-coverage bridge for sealed dangerous-work packages."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from runtime.orchestrator.dangerous_work_package import (
    DangerousWorkPackageV1,
    P6_OPERATION,
    POST_P5_SUCCESSOR_HEALTH,
)
from runtime.orchestrator.user_interaction_policy import ApprovalCoverageEvidence


SCHEMA_VERSION = "orchestration.dangerous-work-approval.v1"
SAFE_EFFECT_RECONCILIATION = frozenset({"NO_EFFECT", "RECONCILED"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({
    "schema_version", "approval_ref", "project_id", "run_id", "package_digest",
    "issued_at", "expires_at", "issuer_identity", "approval_evidence_digest",
})


class DangerousWorkAuthorizationError(ValueError):
    pass


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DangerousWorkAuthorizationError(f"{field} is required")
    if value != value.strip():
        raise DangerousWorkAuthorizationError(f"{field} must not contain surrounding whitespace")
    return value


def _timestamp(value: object, field: str) -> datetime:
    raw = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DangerousWorkAuthorizationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DangerousWorkAuthorizationError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DangerousWorkAuthorizationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DangerousWorkApprovalV1:
    schema_version: str
    approval_ref: str
    project_id: str
    run_id: str
    package_digest: str
    issued_at: datetime
    expires_at: datetime
    issuer_identity: str
    approval_evidence_digest: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DangerousWorkApprovalV1":
        if not isinstance(raw, Mapping):
            raise DangerousWorkAuthorizationError("approval must be a mapping")
        keys = frozenset(raw.keys())
        if keys != _FIELDS:
            missing = sorted(_FIELDS - keys)
            unknown = sorted(keys - _FIELDS)
            raise DangerousWorkAuthorizationError(
                f"approval fields mismatch missing={missing} unknown={unknown}"
            )
        schema_version = _required_text(raw["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise DangerousWorkAuthorizationError("schema_version mismatch")
        package_digest = _required_text(raw["package_digest"], "package_digest")
        if not _SHA256.fullmatch(package_digest):
            raise DangerousWorkAuthorizationError("package_digest must be lowercase sha256")
        evidence_digest = _required_text(raw["approval_evidence_digest"], "approval_evidence_digest")
        if not _SHA256.fullmatch(evidence_digest):
            raise DangerousWorkAuthorizationError("approval_evidence_digest must be lowercase sha256")
        issued_at = _timestamp(raw["issued_at"], "issued_at")
        expires_at = _timestamp(raw["expires_at"], "expires_at")
        if expires_at <= issued_at:
            raise DangerousWorkAuthorizationError("approval expires_at must be after issued_at")
        return cls(
            schema_version=schema_version,
            approval_ref=_required_text(raw["approval_ref"], "approval_ref"),
            project_id=_required_text(raw["project_id"], "project_id"),
            run_id=_required_text(raw["run_id"], "run_id"),
            package_digest=package_digest,
            issued_at=issued_at,
            expires_at=expires_at,
            issuer_identity=_required_text(raw["issuer_identity"], "issuer_identity"),
            approval_evidence_digest=evidence_digest,
        )


@dataclass(frozen=True, slots=True)
class ProtectedOperationAuthorization:
    allowed: bool
    reason: str
    coverage: ApprovalCoverageEvidence


def approval_coverage_for_package(
    package: DangerousWorkPackageV1,
    approval: DangerousWorkApprovalV1,
    *,
    now: datetime,
) -> ApprovalCoverageEvidence:
    now_utc = _aware_utc(now, "now")
    if approval.project_id != package.project_id:
        raise DangerousWorkAuthorizationError("approval project_id does not match package")
    if approval.run_id != package.run_id:
        raise DangerousWorkAuthorizationError("approval run_id does not match package")
    if approval.package_digest != package.package_digest:
        raise DangerousWorkAuthorizationError("approval package digest mismatch")
    if now_utc < package.created_at or now_utc >= package.expires_at:
        raise DangerousWorkAuthorizationError("dangerous-work package is not currently valid")
    if now_utc < approval.issued_at or now_utc >= approval.expires_at:
        raise DangerousWorkAuthorizationError("dangerous-work approval is not currently valid")
    if approval.issued_at < package.created_at:
        raise DangerousWorkAuthorizationError("approval predates sealed dangerous-work package")
    if approval.expires_at > package.expires_at:
        raise DangerousWorkAuthorizationError("approval lifetime exceeds package lifetime")
    return ApprovalCoverageEvidence(
        approval_ref=approval.approval_ref,
        approved_semantic_digest=package.package_digest,
        reviewed_semantic_digest=package.package_digest,
        allowed_risk_classes=tuple(package.risk_classes),
        allowed_operations=tuple(package.operations),
    )


def authorize_protected_operation(
    *,
    package: DangerousWorkPackageV1,
    approval: DangerousWorkApprovalV1,
    requested_operation: str,
    requested_risk_class: str,
    now: datetime,
    satisfied_preconditions: set[str] | frozenset[str] | tuple[str, ...],
    post_verifier_results: Mapping[str, str],
    current_source_head: str | None = None,
    current_target_ref: str | None = None,
    dangerous_reexecution: bool = False,
    effect_reconciliation: str = "UNKNOWN",
) -> ProtectedOperationAuthorization:
    coverage = approval_coverage_for_package(package, approval, now=now)
    if requested_operation not in package.operations:
        raise DangerousWorkAuthorizationError("requested operation is outside sealed package")
    if requested_risk_class not in package.risk_classes:
        raise DangerousWorkAuthorizationError("requested risk class is outside sealed package")
    if not coverage.covers(risk_class=requested_risk_class, operation=requested_operation):
        raise DangerousWorkAuthorizationError("approval coverage does not authorize requested operation")
    if current_source_head is not None and current_source_head != package.source_head:
        raise DangerousWorkAuthorizationError("source HEAD drift detected")
    if current_target_ref is not None and current_target_ref != package.target_ref:
        raise DangerousWorkAuthorizationError("target ref drift detected")

    satisfied = set(satisfied_preconditions)
    missing = [item for item in package.precondition_evidence if item not in satisfied]
    if missing:
        raise DangerousWorkAuthorizationError(f"missing dangerous-work precondition: {missing[0]}")

    if dangerous_reexecution and effect_reconciliation not in SAFE_EFFECT_RECONCILIATION:
        raise DangerousWorkAuthorizationError("dangerous reexecution lacks safe effect reconciliation")

    if requested_operation == P6_OPERATION:
        if post_verifier_results.get(POST_P5_SUCCESSOR_HEALTH) != "PASS":
            raise DangerousWorkAuthorizationError("P6 requires successful post-P5 successor health verification")

    return ProtectedOperationAuthorization(
        allowed=True,
        reason="sealed dangerous-work package and approval authorize operation",
        coverage=coverage,
    )
