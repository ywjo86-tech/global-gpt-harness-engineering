from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .completion_authority import FrozenCompletionAuthority
from .completion_contract import TaskEffectPolicy
from .execution_contract import (
    ActivationProfile,
    ApprovedExecutionProjection,
    CanonicalExecutionContract,
    RunBinding,
    activate_contract,
    build_contract_candidate,
    cross_check_contract,
)
from .migration_authority import (
    MigrationAuthorityEvidence,
    MigrationAuthorityError,
)
from .migration_quality_authority import (
    ApprovedMigrationQualityCriteriaContract,
    MigrationQualityAuthorityError,
    validate_approved_migration_quality_contract,
)


class CanonicalContractBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class ApprovedTaskContractInputs:
    requirement_refs: tuple[str, ...]
    plan_task_ref: str
    purpose: str
    task_effect_policy: TaskEffectPolicy
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


@dataclass(frozen=True, slots=True)
class CanonicalContractBridgeResult:
    approved_projection: ApprovedExecutionProjection
    active_contract: CanonicalExecutionContract
    run_binding: RunBinding


def build_approved_projection(
    *,
    authority: MigrationAuthorityEvidence,
    completion_authority: FrozenCompletionAuthority,
    task: ApprovedTaskContractInputs,
    canonical_plan_sha256: str,
    requirements_sha256: str,
) -> ApprovedExecutionProjection:
    if authority.activation_profile is not ActivationProfile.MIGRATION_APPROVED_PLAN:
        raise CanonicalContractBridgeError(
            "Phase4A bridge requires MIGRATION_APPROVED_PLAN authority",
            reason_taxonomy="CANONICAL_BRIDGE_PROFILE_INVALID",
        )
    if completion_authority.task_ref != task.plan_task_ref:
        raise CanonicalContractBridgeError(
            "Completion authority task does not match approved Plan task",
            reason_taxonomy="CANONICAL_BRIDGE_COMPLETION_TASK_DRIFT",
        )

    try:
        run_sources = authority.run_source_digests(
            plan_digest=canonical_plan_sha256,
            requirement_digest=requirements_sha256,
        )
    except MigrationAuthorityError as exc:
        raise CanonicalContractBridgeError(
            "run-specific Plan/Requirement binding is unavailable",
            reason_taxonomy=exc.reason_taxonomy,
        ) from exc

    completion_ids = tuple(item.criterion_id for item in completion_authority.criteria)
    if not completion_ids:
        raise CanonicalContractBridgeError(
            "Completion authority contains no criteria",
            reason_taxonomy="CANONICAL_BRIDGE_COMPLETION_MISSING",
        )

    return ApprovedExecutionProjection(
        requirement_refs=task.requirement_refs,
        plan_task_ref=task.plan_task_ref,
        purpose=task.purpose,
        task_effect_policy=task.task_effect_policy,
        completion_criteria_ids=completion_ids,
        validation_criteria=task.validation_criteria,
        quality_criteria_contract_ref=task.quality_criteria_contract_ref,
        change_targets=task.change_targets,
        owned_scope=task.owned_scope,
        allowed_worker_terminal_states=task.allowed_worker_terminal_states,
        allowed_capabilities=task.allowed_capabilities,
        permission_requirements=task.permission_requirements,
        security_requirements=task.security_requirements,
        evidence_requirements=task.evidence_requirements,
        remediation_policy_ref=task.remediation_policy_ref,
        source_digests=run_sources,
    )


def build_active_contract_and_run_binding(
    *,
    authority: MigrationAuthorityEvidence,
    completion_authority: FrozenCompletionAuthority,
    task: ApprovedTaskContractInputs,
    project_id: str,
    gate_id: str,
    lv_id: str,
    run_id: str,
    worker_task_id: str,
    plan_version: str,
    canonical_plan_sha256: str,
    requirement_version: str,
    requirements_sha256: str,
    semantic_version: str,
    contract_id: str,
    contract_version: str,
    parent_contract_id: str = "",
) -> CanonicalContractBridgeResult:
    if worker_task_id != task.plan_task_ref or worker_task_id != completion_authority.task_ref:
        raise CanonicalContractBridgeError(
            "Worker task binding does not match approved task and Completion authority",
            reason_taxonomy="CANONICAL_BRIDGE_WORKER_TASK_DRIFT",
        )

    projection = build_approved_projection(
        authority=authority,
        completion_authority=completion_authority,
        task=task,
        canonical_plan_sha256=canonical_plan_sha256,
        requirements_sha256=requirements_sha256,
    )
    approval_context = authority.approval_context()

    candidate = build_contract_candidate(
        contract_id=contract_id,
        contract_version=contract_version,
        parent_contract_id=parent_contract_id,
        approved_projection=projection,
        approval_context=approval_context,
    )
    cross_check = cross_check_contract(candidate, projection, approval_context)
    if not cross_check.passed:
        raise CanonicalContractBridgeError(
            f"Canonical Contract Cross-Check failed: {cross_check.reason_taxonomy}",
            reason_taxonomy="CANONICAL_BRIDGE_CONTRACT_CROSS_CHECK_FAILED",
        )
    active = activate_contract(
        candidate,
        cross_check=cross_check,
        approved_projection=projection,
        approval_context=approval_context,
    )

    run_binding = RunBinding(
        project_id=project_id,
        gate_id=gate_id,
        lv_id=lv_id,
        run_id=run_id,
        worker_task_id=worker_task_id,
        plan_version=plan_version,
        plan_digest=canonical_plan_sha256,
        requirement_version=requirement_version,
        requirement_digest=requirements_sha256,
        semantic_version=semantic_version,
        semantic_digest=authority.semantic_digest,
    )

    # Fail closed on the exact source-domain invariant before any Package build.
    expected = {
        "plan": run_binding.plan_digest,
        "requirement": run_binding.requirement_digest,
        "semantic": run_binding.semantic_digest,
    }
    actual = {
        key: active.source_digests.get(key, "")
        for key in ("plan", "requirement", "semantic")
    }
    if actual != expected:
        raise CanonicalContractBridgeError(
            "ACTIVE Contract and RunBinding source digests are not exact-compatible",
            reason_taxonomy="CANONICAL_BRIDGE_SOURCE_DIGEST_DRIFT",
        )

    return CanonicalContractBridgeResult(
        approved_projection=projection,
        active_contract=active,
        run_binding=run_binding,
    )


def build_migration_quality_bound_active_contract_and_run_binding(
    *,
    migration_quality_contract: ApprovedMigrationQualityCriteriaContract,
    authority: MigrationAuthorityEvidence,
    completion_authority: FrozenCompletionAuthority,
    task: ApprovedTaskContractInputs,
    project_id: str,
    gate_id: str,
    lv_id: str,
    run_id: str,
    worker_task_id: str,
    plan_version: str,
    canonical_plan_sha256: str,
    requirement_version: str,
    requirements_sha256: str,
    semantic_version: str,
    contract_id: str,
    contract_version: str,
    parent_contract_id: str = "",
) -> CanonicalContractBridgeResult:
    try:
        validate_approved_migration_quality_contract(migration_quality_contract)
    except MigrationQualityAuthorityError as exc:
        raise CanonicalContractBridgeError(
            "approved migration quality contract is invalid",
            reason_taxonomy=exc.reason_taxonomy,
        ) from exc

    if task.quality_criteria_contract_ref != migration_quality_contract.contract_ref:
        raise CanonicalContractBridgeError(
            "approved task quality ref does not exactly bind the migration quality contract",
            reason_taxonomy="CANONICAL_BRIDGE_MIGRATION_QUALITY_REF_DRIFT",
        )

    result = build_active_contract_and_run_binding(
        authority=authority,
        completion_authority=completion_authority,
        task=task,
        project_id=project_id,
        gate_id=gate_id,
        lv_id=lv_id,
        run_id=run_id,
        worker_task_id=worker_task_id,
        plan_version=plan_version,
        canonical_plan_sha256=canonical_plan_sha256,
        requirement_version=requirement_version,
        requirements_sha256=requirements_sha256,
        semantic_version=semantic_version,
        contract_id=contract_id,
        contract_version=contract_version,
        parent_contract_id=parent_contract_id,
    )
    if result.active_contract.quality_criteria_contract_ref != migration_quality_contract.contract_ref:
        raise CanonicalContractBridgeError(
            "ACTIVE Contract lost exact migration quality binding",
            reason_taxonomy="CANONICAL_BRIDGE_MIGRATION_QUALITY_BINDING_DRIFT",
        )
    return result
