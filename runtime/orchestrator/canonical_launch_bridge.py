from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .codex_readiness import (
    ReadinessProbeSet,
    recheck_codex_auth_readiness,
)
from .completion_contract import CompletionAssessment
from .execution_contract import (
    ActivationProfile,
    ApprovalContext,
    CanonicalExecutionContract,
    CodexAuthReadinessEvidence,
    ExecutionPackage,
    PreflightContext,
    PreflightResult,
    RunBinding,
    build_execution_package,
    preflight_execution_package,
)
from .migration_quality_authority import (
    ApprovedMigrationQualityCriteriaContract,
    MigrationQualityAuthorityError,
    validate_approved_migration_quality_contract,
)
from .worker_authority import (
    WorkerLaunchAuthorization,
    authorize_worker_launch,
    execution_package_ref,
)


class CanonicalLaunchBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class CanonicalLaunchBridgeResult:
    package: ExecutionPackage
    preflight: PreflightResult
    launch_authorization: WorkerLaunchAuthorization
    readiness_recheck: CodexAuthReadinessEvidence
    gateway_authority_binding: Mapping[str, Any]
    gateway_authority_binding_digest: str


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalLaunchBridgeError(
            "canonical launch authority is not serializable",
            reason_taxonomy="CANONICAL_LAUNCH_BINDING_INVALID",
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _authority_binding(
    *,
    package: ExecutionPackage,
    preflight: PreflightResult,
    launch: WorkerLaunchAuthorization,
    initial_readiness: CodexAuthReadinessEvidence,
    readiness_recheck: CodexAuthReadinessEvidence,
    migration_authority_ref: str,
) -> tuple[Mapping[str, Any], str]:
    if not isinstance(migration_authority_ref, str) or not migration_authority_ref.strip():
        raise CanonicalLaunchBridgeError(
            "migration authority ref is required",
            reason_taxonomy="CANONICAL_LAUNCH_MIGRATION_AUTHORITY_MISSING",
        )

    projection = {
        "schema_version": "orchestration.canonical-launch-authority.v1",
        "package_ref": execution_package_ref(package),
        "package_digest": package.package_digest,
        "contract_ref": package.contract_ref,
        "contract_digest": package.contract_digest,
        "contract_activation_digest": package.contract_activation_digest,
        "worker_task_id": package.run_binding.worker_task_id,
        "criterion_set_digest": package.criterion_set_digest,
        "execution_obligation": package.execution_obligation.value,
        "preflight_evidence_digest": preflight.evidence_digest,
        "codex_auth_readiness_ref": initial_readiness.evidence_id,
        "codex_auth_recheck_evidence_ref": readiness_recheck.evidence_id,
        "launch_authorization_digest": launch.authorization_digest,
        "migration_authority_ref": migration_authority_ref.strip(),
    }
    return MappingProxyType(dict(projection)), _digest(projection)


def build_canonical_launch(
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
    codex_auth_readiness: CodexAuthReadinessEvidence,
    approval_context: ApprovalContext,
    migration_authority_ref: str,
    migration_quality_contract: ApprovedMigrationQualityCriteriaContract | None = None,
    readiness_recheck_probes: ReadinessProbeSet | None = None,
    readiness_recheck_verified_at_utc: str | None = None,
    resume_cursor: str = "",
    checkpoint_refs: Sequence[str] = (),
    effect_refs: Sequence[str] = (),
    remediation_attempt_event_id: str = "",
) -> CanonicalLaunchBridgeResult:
    if active_contract.quality_criteria_contract_ref.startswith("migration-quality://"):
        if migration_quality_contract is None:
            raise CanonicalLaunchBridgeError(
                "migration-quality ACTIVE Contract requires the exact approved quality contract",
                reason_taxonomy="CANONICAL_LAUNCH_MIGRATION_QUALITY_MISSING",
            )
        try:
            validate_approved_migration_quality_contract(migration_quality_contract)
        except MigrationQualityAuthorityError as exc:
            raise CanonicalLaunchBridgeError(
                "migration quality contract is invalid at launch",
                reason_taxonomy=exc.reason_taxonomy,
            ) from exc
        if active_contract.quality_criteria_contract_ref != migration_quality_contract.contract_ref:
            raise CanonicalLaunchBridgeError(
                "ACTIVE Contract migration quality ref drifted before Package build",
                reason_taxonomy="CANONICAL_LAUNCH_MIGRATION_QUALITY_REF_DRIFT",
            )

    package = build_execution_package(
        package_id=package_id,
        package_revision=package_revision,
        previous_package_digest=previous_package_digest,
        activation_profile=activation_profile,
        run_binding=run_binding,
        active_contract=active_contract,
        pre_execution_assessment_ref=pre_execution_assessment_ref,
        pre_execution_assessment=pre_execution_assessment,
        runtime_selection=runtime_selection,
        exact_tool_authorization_projection=exact_tool_authorization_projection,
        security_policy_refs=security_policy_refs,
        quality_policy_refs=quality_policy_refs,
        codex_backed_worker=True,
        codex_auth_readiness=codex_auth_readiness,
        resume_cursor=resume_cursor,
        checkpoint_refs=checkpoint_refs,
        effect_refs=effect_refs,
    )

    if migration_quality_contract is not None:
        if (
            package.quality_criteria_contract_ref != migration_quality_contract.contract_ref
            or migration_quality_contract.contract_ref not in package.quality_policy_refs
        ):
            raise CanonicalLaunchBridgeError(
                "ExecutionPackage lost exact migration quality binding",
                reason_taxonomy="CANONICAL_LAUNCH_MIGRATION_QUALITY_PACKAGE_DRIFT",
            )

    preflight_context = PreflightContext(
        activation_profile=activation_profile,
        run_binding=run_binding,
        active_contract=active_contract,
        current_pre_execution_assessment_ref=pre_execution_assessment_ref,
        current_pre_execution_assessment=pre_execution_assessment,
        current_codex_auth_readiness=codex_auth_readiness,
        current_exact_tool_authorization_projection=tuple(exact_tool_authorization_projection),
        current_codex_backed_worker=True,
        expected_package_revision=package_revision,
        expected_previous_package_digest=previous_package_digest,
        current_approval_context=approval_context,
        current_security_policy_refs=tuple(security_policy_refs),
        current_resume_cursor=resume_cursor,
        current_checkpoint_refs=tuple(checkpoint_refs),
        current_effect_refs=tuple(effect_refs),
        expected_cli_version=codex_auth_readiness.cli_version,
        expected_environment_fingerprint=codex_auth_readiness.environment_fingerprint,
        expected_transport_schema_digest=codex_auth_readiness.transport_schema_digest,
    )
    preflight = preflight_execution_package(package, preflight_context)

    # Re-probe after Package + canonical preflight and immediately before launch
    # authorization. The Package remains bound to the original readiness evidence
    # id; the recheck proves that its stable facts are still current.
    readiness_recheck = recheck_codex_auth_readiness(
        codex_auth_readiness,
        run_id=run_binding.run_id,
        worker_task_id=run_binding.worker_task_id,
        package_id=package.package_id,
        package_revision=package.package_revision,
        probes=readiness_recheck_probes,
        verified_at_utc=readiness_recheck_verified_at_utc,
    )

    launch = authorize_worker_launch(
        package,
        preflight,
        remediation_attempt_event_id=remediation_attempt_event_id,
    )

    binding, binding_digest = _authority_binding(
        package=package,
        preflight=preflight,
        launch=launch,
        initial_readiness=codex_auth_readiness,
        readiness_recheck=readiness_recheck,
        migration_authority_ref=migration_authority_ref,
    )
    return CanonicalLaunchBridgeResult(
        package=package,
        preflight=preflight,
        launch_authorization=launch,
        readiness_recheck=readiness_recheck,
        gateway_authority_binding=binding,
        gateway_authority_binding_digest=binding_digest,
    )
