from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .completion_contract import (
    CompletionAssessment,
    ExecutionObligation,
    TaskEffectPolicy,
    derive_execution_obligation,
)


class GovernedContractError(ValueError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


class ContractBuildError(GovernedContractError):
    pass


class ContractActivationError(GovernedContractError):
    pass


class PackageBuildError(GovernedContractError):
    pass


class PreflightBlocked(GovernedContractError):
    pass


class ActivationProfile(str, Enum):
    MIGRATION_APPROVED_PLAN = "MIGRATION_APPROVED_PLAN"
    FULL_ORCHESTRATION = "FULL_ORCHESTRATION"


class ContractStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"


class CrossCheckFailureOwner(str, Enum):
    PLANNING_REVISION = "PLANNING_REVISION_REQUIRED"
    QUALITY_CRITERIA_REVISION = "QUALITY_CRITERIA_REVISION_REQUIRED"
    CONTRACT_BUILDER_FIX = "CONTRACT_PROJECTION_FIX_REQUIRED"
    APPROVAL_RESOLUTION = "APPROVAL_RESOLUTION_REQUIRED"
    REQUIREMENT_CHANGE_DECISION = "REQUIREMENT_CHANGE_DECISION_REQUIRED"
    ENGINEERING_BLOCK = "ENGINEERING_BLOCK"


READY = "READY"
ALWAYS_BEFORE_CODEX_LAUNCH = "ALWAYS_BEFORE_CODEX_LAUNCH"
LEGACY_REFERENCE_BOOTSTRAP = "LEGACY_REFERENCE_BOOTSTRAP"
PRE_QUALITY_REFERENCE_SATISFIED = "PRE_QUALITY_REFERENCE_SATISFIED"
OBLIGATION_DERIVATION_VERSION = "completion-obligation-v1"
CONTRACT_SCHEMA_VERSION = "execution-contract-v1"
PACKAGE_SCHEMA_VERSION = "execution-package-v1"


_SECRET_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+\-/]+=*|sk-[a-z0-9_-]{12,}|api[_-]?key\s*[:=]|token\s*[:=]|password\s*[:=]|secret\s*[:=])"
)


def _freeze_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, MappingABC):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise GovernedContractError(
                    "mapping keys must be strings", reason_taxonomy="NON_CANONICAL_MAPPING"
                )
            frozen[key] = _freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, SequenceABC) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json_value(item) for item in value)
    raise GovernedContractError(
        f"unsupported canonical value type: {type(value).__name__}",
        reason_taxonomy="NON_CANONICAL_VALUE",
    )


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            _thaw_json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GovernedContractError(
            f"value is not canonically serializable: {exc}",
            reason_taxonomy="NON_CANONICAL_VALUE",
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sorted_unique_strings(values: Sequence[str], *, field_name: str, allow_empty: bool = True) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise GovernedContractError(
                f"{field_name} must contain non-empty strings",
                reason_taxonomy="INVALID_CONTRACT_FIELD",
            )
        normalized.append(value.strip())
    result = tuple(sorted(set(normalized)))
    if not allow_empty and not result:
        raise GovernedContractError(
            f"{field_name} is required", reason_taxonomy="INVALID_CONTRACT_FIELD"
        )
    return result


def _mapping_of_strings(value: Mapping[str, str], *, field_name: str) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(item, str) or not item.strip():
            raise GovernedContractError(
                f"{field_name} must contain non-empty string keys/values",
                reason_taxonomy="INVALID_CONTRACT_FIELD",
            )
        normalized[key.strip()] = item.strip()
    return MappingProxyType(dict(sorted(normalized.items())))


def _utc_parse(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GovernedContractError(
            "verified_at_utc must be ISO-8601", reason_taxonomy="AUTH_EVIDENCE_INVALID"
        ) from exc
    if parsed.tzinfo is None:
        raise GovernedContractError(
            "verified_at_utc must be timezone-aware", reason_taxonomy="AUTH_EVIDENCE_INVALID"
        )
    return parsed.astimezone(timezone.utc)


def _write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, target)


@dataclass(frozen=True, slots=True)
class ApprovalContext:
    full_plan_approval_required: bool
    full_plan_approval_ref: str = ""
    approved_semantic_digest: str = ""
    reviewed_semantic_digest: str = ""
    other_approval_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "other_approval_refs",
            _sorted_unique_strings(self.other_approval_refs, field_name="other_approval_refs"),
        )

    @property
    def is_compatible(self) -> bool:
        if not self.approved_semantic_digest.strip() or not self.reviewed_semantic_digest.strip():
            return False
        return self.approved_semantic_digest.strip() == self.reviewed_semantic_digest.strip()

    def require_contract_build_eligible(self, *, expected_semantic_digest: str | None = None) -> None:
        if not self.full_plan_approval_ref.strip():
            raise ContractBuildError(
                (
                    "Full Plan Approval is required before Contract Build"
                    if self.full_plan_approval_required
                    else "approved Plan/Design approval lineage is required before Contract Build"
                ),
                reason_taxonomy=(
                    "FULL_PLAN_APPROVAL_MISSING"
                    if self.full_plan_approval_required
                    else "APPROVAL_LINEAGE_MISSING"
                ),
            )
        if not self.approved_semantic_digest.strip() or not self.reviewed_semantic_digest.strip():
            raise ContractBuildError(
                "approval semantic digests are required for exact compatibility validation",
                reason_taxonomy="APPROVAL_SEMANTIC_DIGEST_MISSING",
            )
        if not self.is_compatible:
            raise ContractBuildError(
                "approval semantic digest is stale after material change",
                reason_taxonomy="PLAN_REAPPROVAL_REQUIRED",
            )
        if expected_semantic_digest is not None:
            if not isinstance(expected_semantic_digest, str) or not expected_semantic_digest.strip():
                raise ContractBuildError(
                    "authoritative semantic source digest is required",
                    reason_taxonomy="SEMANTIC_SOURCE_DIGEST_MISSING",
                )
            expected = expected_semantic_digest.strip()
            if (
                self.approved_semantic_digest.strip() != expected
                or self.reviewed_semantic_digest.strip() != expected
            ):
                raise ContractBuildError(
                    "approval lineage is not exact-compatible with the reviewed semantic source",
                    reason_taxonomy="PLAN_REAPPROVAL_REQUIRED",
                )

    def approval_refs(self) -> tuple[str, ...]:
        refs = list(self.other_approval_refs)
        if self.full_plan_approval_ref.strip():
            refs.append(self.full_plan_approval_ref.strip())
        return tuple(sorted(set(refs)))


@dataclass(frozen=True, slots=True)
class QualityCriterion:
    criterion_id: str
    rule_ref: str
    source_ref: str
    requirement_refs: tuple[str, ...] = ()
    scope_refs: tuple[str, ...] = ()
    permission_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("criterion_id", "rule_ref", "source_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise GovernedContractError(
                    f"{name} is required", reason_taxonomy="QUALITY_CRITERION_INVALID"
                )
            object.__setattr__(self, name, value.strip())
        object.__setattr__(self, "requirement_refs", _sorted_unique_strings(self.requirement_refs, field_name="requirement_refs"))
        object.__setattr__(self, "scope_refs", _sorted_unique_strings(self.scope_refs, field_name="scope_refs"))
        object.__setattr__(self, "permission_refs", _sorted_unique_strings(self.permission_refs, field_name="permission_refs"))

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "rule_ref": self.rule_ref,
            "source_ref": self.source_ref,
            "requirement_refs": list(self.requirement_refs),
            "scope_refs": list(self.scope_refs),
            "permission_refs": list(self.permission_refs),
        }


@dataclass(frozen=True, slots=True)
class MigrationQualityCriteriaContract:
    source_mode: str
    source_refs: tuple[str, ...]
    policy_version: str
    criteria: tuple[QualityCriterion, ...]
    digest: str
    pre_quality_state: str = PRE_QUALITY_REFERENCE_SATISFIED

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "source_mode": self.source_mode,
            "source_refs": list(self.source_refs),
            "policy_version": self.policy_version,
            "criteria": [criterion.canonical_projection() for criterion in self.criteria],
            "pre_quality_state": self.pre_quality_state,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.canonical_projection()
        payload["digest"] = self.digest
        return payload

    def persist(self, path: str | Path) -> None:
        _write_json_atomic(path, self.to_dict())


def build_migration_quality_criteria_contract(
    *,
    activation_profile: ActivationProfile,
    source_refs: Sequence[str],
    policy_version: str,
    approved_quality_obligations: Sequence[QualityCriterion],
    harness_policy_criteria: Sequence[QualityCriterion],
    approved_requirement_refs: Sequence[str],
    approved_scope: Sequence[str],
    approved_permissions: Sequence[str],
) -> MigrationQualityCriteriaContract:
    if activation_profile is not ActivationProfile.MIGRATION_APPROVED_PLAN:
        raise ContractBuildError(
            "migration quality bootstrap is prohibited outside MIGRATION_APPROVED_PLAN",
            reason_taxonomy="MIGRATION_BOOTSTRAP_PROFILE_INVALID",
        )
    sources = _sorted_unique_strings(source_refs, field_name="source_refs", allow_empty=False)
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ContractBuildError(
            "policy_version is required", reason_taxonomy="QUALITY_POLICY_VERSION_MISSING"
        )
    criteria = tuple(sorted((*approved_quality_obligations, *harness_policy_criteria), key=lambda item: item.criterion_id))
    if not criteria:
        raise ContractBuildError(
            "migration quality bootstrap requires approved quality criteria",
            reason_taxonomy="MIGRATION_QUALITY_SOURCE_MISSING",
        )
    ids = [criterion.criterion_id for criterion in criteria]
    if len(ids) != len(set(ids)):
        raise ContractBuildError(
            "duplicate migration quality criterion_id",
            reason_taxonomy="MIGRATION_QUALITY_DUPLICATE_ID",
        )
    reqs = set(_sorted_unique_strings(approved_requirement_refs, field_name="approved_requirement_refs"))
    scope = set(_sorted_unique_strings(approved_scope, field_name="approved_scope"))
    permissions = set(_sorted_unique_strings(approved_permissions, field_name="approved_permissions"))
    for criterion in criteria:
        if not set(criterion.requirement_refs).issubset(reqs):
            raise ContractBuildError(
                f"{criterion.criterion_id}: bootstrap invents requirement meaning",
                reason_taxonomy="MIGRATION_QUALITY_REQUIREMENT_EXPANSION",
            )
        if not set(criterion.scope_refs).issubset(scope):
            raise ContractBuildError(
                f"{criterion.criterion_id}: bootstrap expands scope",
                reason_taxonomy="MIGRATION_QUALITY_SCOPE_EXPANSION",
            )
        if not set(criterion.permission_refs).issubset(permissions):
            raise ContractBuildError(
                f"{criterion.criterion_id}: bootstrap expands permission",
                reason_taxonomy="MIGRATION_QUALITY_PERMISSION_EXPANSION",
            )
    projection = {
        "source_mode": LEGACY_REFERENCE_BOOTSTRAP,
        "source_refs": list(sources),
        "policy_version": policy_version.strip(),
        "criteria": [criterion.canonical_projection() for criterion in criteria],
        "pre_quality_state": PRE_QUALITY_REFERENCE_SATISFIED,
    }
    return MigrationQualityCriteriaContract(
        source_mode=LEGACY_REFERENCE_BOOTSTRAP,
        source_refs=sources,
        policy_version=policy_version.strip(),
        criteria=criteria,
        digest=_digest(projection),
    )


@dataclass(frozen=True, slots=True)
class ApprovedExecutionProjection:
    requirement_refs: tuple[str, ...]
    plan_task_ref: str
    purpose: str
    task_effect_policy: TaskEffectPolicy
    completion_criteria_ids: tuple[str, ...]
    validation_criteria: tuple[str, ...]
    quality_criteria_contract_ref: str
    change_targets: tuple[str, ...]
    owned_scope: tuple[str, ...]
    allowed_worker_terminal_states: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    permission_requirements: tuple[str, ...]
    security_requirements: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    remediation_policy_ref: str
    source_digests: Mapping[str, str]
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_refs", _sorted_unique_strings(self.requirement_refs, field_name="requirement_refs", allow_empty=False))
        object.__setattr__(self, "completion_criteria_ids", _sorted_unique_strings(self.completion_criteria_ids, field_name="completion_criteria_ids", allow_empty=False))
        object.__setattr__(self, "validation_criteria", _sorted_unique_strings(self.validation_criteria, field_name="validation_criteria", allow_empty=False))
        object.__setattr__(self, "change_targets", _sorted_unique_strings(self.change_targets, field_name="change_targets", allow_empty=False))
        object.__setattr__(self, "owned_scope", _sorted_unique_strings(self.owned_scope, field_name="owned_scope", allow_empty=False))
        object.__setattr__(self, "allowed_worker_terminal_states", _sorted_unique_strings(self.allowed_worker_terminal_states, field_name="allowed_worker_terminal_states", allow_empty=False))
        object.__setattr__(self, "allowed_capabilities", _sorted_unique_strings(self.allowed_capabilities, field_name="allowed_capabilities"))
        object.__setattr__(self, "permission_requirements", _sorted_unique_strings(self.permission_requirements, field_name="permission_requirements"))
        object.__setattr__(self, "security_requirements", _sorted_unique_strings(self.security_requirements, field_name="security_requirements"))
        object.__setattr__(self, "evidence_requirements", _sorted_unique_strings(self.evidence_requirements, field_name="evidence_requirements"))
        object.__setattr__(self, "source_digests", _mapping_of_strings(self.source_digests, field_name="source_digests"))
        missing_source_keys = {"plan", "requirement", "semantic"} - set(self.source_digests)
        if missing_source_keys:
            raise GovernedContractError(
                f"source_digests missing required keys: {sorted(missing_source_keys)}",
                reason_taxonomy="INVALID_PROJECTION",
            )
        for name in ("plan_task_ref", "purpose", "quality_criteria_contract_ref", "remediation_policy_ref", "schema_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise GovernedContractError(f"{name} is required", reason_taxonomy="INVALID_PROJECTION")
            object.__setattr__(self, name, value.strip())


@dataclass(frozen=True, slots=True)
class CanonicalExecutionContract:
    contract_id: str
    contract_version: str
    parent_contract_id: str
    requirement_refs: tuple[str, ...]
    plan_task_ref: str
    purpose: str
    task_effect_policy: TaskEffectPolicy
    completion_criteria_ids: tuple[str, ...]
    validation_criteria: tuple[str, ...]
    quality_criteria_contract_ref: str
    obligation_derivation_version: str
    change_targets: tuple[str, ...]
    owned_scope: tuple[str, ...]
    allowed_worker_terminal_states: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    permission_requirements: tuple[str, ...]
    security_requirements: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    remediation_policy_ref: str
    source_digests: Mapping[str, str]
    approval_refs: tuple[str, ...]
    schema_version: str
    status: ContractStatus
    contract_digest: str
    cross_check_digest: str = ""
    activation_digest: str = ""

    def semantic_projection(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "parent_contract_id": self.parent_contract_id,
            "requirement_refs": list(self.requirement_refs),
            "plan_task_ref": self.plan_task_ref,
            "purpose": self.purpose,
            "task_effect_policy": self.task_effect_policy.value,
            "completion_criteria_ids": list(self.completion_criteria_ids),
            "validation_criteria": list(self.validation_criteria),
            "quality_criteria_contract_ref": self.quality_criteria_contract_ref,
            "obligation_derivation_version": self.obligation_derivation_version,
            "change_targets": list(self.change_targets),
            "owned_scope": list(self.owned_scope),
            "allowed_worker_terminal_states": list(self.allowed_worker_terminal_states),
            "allowed_capabilities": list(self.allowed_capabilities),
            "permission_requirements": list(self.permission_requirements),
            "security_requirements": list(self.security_requirements),
            "evidence_requirements": list(self.evidence_requirements),
            "remediation_policy_ref": self.remediation_policy_ref,
            "source_digests": dict(self.source_digests),
            "approval_refs": list(self.approval_refs),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_projection()
        payload.update(
            {
                "status": self.status.value,
                "contract_digest": self.contract_digest,
                "cross_check_digest": self.cross_check_digest,
                "activation_digest": self.activation_digest,
            }
        )
        return payload

    def persist(self, path: str | Path) -> None:
        _write_json_atomic(path, self.to_dict())


def build_contract_candidate(
    *,
    contract_id: str,
    contract_version: str,
    parent_contract_id: str = "",
    approved_projection: ApprovedExecutionProjection,
    approval_context: ApprovalContext,
) -> CanonicalExecutionContract:
    approval_context.require_contract_build_eligible(
        expected_semantic_digest=approved_projection.source_digests.get("semantic")
    )
    for name, value in (("contract_id", contract_id), ("contract_version", contract_version)):
        if not isinstance(value, str) or not value.strip():
            raise ContractBuildError(f"{name} is required", reason_taxonomy="INVALID_CONTRACT_FIELD")
    parent = parent_contract_id.strip() if isinstance(parent_contract_id, str) else ""
    approval_refs = approval_context.approval_refs()
    base = {
        "contract_id": contract_id.strip(),
        "contract_version": contract_version.strip(),
        "parent_contract_id": parent,
        "requirement_refs": list(approved_projection.requirement_refs),
        "plan_task_ref": approved_projection.plan_task_ref,
        "purpose": approved_projection.purpose,
        "task_effect_policy": approved_projection.task_effect_policy.value,
        "completion_criteria_ids": list(approved_projection.completion_criteria_ids),
        "validation_criteria": list(approved_projection.validation_criteria),
        "quality_criteria_contract_ref": approved_projection.quality_criteria_contract_ref,
        "obligation_derivation_version": OBLIGATION_DERIVATION_VERSION,
        "change_targets": list(approved_projection.change_targets),
        "owned_scope": list(approved_projection.owned_scope),
        "allowed_worker_terminal_states": list(approved_projection.allowed_worker_terminal_states),
        "allowed_capabilities": list(approved_projection.allowed_capabilities),
        "permission_requirements": list(approved_projection.permission_requirements),
        "security_requirements": list(approved_projection.security_requirements),
        "evidence_requirements": list(approved_projection.evidence_requirements),
        "remediation_policy_ref": approved_projection.remediation_policy_ref,
        "source_digests": dict(approved_projection.source_digests),
        "approval_refs": list(approval_refs),
        "schema_version": approved_projection.schema_version,
    }
    return CanonicalExecutionContract(
        contract_id=base["contract_id"],
        contract_version=base["contract_version"],
        parent_contract_id=base["parent_contract_id"],
        requirement_refs=tuple(base["requirement_refs"]),
        plan_task_ref=base["plan_task_ref"],
        purpose=base["purpose"],
        task_effect_policy=approved_projection.task_effect_policy,
        completion_criteria_ids=tuple(base["completion_criteria_ids"]),
        validation_criteria=tuple(base["validation_criteria"]),
        quality_criteria_contract_ref=base["quality_criteria_contract_ref"],
        obligation_derivation_version=OBLIGATION_DERIVATION_VERSION,
        change_targets=tuple(base["change_targets"]),
        owned_scope=tuple(base["owned_scope"]),
        allowed_worker_terminal_states=tuple(base["allowed_worker_terminal_states"]),
        allowed_capabilities=tuple(base["allowed_capabilities"]),
        permission_requirements=tuple(base["permission_requirements"]),
        security_requirements=tuple(base["security_requirements"]),
        evidence_requirements=tuple(base["evidence_requirements"]),
        remediation_policy_ref=base["remediation_policy_ref"],
        source_digests=MappingProxyType(dict(base["source_digests"])),
        approval_refs=approval_refs,
        schema_version=base["schema_version"],
        status=ContractStatus.CANDIDATE,
        contract_digest=_digest(base),
        cross_check_digest="",
    )


@dataclass(frozen=True, slots=True)
class ContractCrossCheckResult:
    passed: bool
    failure_owner: CrossCheckFailureOwner | None
    reason_taxonomy: str
    evidence_digest: str


def cross_check_contract(
    candidate: CanonicalExecutionContract,
    approved_projection: ApprovedExecutionProjection,
    approval_context: ApprovalContext,
) -> ContractCrossCheckResult:
    def result(passed: bool, owner: CrossCheckFailureOwner | None, reason: str) -> ContractCrossCheckResult:
        evidence = {
            "contract_digest": candidate.contract_digest,
            "projection_source_digests": dict(approved_projection.source_digests),
            "approval_refs": list(approval_context.approval_refs()),
            "passed": passed,
            "owner": owner.value if owner else "",
            "reason": reason,
        }
        return ContractCrossCheckResult(passed, owner, reason, _digest(evidence))

    if candidate.schema_version != approved_projection.schema_version:
        return result(False, CrossCheckFailureOwner.ENGINEERING_BLOCK, "SCHEMA_OR_INFRA_DEFECT")
    if candidate.plan_task_ref != approved_projection.plan_task_ref or candidate.purpose != approved_projection.purpose:
        return result(False, CrossCheckFailureOwner.PLANNING_REVISION, "PLANNING_SEMANTIC_DEFECT")
    if candidate.requirement_refs != approved_projection.requirement_refs:
        return result(False, CrossCheckFailureOwner.REQUIREMENT_CHANGE_DECISION, "REQUIREMENT_CHANGE_REQUIRED")
    if candidate.quality_criteria_contract_ref != approved_projection.quality_criteria_contract_ref:
        return result(False, CrossCheckFailureOwner.QUALITY_CRITERIA_REVISION, "QUALITY_CRITERIA_DEFECT")
    if candidate.obligation_derivation_version != OBLIGATION_DERIVATION_VERSION:
        return result(False, CrossCheckFailureOwner.ENGINEERING_BLOCK, "SCHEMA_OR_INFRA_DEFECT")
    projection_fields_equal = all(
        (
            candidate.task_effect_policy == approved_projection.task_effect_policy,
            candidate.completion_criteria_ids == approved_projection.completion_criteria_ids,
            candidate.validation_criteria == approved_projection.validation_criteria,
            candidate.change_targets == approved_projection.change_targets,
            candidate.owned_scope == approved_projection.owned_scope,
            candidate.allowed_worker_terminal_states == approved_projection.allowed_worker_terminal_states,
            candidate.allowed_capabilities == approved_projection.allowed_capabilities,
            candidate.permission_requirements == approved_projection.permission_requirements,
            candidate.security_requirements == approved_projection.security_requirements,
            candidate.evidence_requirements == approved_projection.evidence_requirements,
            candidate.remediation_policy_ref == approved_projection.remediation_policy_ref,
            dict(candidate.source_digests) == dict(approved_projection.source_digests),
        )
    )
    if not projection_fields_equal:
        return result(False, CrossCheckFailureOwner.CONTRACT_BUILDER_FIX, "CONTRACT_PROJECTION_DEFECT")
    try:
        approval_context.require_contract_build_eligible(
            expected_semantic_digest=approved_projection.source_digests.get("semantic")
        )
    except ContractBuildError:
        return result(False, CrossCheckFailureOwner.APPROVAL_RESOLUTION, "APPROVAL_MISSING_OR_STALE")
    if candidate.approval_refs != approval_context.approval_refs():
        return result(False, CrossCheckFailureOwner.APPROVAL_RESOLUTION, "APPROVAL_MISSING_OR_STALE")
    if candidate.contract_digest != _digest(candidate.semantic_projection()):
        return result(False, CrossCheckFailureOwner.CONTRACT_BUILDER_FIX, "CONTRACT_DIGEST_DRIFT")
    return result(True, None, "PASS")


def activate_contract(
    candidate: CanonicalExecutionContract,
    *,
    cross_check: ContractCrossCheckResult,
    approved_projection: ApprovedExecutionProjection,
    approval_context: ApprovalContext,
) -> CanonicalExecutionContract:
    if candidate.status is not ContractStatus.CANDIDATE:
        raise ContractActivationError(
            "only a Contract Candidate can be activated",
            reason_taxonomy="CONTRACT_LIFECYCLE_INVALID",
        )
    # Preserve the explicit AUTH-003 activation boundary and taxonomy before
    # evaluating the rest of the Cross-Check evidence.
    if candidate.owned_scope != approved_projection.owned_scope:
        raise ContractActivationError(
            "Contract scope differs from approved baseline without reapproval",
            reason_taxonomy="SCOPE_REAPPROVAL_REQUIRED",
        )
    expected_cross_check = cross_check_contract(candidate, approved_projection, approval_context)
    if not expected_cross_check.passed:
        raise ContractActivationError(
            "current Contract Cross-Check does not pass",
            reason_taxonomy="CONTRACT_CROSS_CHECK_NOT_PASS",
        )
    if cross_check != expected_cross_check:
        raise ContractActivationError(
            "supplied Contract Cross-Check evidence is stale or does not bind to this Candidate",
            reason_taxonomy="CONTRACT_CROSS_CHECK_EVIDENCE_DRIFT",
        )
    approval_context.require_contract_build_eligible(
        expected_semantic_digest=approved_projection.source_digests.get("semantic")
    )
    required_refs = approval_context.approval_refs()
    if candidate.approval_refs != required_refs:
        raise ContractActivationError(
            "required approval is missing, stale, or changed",
            reason_taxonomy="APPROVAL_MISSING_OR_STALE",
        )
    activation_projection = {
        "contract_digest": candidate.contract_digest,
        "cross_check_digest": expected_cross_check.evidence_digest,
        "approval_refs": list(required_refs),
    }
    return replace(
        candidate,
        status=ContractStatus.ACTIVE,
        cross_check_digest=expected_cross_check.evidence_digest,
        activation_digest=_digest(activation_projection),
    )


def require_valid_active_contract(contract: CanonicalExecutionContract) -> None:
    if contract.status is not ContractStatus.ACTIVE:
        raise PackageBuildError(
            "Execution Package requires ACTIVE Contract",
            reason_taxonomy="CONTRACT_NOT_ACTIVE",
        )
    if not contract.cross_check_digest or not contract.activation_digest:
        raise PackageBuildError(
            "ACTIVE Contract activation evidence is incomplete",
            reason_taxonomy="CONTRACT_ACTIVATION_EVIDENCE_MISSING",
        )
    if contract.obligation_derivation_version != OBLIGATION_DERIVATION_VERSION:
        raise PackageBuildError(
            "ACTIVE Contract obligation derivation rule is unsupported",
            reason_taxonomy="CONTRACT_DERIVATION_RULE_DRIFT",
        )
    if contract.contract_digest != _digest(contract.semantic_projection()):
        raise PackageBuildError(
            "ACTIVE Contract semantic projection does not match its sealed digest",
            reason_taxonomy="CONTRACT_DIGEST_DRIFT",
        )
    expected = _digest(
        {
            "contract_digest": contract.contract_digest,
            "cross_check_digest": contract.cross_check_digest,
            "approval_refs": sorted(contract.approval_refs),
        }
    )
    if contract.activation_digest != expected:
        raise PackageBuildError(
            "ACTIVE Contract activation digest is invalid",
            reason_taxonomy="CONTRACT_ACTIVATION_DRIFT",
        )



@dataclass(frozen=True, slots=True)
class CodexAuthReadinessEvidence:
    evidence_id: str
    verified_at_utc: str
    cli_version: str
    environment_fingerprint: str
    transport_schema_digest: str
    auth_status: str
    source_evidence_refs: tuple[str, ...]
    recheck_policy: str
    launch_binding_digest: str

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "verified_at_utc",
            "cli_version",
            "environment_fingerprint",
            "transport_schema_digest",
            "auth_status",
            "recheck_policy",
            "launch_binding_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise GovernedContractError(f"{name} is required", reason_taxonomy="AUTH_EVIDENCE_INVALID")
            if _SECRET_PATTERN.search(value):
                raise GovernedContractError(
                    f"{name} contains secret-like material", reason_taxonomy="AUTH_EVIDENCE_SECRET_MATERIAL"
                )
            object.__setattr__(self, name, value.strip())
        refs = _sorted_unique_strings(self.source_evidence_refs, field_name="source_evidence_refs", allow_empty=False)
        for ref in refs:
            if _SECRET_PATTERN.search(ref):
                raise GovernedContractError(
                    "source_evidence_refs contain secret-like material",
                    reason_taxonomy="AUTH_EVIDENCE_SECRET_MATERIAL",
                )
        object.__setattr__(self, "source_evidence_refs", refs)
        _utc_parse(self.verified_at_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "verified_at_utc": self.verified_at_utc,
            "cli_version": self.cli_version,
            "environment_fingerprint": self.environment_fingerprint,
            "transport_schema_digest": self.transport_schema_digest,
            "auth_status": self.auth_status,
            "source_evidence_refs": list(self.source_evidence_refs),
            "recheck_policy": self.recheck_policy,
            "launch_binding_digest": self.launch_binding_digest,
        }


def codex_launch_binding_digest(
    *,
    cli_version: str,
    environment_fingerprint: str,
    transport_schema_digest: str,
    run_id: str,
    worker_task_id: str,
    package_id: str,
    package_revision: int,
) -> str:
    return _digest(
        {
            "cli_version": cli_version,
            "environment_fingerprint": environment_fingerprint,
            "transport_schema_digest": transport_schema_digest,
            "run_id": run_id,
            "worker_task_id": worker_task_id,
            "package_id": package_id,
            "package_revision": package_revision,
        }
    )


@dataclass(frozen=True, slots=True)
class RunBinding:
    project_id: str
    gate_id: str
    lv_id: str
    run_id: str
    worker_task_id: str
    plan_version: str
    plan_digest: str
    requirement_version: str
    requirement_digest: str
    semantic_version: str
    semantic_digest: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise GovernedContractError(f"{name} is required", reason_taxonomy="RUN_BINDING_INVALID")
            object.__setattr__(self, name, value.strip())

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ExecutionPackage:
    package_id: str
    package_revision: int
    previous_package_digest: str
    activation_profile: ActivationProfile
    run_binding: RunBinding
    contract_ref: str
    contract_id: str
    contract_version: str
    contract_digest: str
    contract_activation_digest: str
    pre_execution_completion_assessment_ref: str
    criterion_set_digest: str
    execution_obligation: ExecutionObligation
    obligation_derivation_version: str
    obligation_derivation_result_digest: str
    purpose: str
    task_effect_policy: TaskEffectPolicy
    change_targets: tuple[str, ...]
    owned_scope_projection: tuple[str, ...]
    completion_criteria_ids: tuple[str, ...]
    validation_criteria: tuple[str, ...]
    quality_criteria_contract_ref: str
    allowed_worker_terminal_states: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    permission_requirements: tuple[str, ...]
    security_requirements: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    remediation_policy_ref: str
    source_digests: Mapping[str, str]
    approval_refs: tuple[str, ...]
    runtime_selection: Mapping[str, Any]
    exact_tool_authorization_projection: tuple[str, ...]
    security_policy_refs: tuple[str, ...]
    quality_policy_refs: tuple[str, ...]
    codex_backed_worker: bool
    codex_auth_readiness_ref: str
    resume_cursor: str
    checkpoint_refs: tuple[str, ...]
    effect_refs: tuple[str, ...]
    schema_version: str
    package_digest: str

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_revision": self.package_revision,
            "previous_package_digest": self.previous_package_digest,
            "activation_profile": self.activation_profile.value,
            "run_binding": self.run_binding.to_dict(),
            "contract_ref": self.contract_ref,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
            "contract_activation_digest": self.contract_activation_digest,
            "pre_execution_completion_assessment_ref": self.pre_execution_completion_assessment_ref,
            "criterion_set_digest": self.criterion_set_digest,
            "execution_obligation": self.execution_obligation.value,
            "obligation_derivation_version": self.obligation_derivation_version,
            "obligation_derivation_result_digest": self.obligation_derivation_result_digest,
            "purpose": self.purpose,
            "task_effect_policy": self.task_effect_policy.value,
            "change_targets": list(self.change_targets),
            "owned_scope_projection": list(self.owned_scope_projection),
            "completion_criteria_ids": list(self.completion_criteria_ids),
            "validation_criteria": list(self.validation_criteria),
            "quality_criteria_contract_ref": self.quality_criteria_contract_ref,
            "allowed_worker_terminal_states": list(self.allowed_worker_terminal_states),
            "allowed_capabilities": list(self.allowed_capabilities),
            "permission_requirements": list(self.permission_requirements),
            "security_requirements": list(self.security_requirements),
            "evidence_requirements": list(self.evidence_requirements),
            "remediation_policy_ref": self.remediation_policy_ref,
            "source_digests": dict(self.source_digests),
            "approval_refs": list(self.approval_refs),
            "runtime_selection": _thaw_json_value(self.runtime_selection),
            "exact_tool_authorization_projection": list(self.exact_tool_authorization_projection),
            "security_policy_refs": list(self.security_policy_refs),
            "quality_policy_refs": list(self.quality_policy_refs),
            "codex_backed_worker": self.codex_backed_worker,
            "codex_auth_readiness_ref": self.codex_auth_readiness_ref,
            "resume_cursor": self.resume_cursor,
            "checkpoint_refs": list(self.checkpoint_refs),
            "effect_refs": list(self.effect_refs),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.canonical_projection()
        payload["package_digest"] = self.package_digest
        return payload

    def persist(self, path: str | Path) -> None:
        _write_json_atomic(path, self.to_dict())


def _obligation_result_digest(
    contract: CanonicalExecutionContract,
    assessment: CompletionAssessment,
    obligation: ExecutionObligation,
) -> str:
    return _digest(
        {
            "contract_digest": contract.contract_digest,
            "task_effect_policy": contract.task_effect_policy.value,
            "assessment_state": assessment.overall_state.value,
            "criterion_set_digest": assessment.criterion_set_digest,
            "execution_obligation": obligation.value,
            "obligation_derivation_version": contract.obligation_derivation_version,
        }
    )


def build_execution_package(
    *,
    package_id: str,
    package_revision: int,
    previous_package_digest: str,
    activation_profile: ActivationProfile,
    run_binding: RunBinding,
    active_contract: CanonicalExecutionContract,
    pre_execution_assessment_ref: str,
    pre_execution_assessment: CompletionAssessment,
    runtime_selection: Mapping[str, Any],
    exact_tool_authorization_projection: Sequence[str],
    security_policy_refs: Sequence[str],
    quality_policy_refs: Sequence[str],
    codex_backed_worker: bool,
    codex_auth_readiness: CodexAuthReadinessEvidence | None,
    resume_cursor: str = "",
    checkpoint_refs: Sequence[str] = (),
    effect_refs: Sequence[str] = (),
) -> ExecutionPackage:
    require_valid_active_contract(active_contract)
    if not isinstance(codex_backed_worker, bool):
        raise PackageBuildError(
            "codex_backed_worker must be boolean",
            reason_taxonomy="CODEX_BACKEND_BINDING_INVALID",
        )
    if not isinstance(package_id, str) or not package_id.strip() or package_revision < 1:
        raise PackageBuildError("invalid package identity", reason_taxonomy="PACKAGE_IDENTITY_INVALID")
    if package_revision == 1 and previous_package_digest.strip():
        raise PackageBuildError(
            "first Package revision cannot name previous_package_digest",
            reason_taxonomy="PACKAGE_REVISION_LINEAGE_INVALID",
        )
    if package_revision > 1 and not previous_package_digest.strip():
        raise PackageBuildError(
            "Package revision >1 requires previous_package_digest",
            reason_taxonomy="PACKAGE_REVISION_LINEAGE_INVALID",
        )
    if not isinstance(pre_execution_assessment_ref, str) or not pre_execution_assessment_ref.strip():
        raise PackageBuildError(
            "pre-execution CompletionAssessment ref is required",
            reason_taxonomy="COMPLETION_PROJECTION_MISSING",
        )
    source_digests = dict(active_contract.source_digests)
    expected_sources = {
        "plan": run_binding.plan_digest,
        "requirement": run_binding.requirement_digest,
        "semantic": run_binding.semantic_digest,
    }
    for key, expected in expected_sources.items():
        if source_digests.get(key) != expected:
            raise PackageBuildError(
                f"{key} digest does not match ACTIVE Contract source binding",
                reason_taxonomy="SOURCE_DIGEST_BINDING_DRIFT",
            )
    obligation = derive_execution_obligation(active_contract.task_effect_policy, pre_execution_assessment)
    obligation_digest = _obligation_result_digest(active_contract, pre_execution_assessment, obligation)
    tools = _sorted_unique_strings(
        exact_tool_authorization_projection, field_name="exact_tool_authorization_projection"
    )
    if not set(tools).issubset(set(active_contract.allowed_capabilities)):
        raise PackageBuildError(
            "tool authorization projection exceeds ACTIVE Contract capability set",
            reason_taxonomy="TOOL_AUTHORIZATION_SCOPE_EXCEEDED",
        )
    security_refs = _sorted_unique_strings(security_policy_refs, field_name="security_policy_refs")
    if active_contract.security_requirements and not security_refs:
        raise PackageBuildError(
            "Package security refs are required by ACTIVE Contract security requirements",
            reason_taxonomy="SECURITY_BINDING_MISSING",
        )
    quality_refs = _sorted_unique_strings(quality_policy_refs, field_name="quality_policy_refs")
    if active_contract.quality_criteria_contract_ref not in quality_refs:
        raise PackageBuildError(
            "Package quality refs must include ACTIVE Contract quality criteria ref",
            reason_taxonomy="QUALITY_BINDING_MISSING",
        )
    contract_ref = (
        f"contract://{active_contract.contract_id}@{active_contract.contract_version}"
        f"#{active_contract.contract_digest}"
    )
    auth_ref = ""
    if codex_backed_worker:
        if codex_auth_readiness is None:
            raise PackageBuildError(
                "Codex-backed Worker requires current auth readiness evidence",
                reason_taxonomy="CODEX_AUTH_READINESS_MISSING",
            )
        expected_binding = codex_launch_binding_digest(
            cli_version=codex_auth_readiness.cli_version,
            environment_fingerprint=codex_auth_readiness.environment_fingerprint,
            transport_schema_digest=codex_auth_readiness.transport_schema_digest,
            run_id=run_binding.run_id,
            worker_task_id=run_binding.worker_task_id,
            package_id=package_id.strip(),
            package_revision=package_revision,
        )
        if (
            codex_auth_readiness.auth_status != READY
            or codex_auth_readiness.recheck_policy != ALWAYS_BEFORE_CODEX_LAUNCH
            or codex_auth_readiness.launch_binding_digest != expected_binding
        ):
            raise PackageBuildError(
                "Codex auth readiness is not current for this launch",
                reason_taxonomy="CODEX_AUTH_READINESS_STALE_OR_DRIFTED",
            )
        auth_ref = codex_auth_readiness.evidence_id
    base = {
        "package_id": package_id.strip(),
        "package_revision": package_revision,
        "previous_package_digest": previous_package_digest.strip(),
        "activation_profile": activation_profile.value,
        "run_binding": run_binding.to_dict(),
        "contract_ref": contract_ref,
        "contract_id": active_contract.contract_id,
        "contract_version": active_contract.contract_version,
        "contract_digest": active_contract.contract_digest,
        "contract_activation_digest": active_contract.activation_digest,
        "pre_execution_completion_assessment_ref": pre_execution_assessment_ref.strip(),
        "criterion_set_digest": pre_execution_assessment.criterion_set_digest,
        "execution_obligation": obligation.value,
        "obligation_derivation_version": active_contract.obligation_derivation_version,
        "obligation_derivation_result_digest": obligation_digest,
        "purpose": active_contract.purpose,
        "task_effect_policy": active_contract.task_effect_policy.value,
        "change_targets": list(active_contract.change_targets),
        "owned_scope_projection": list(active_contract.owned_scope),
        "completion_criteria_ids": list(active_contract.completion_criteria_ids),
        "validation_criteria": list(active_contract.validation_criteria),
        "quality_criteria_contract_ref": active_contract.quality_criteria_contract_ref,
        "allowed_worker_terminal_states": list(active_contract.allowed_worker_terminal_states),
        "allowed_capabilities": list(active_contract.allowed_capabilities),
        "permission_requirements": list(active_contract.permission_requirements),
        "security_requirements": list(active_contract.security_requirements),
        "evidence_requirements": list(active_contract.evidence_requirements),
        "remediation_policy_ref": active_contract.remediation_policy_ref,
        "source_digests": dict(active_contract.source_digests),
        "approval_refs": list(active_contract.approval_refs),
        "runtime_selection": _thaw_json_value(_freeze_json_value(dict(runtime_selection))),
        "exact_tool_authorization_projection": list(tools),
        "security_policy_refs": list(security_refs),
        "quality_policy_refs": list(quality_refs),
        "codex_backed_worker": codex_backed_worker,
        "codex_auth_readiness_ref": auth_ref,
        "resume_cursor": resume_cursor.strip(),
        "checkpoint_refs": list(_sorted_unique_strings(checkpoint_refs, field_name="checkpoint_refs")),
        "effect_refs": list(_sorted_unique_strings(effect_refs, field_name="effect_refs")),
        "schema_version": PACKAGE_SCHEMA_VERSION,
    }
    return ExecutionPackage(
        package_id=base["package_id"],
        package_revision=package_revision,
        previous_package_digest=base["previous_package_digest"],
        activation_profile=activation_profile,
        run_binding=run_binding,
        contract_ref=contract_ref,
        contract_id=active_contract.contract_id,
        contract_version=active_contract.contract_version,
        contract_digest=active_contract.contract_digest,
        contract_activation_digest=active_contract.activation_digest,
        pre_execution_completion_assessment_ref=base["pre_execution_completion_assessment_ref"],
        criterion_set_digest=pre_execution_assessment.criterion_set_digest,
        execution_obligation=obligation,
        obligation_derivation_version=active_contract.obligation_derivation_version,
        obligation_derivation_result_digest=obligation_digest,
        purpose=active_contract.purpose,
        task_effect_policy=active_contract.task_effect_policy,
        change_targets=active_contract.change_targets,
        owned_scope_projection=active_contract.owned_scope,
        completion_criteria_ids=active_contract.completion_criteria_ids,
        validation_criteria=active_contract.validation_criteria,
        quality_criteria_contract_ref=active_contract.quality_criteria_contract_ref,
        allowed_worker_terminal_states=active_contract.allowed_worker_terminal_states,
        allowed_capabilities=active_contract.allowed_capabilities,
        permission_requirements=active_contract.permission_requirements,
        security_requirements=active_contract.security_requirements,
        evidence_requirements=active_contract.evidence_requirements,
        remediation_policy_ref=active_contract.remediation_policy_ref,
        source_digests=MappingProxyType(dict(active_contract.source_digests)),
        approval_refs=active_contract.approval_refs,
        runtime_selection=_freeze_json_value(dict(runtime_selection)),
        exact_tool_authorization_projection=tools,
        security_policy_refs=tuple(base["security_policy_refs"]),
        quality_policy_refs=tuple(base["quality_policy_refs"]),
        codex_backed_worker=codex_backed_worker,
        codex_auth_readiness_ref=auth_ref,
        resume_cursor=base["resume_cursor"],
        checkpoint_refs=tuple(base["checkpoint_refs"]),
        effect_refs=tuple(base["effect_refs"]),
        schema_version=PACKAGE_SCHEMA_VERSION,
        package_digest=_digest(base),
    )


@dataclass(frozen=True, slots=True)
class PreflightContext:
    activation_profile: ActivationProfile
    run_binding: RunBinding
    active_contract: CanonicalExecutionContract
    current_pre_execution_assessment_ref: str
    current_pre_execution_assessment: CompletionAssessment
    current_codex_auth_readiness: CodexAuthReadinessEvidence | None
    current_exact_tool_authorization_projection: tuple[str, ...]
    current_codex_backed_worker: bool
    expected_package_revision: int
    expected_previous_package_digest: str
    current_approval_context: ApprovalContext | None = None
    current_security_policy_refs: tuple[str, ...] = ()
    current_resume_cursor: str = ""
    current_checkpoint_refs: tuple[str, ...] = ()
    current_effect_refs: tuple[str, ...] = ()
    expected_cli_version: str = ""
    expected_environment_fingerprint: str = ""
    expected_transport_schema_digest: str = ""


@dataclass(frozen=True, slots=True)
class PreflightResult:
    ready: bool
    evidence_digest: str
    reason_taxonomy: str = "PASS"


def preflight_execution_package(package: ExecutionPackage, context: PreflightContext) -> PreflightResult:
    def block(message: str, reason: str) -> None:
        raise PreflightBlocked(message, reason_taxonomy=reason)

    if package.package_digest != _digest(package.canonical_projection()):
        block("sealed package digest mismatch", "PACKAGE_TAMPER_OR_DRIFT")
    if package.schema_version != PACKAGE_SCHEMA_VERSION:
        block("unsupported package schema", "PACKAGE_SCHEMA_DRIFT")
    if not isinstance(context.expected_package_revision, int) or context.expected_package_revision < 1:
        block("expected Package revision is invalid", "PACKAGE_REVISION_LINEAGE_INVALID")
    if package.package_revision != context.expected_package_revision:
        block("Package revision does not match current append-only lineage", "PACKAGE_REVISION_LINEAGE_DRIFT")
    if package.previous_package_digest != context.expected_previous_package_digest.strip():
        block("previous Package digest does not match current append-only lineage", "PACKAGE_REVISION_LINEAGE_DRIFT")
    try:
        require_valid_active_contract(context.active_contract)
    except PackageBuildError as exc:
        block(str(exc), exc.reason_taxonomy)
    if context.current_approval_context is None:
        block("current approval context is required", "APPROVAL_CONTEXT_MISSING")
    try:
        context.current_approval_context.require_contract_build_eligible(
            expected_semantic_digest=dict(context.active_contract.source_digests).get("semantic")
        )
    except ContractBuildError as exc:
        block(str(exc), exc.reason_taxonomy)
    current_approval_refs = context.current_approval_context.approval_refs()
    current_approval_ref = context.current_approval_context.full_plan_approval_ref.strip()
    if context.active_contract.approval_refs != current_approval_refs:
        block("current approval lineage does not exactly match ACTIVE Contract", "APPROVAL_BINDING_DRIFT")
    expected_contract_ref = (
        f"contract://{context.active_contract.contract_id}@{context.active_contract.contract_version}"
        f"#{context.active_contract.contract_digest}"
    )
    if package.contract_ref != expected_contract_ref:
        block("Contract ref mismatch", "CONTRACT_REF_DRIFT")
    if (
        package.contract_id != context.active_contract.contract_id
        or package.contract_version != context.active_contract.contract_version
        or package.contract_digest != context.active_contract.contract_digest
        or package.contract_activation_digest != context.active_contract.activation_digest
    ):
        block("Contract binding mismatch", "CONTRACT_BINDING_DRIFT")
    direct_contract_projection_matches = all(
        (
            package.purpose == context.active_contract.purpose,
            package.task_effect_policy is context.active_contract.task_effect_policy,
            package.change_targets == context.active_contract.change_targets,
            package.owned_scope_projection == context.active_contract.owned_scope,
            package.completion_criteria_ids == context.active_contract.completion_criteria_ids,
            package.validation_criteria == context.active_contract.validation_criteria,
            package.quality_criteria_contract_ref == context.active_contract.quality_criteria_contract_ref,
            package.allowed_worker_terminal_states == context.active_contract.allowed_worker_terminal_states,
            package.allowed_capabilities == context.active_contract.allowed_capabilities,
            package.permission_requirements == context.active_contract.permission_requirements,
            package.security_requirements == context.active_contract.security_requirements,
            package.evidence_requirements == context.active_contract.evidence_requirements,
            package.remediation_policy_ref == context.active_contract.remediation_policy_ref,
            dict(package.source_digests) == dict(context.active_contract.source_digests),
            package.approval_refs == context.active_contract.approval_refs,
        )
    )
    if not direct_contract_projection_matches:
        block("Package minimum Contract projection drift", "PACKAGE_CONTRACT_PROJECTION_DRIFT")
    expected_sources = {
        "plan": context.run_binding.plan_digest,
        "requirement": context.run_binding.requirement_digest,
        "semantic": context.run_binding.semantic_digest,
    }
    for key, expected in expected_sources.items():
        if dict(context.active_contract.source_digests).get(key) != expected:
            block(f"{key} source digest drift", "SOURCE_DIGEST_BINDING_DRIFT")
    if context.active_contract.quality_criteria_contract_ref not in package.quality_policy_refs:
        block("quality criteria Contract ref missing from Package", "QUALITY_BINDING_MISSING")
    current_security_refs = _sorted_unique_strings(
        context.current_security_policy_refs, field_name="current_security_policy_refs"
    )
    if context.active_contract.security_requirements and not current_security_refs:
        block("current security policy refs are required", "SECURITY_BINDING_MISSING")
    if package.security_policy_refs != current_security_refs:
        block("security policy binding drift", "SECURITY_BINDING_DRIFT")
    if package.resume_cursor != context.current_resume_cursor.strip():
        block("resume cursor drift", "RESUME_BINDING_DRIFT")
    current_checkpoint_refs = _sorted_unique_strings(
        context.current_checkpoint_refs, field_name="current_checkpoint_refs"
    )
    if package.checkpoint_refs != current_checkpoint_refs:
        block("checkpoint binding drift", "CHECKPOINT_BINDING_DRIFT")
    current_effect_refs = _sorted_unique_strings(
        context.current_effect_refs, field_name="current_effect_refs"
    )
    if package.effect_refs != current_effect_refs:
        block("effect binding drift", "EFFECT_BINDING_DRIFT")
    if package.activation_profile is not context.activation_profile:
        block("activation profile mismatch", "ACTIVATION_PROFILE_DRIFT")
    if package.run_binding != context.run_binding:
        block("run binding mismatch", "RUN_BINDING_DRIFT")
    if package.owned_scope_projection != context.active_contract.owned_scope:
        block("owned scope projection mismatch", "SCOPE_PROJECTION_DRIFT")
    current_tools = _sorted_unique_strings(
        context.current_exact_tool_authorization_projection,
        field_name="current_exact_tool_authorization_projection",
    )
    if not set(current_tools).issubset(set(context.active_contract.allowed_capabilities)):
        block("current tool authorization exceeds Contract", "TOOL_AUTHORIZATION_DRIFT")
    if package.exact_tool_authorization_projection != current_tools:
        block("tool authorization binding drift", "TOOL_AUTHORIZATION_BINDING_DRIFT")
    if not package.pre_execution_completion_assessment_ref or not package.criterion_set_digest:
        block("current CompletionAssessment projection missing", "COMPLETION_PROJECTION_MISSING")
    if package.pre_execution_completion_assessment_ref != context.current_pre_execution_assessment_ref:
        block("CompletionAssessment ref is stale", "COMPLETION_ASSESSMENT_REF_DRIFT")
    if package.criterion_set_digest != context.current_pre_execution_assessment.criterion_set_digest:
        block("completion criterion digest mismatch", "COMPLETION_CRITERION_DIGEST_DRIFT")
    expected_obligation = derive_execution_obligation(
        context.active_contract.task_effect_policy, context.current_pre_execution_assessment
    )
    expected_obligation_digest = _obligation_result_digest(
        context.active_contract, context.current_pre_execution_assessment, expected_obligation
    )
    if (
        package.execution_obligation is not expected_obligation
        or package.obligation_derivation_version != context.active_contract.obligation_derivation_version
        or package.obligation_derivation_result_digest != expected_obligation_digest
    ):
        block("ExecutionObligation projection mismatch", "EXECUTION_OBLIGATION_DRIFT")
    if expected_obligation is ExecutionObligation.BLOCKED:
        block("ExecutionObligation is BLOCKED", "BLOCKED_COMPLETION_CONTRACT")

    if not isinstance(context.current_codex_backed_worker, bool):
        block("current Codex-backed Worker indicator must be boolean", "CODEX_BACKEND_BINDING_INVALID")
    if package.codex_backed_worker != context.current_codex_backed_worker:
        block("Codex-backed Worker binding drift", "CODEX_BACKEND_BINDING_DRIFT")
    if package.codex_backed_worker:
        if not package.codex_auth_readiness_ref:
            block("Codex-backed Worker auth readiness ref is missing", "CODEX_AUTH_READINESS_MISSING_OR_STALE")
        evidence = context.current_codex_auth_readiness
        if evidence is None or evidence.evidence_id != package.codex_auth_readiness_ref:
            block("Codex auth readiness evidence missing/stale", "CODEX_AUTH_READINESS_MISSING_OR_STALE")
        if evidence.auth_status != READY or evidence.recheck_policy != ALWAYS_BEFORE_CODEX_LAUNCH:
            block("Codex auth readiness not READY/current", "CODEX_AUTH_READINESS_NOT_READY")
        if context.expected_cli_version and evidence.cli_version != context.expected_cli_version:
            block("Codex cli version drift", "CODEX_CLI_VERSION_DRIFT")
        if context.expected_environment_fingerprint and evidence.environment_fingerprint != context.expected_environment_fingerprint:
            block("Codex environment drift", "CODEX_ENVIRONMENT_DRIFT")
        if context.expected_transport_schema_digest and evidence.transport_schema_digest != context.expected_transport_schema_digest:
            block("Codex transport/schema drift", "CODEX_TRANSPORT_SCHEMA_DRIFT")
        expected_binding = codex_launch_binding_digest(
            cli_version=evidence.cli_version,
            environment_fingerprint=evidence.environment_fingerprint,
            transport_schema_digest=evidence.transport_schema_digest,
            run_id=context.run_binding.run_id,
            worker_task_id=context.run_binding.worker_task_id,
            package_id=package.package_id,
            package_revision=package.package_revision,
        )
        if evidence.launch_binding_digest != expected_binding:
            block("Codex auth readiness launch binding stale", "CODEX_AUTH_LAUNCH_BINDING_DRIFT")
    elif package.codex_auth_readiness_ref:
        block("non-Codex Package must not carry Codex auth readiness ref", "CODEX_BACKEND_BINDING_DRIFT")

    evidence_digest = _digest(
        {
            "package_digest": package.package_digest,
            "package_revision": package.package_revision,
            "previous_package_digest": package.previous_package_digest,
            "contract_activation_digest": context.active_contract.activation_digest,
            "completion_assessment_ref": context.current_pre_execution_assessment_ref,
            "completion_criterion_digest": context.current_pre_execution_assessment.criterion_set_digest,
            "execution_obligation": expected_obligation.value,
            "approval_ref": current_approval_ref,
            "approval_refs": list(current_approval_refs),
            "exact_tool_authorization_projection": list(current_tools),
            "security_policy_refs": list(current_security_refs),
            "codex_backed_worker": package.codex_backed_worker,
            "resume_cursor": package.resume_cursor,
            "checkpoint_refs": list(package.checkpoint_refs),
            "effect_refs": list(package.effect_refs),
            "auth_ref": package.codex_auth_readiness_ref,
        }
    )
    return PreflightResult(ready=True, evidence_digest=evidence_digest)
