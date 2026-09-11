from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

from .canonical_contract_bridge import (
    ApprovedTaskContractInputs,
    CanonicalContractBridgeResult,
    build_migration_quality_bound_active_contract_and_run_binding,
)
from .canonical_launch_bridge import CanonicalLaunchBridgeResult, build_canonical_launch
from .codex_readiness import ReadinessProbeSet
from .completion_authority import (
    FrozenCompletionAuthority,
    materialize_task_4a_08_completion_authority,
)
from .completion_contract import CompletionAssessment, TaskEffectPolicy
from .completion_contract_bridge import (
    CompletionBridgeAssessment,
    evaluate_contract_completion,
)
from .execution_contract import ActivationProfile, CodexAuthReadinessEvidence
from .lv_execution_package import canonical_json_bytes
from .tool_authorization import (
    DEC007_CONTRACT_IDS,
    DEC007_DECISION_REF,
    DEC007_WORKER_TASK_ID,
    ToolAuthorizationContract,
    ToolAuthorizationError,
    owned_scope_digest,
    validate_contract as validate_tool_authorization_contract,
)
from .migration_authority import MigrationAuthorityEvidence, load_migration_authority
from .migration_quality_authority import (
    ApprovedMigrationQualityAuthority,
    ApprovedMigrationQualityCriteriaContract,
    MIGRATION_APPROVED_PLAN,
    build_approved_migration_quality_contract,
    load_approved_migration_quality_authority,
    validate_approved_migration_quality_contract,
)


class ProductionCanonicalAuthorityError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class ProductionCanonicalContractAuthority:
    migration_authority: MigrationAuthorityEvidence
    migration_quality_authority: ApprovedMigrationQualityAuthority
    migration_quality_contract: ApprovedMigrationQualityCriteriaContract
    completion_authority: FrozenCompletionAuthority
    approved_task: ApprovedTaskContractInputs
    contract_bridge: CanonicalContractBridgeResult


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionCanonicalAuthorityError(
            f"{field} is required",
            reason_taxonomy="PRODUCTION_CANONICAL_IDENTITY_INVALID",
        )
    return value.strip()


def materialize_production_canonical_contract_authority(
    *,
    project_root: str | Path,
    harness_root: str | Path,
    completion_authority_root: str | Path,
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
    canonical_contract_id: str,
    canonical_contract_version: str,
    quality_contract_id: str,
    quality_contract_version: str,
    quality_contract_created_at_utc: str,
    verify_git_provenance: bool = True,
) -> ProductionCanonicalContractAuthority:
    """Materialize the approved migration canonical authority for one production run.

    This stage performs no Codex probe and no Worker launch.  It binds only
    pre-existing approved authority to the current run and creates the frozen
    Completion Authority snapshot in the caller-selected authority directory.
    """
    project = Path(project_root).resolve()
    harness = Path(harness_root).resolve()
    completion_root = Path(completion_authority_root).resolve()
    if not completion_root.is_dir() or completion_root.is_symlink():
        raise ProductionCanonicalAuthorityError(
            "completion authority root must already exist and be a regular directory",
            reason_taxonomy="PRODUCTION_CANONICAL_COMPLETION_ROOT_INVALID",
        )

    migration_authority = load_migration_authority(
        harness,
        verify_git_provenance=verify_git_provenance,
    )
    if migration_authority.activation_profile is not ActivationProfile.MIGRATION_APPROVED_PLAN:
        raise ProductionCanonicalAuthorityError(
            "production canonical bridge requires MIGRATION_APPROVED_PLAN authority",
            reason_taxonomy="PRODUCTION_CANONICAL_PROFILE_INVALID",
        )

    quality_authority = load_approved_migration_quality_authority(harness)
    quality_contract = build_approved_migration_quality_contract(
        authority=quality_authority,
        activation_profile=MIGRATION_APPROVED_PLAN,
        contract_id=_require_text(quality_contract_id, field="quality_contract_id"),
        contract_version=_require_text(quality_contract_version, field="quality_contract_version"),
        created_at_utc=_require_text(
            quality_contract_created_at_utc,
            field="quality_contract_created_at_utc",
        ),
    )
    validate_approved_migration_quality_contract(quality_contract)

    existing_quality_ref = task.quality_criteria_contract_ref.strip()
    if existing_quality_ref and existing_quality_ref != quality_contract.contract_ref:
        raise ProductionCanonicalAuthorityError(
            "approved task contains a conflicting migration quality contract ref",
            reason_taxonomy="PRODUCTION_CANONICAL_TASK_QUALITY_REF_DRIFT",
        )
    bound_task = replace(
        task,
        quality_criteria_contract_ref=quality_contract.contract_ref,
    )

    completion_authority = materialize_task_4a_08_completion_authority(
        project,
        completion_root,
    )
    if completion_authority.task_ref != worker_task_id:
        raise ProductionCanonicalAuthorityError(
            "frozen Completion Authority does not bind the requested Worker task",
            reason_taxonomy="PRODUCTION_CANONICAL_COMPLETION_TASK_DRIFT",
        )

    contract_bridge = build_migration_quality_bound_active_contract_and_run_binding(
        migration_quality_contract=quality_contract,
        authority=migration_authority,
        completion_authority=completion_authority,
        task=bound_task,
        project_id=_require_text(project_id, field="project_id"),
        gate_id=_require_text(gate_id, field="gate_id"),
        lv_id=_require_text(lv_id, field="lv_id"),
        run_id=_require_text(run_id, field="run_id"),
        worker_task_id=_require_text(worker_task_id, field="worker_task_id"),
        plan_version=_require_text(plan_version, field="plan_version"),
        canonical_plan_sha256=canonical_plan_sha256,
        requirement_version=_require_text(requirement_version, field="requirement_version"),
        requirements_sha256=requirements_sha256,
        semantic_version=_require_text(semantic_version, field="semantic_version"),
        contract_id=_require_text(canonical_contract_id, field="canonical_contract_id"),
        contract_version=_require_text(
            canonical_contract_version,
            field="canonical_contract_version",
        ),
    )

    active = contract_bridge.active_contract
    run_binding = contract_bridge.run_binding
    if active.quality_criteria_contract_ref != quality_contract.contract_ref:
        raise ProductionCanonicalAuthorityError(
            "ACTIVE Contract lost the approved migration quality ref",
            reason_taxonomy="PRODUCTION_CANONICAL_QUALITY_BINDING_DRIFT",
        )
    expected_sources = {
        "plan": run_binding.plan_digest,
        "requirement": run_binding.requirement_digest,
        "semantic": run_binding.semantic_digest,
    }
    actual_sources = {
        key: active.source_digests.get(key, "")
        for key in ("plan", "requirement", "semantic")
    }
    if actual_sources != expected_sources:
        raise ProductionCanonicalAuthorityError(
            "ACTIVE Contract run-source binding drift",
            reason_taxonomy="PRODUCTION_CANONICAL_RUN_SOURCE_DRIFT",
        )

    return ProductionCanonicalContractAuthority(
        migration_authority=migration_authority,
        migration_quality_authority=quality_authority,
        migration_quality_contract=quality_contract,
        completion_authority=completion_authority,
        approved_task=bound_task,
        contract_bridge=contract_bridge,
    )


def evaluate_pre_execution_completion(
    authority: ProductionCanonicalContractAuthority,
    project_root: str | Path,
    *,
    timeout: int = 120,
) -> CompletionBridgeAssessment:
    return evaluate_contract_completion(
        authority.contract_bridge.active_contract,
        authority.completion_authority,
        project_root,
        timeout=timeout,
    )


def build_production_canonical_launch_authority(
    *,
    authority: ProductionCanonicalContractAuthority,
    pre_execution_assessment_ref: str,
    pre_execution_assessment: CompletionAssessment,
    package_id: str,
    package_revision: int,
    previous_package_digest: str,
    runtime_selection: Mapping[str, object],
    exact_tool_authorization_projection: Sequence[str],
    security_policy_refs: Sequence[str],
    codex_auth_readiness: CodexAuthReadinessEvidence,
    migration_authority_ref: str,
    readiness_recheck_probes: ReadinessProbeSet | None = None,
    readiness_recheck_verified_at_utc: str | None = None,
    resume_cursor: str = "",
    checkpoint_refs: Sequence[str] = (),
    effect_refs: Sequence[str] = (),
    remediation_attempt_event_id: str = "",
) -> CanonicalLaunchBridgeResult:
    """Build Package→Preflight→WorkerLaunchAuthorization from sealed authority.

    The initial Codex readiness evidence is supplied by the caller so tests can
    remain fully injected and production can collect readiness at its explicit
    launch boundary.  This helper never silently performs the initial probe.
    """
    active = authority.contract_bridge.active_contract
    run_binding = authority.contract_bridge.run_binding
    quality_contract = authority.migration_quality_contract

    result = build_canonical_launch(
        package_id=_require_text(package_id, field="package_id"),
        package_revision=package_revision,
        previous_package_digest=previous_package_digest,
        activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
        run_binding=run_binding,
        active_contract=active,
        pre_execution_assessment_ref=_require_text(
            pre_execution_assessment_ref,
            field="pre_execution_assessment_ref",
        ),
        pre_execution_assessment=pre_execution_assessment,
        runtime_selection=runtime_selection,
        exact_tool_authorization_projection=exact_tool_authorization_projection,
        security_policy_refs=security_policy_refs,
        quality_policy_refs=(quality_contract.contract_ref,),
        codex_auth_readiness=codex_auth_readiness,
        approval_context=authority.migration_authority.approval_context(),
        migration_authority_ref=_require_text(
            migration_authority_ref,
            field="migration_authority_ref",
        ),
        migration_quality_contract=quality_contract,
        readiness_recheck_probes=readiness_recheck_probes,
        readiness_recheck_verified_at_utc=readiness_recheck_verified_at_utc,
        resume_cursor=resume_cursor,
        checkpoint_refs=checkpoint_refs,
        effect_refs=effect_refs,
        remediation_attempt_event_id=remediation_attempt_event_id,
    )

    binding = result.gateway_authority_binding
    if (
        binding.get("worker_task_id") != run_binding.worker_task_id
        or binding.get("contract_digest") != active.contract_digest
        or binding.get("package_digest") != result.package.package_digest
        or result.package.quality_criteria_contract_ref != quality_contract.contract_ref
        or quality_contract.contract_ref not in result.package.quality_policy_refs
    ):
        raise ProductionCanonicalAuthorityError(
            "canonical launch authority binding drift",
            reason_taxonomy="PRODUCTION_CANONICAL_LAUNCH_BINDING_DRIFT",
        )
    return result

def _sha256_canonical(value: object) -> str:
    import hashlib
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    import re
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProductionCanonicalAuthorityError(
            f"{field} must be a lowercase SHA-256 digest",
            reason_taxonomy="PRODUCTION_CANONICAL_DIGEST_INVALID",
        )
    return value


def derive_approved_task_from_lv_manifest(
    manifest: Mapping[str, object],
    *,
    project_id: str,
    gate_id: str,
    lv_id: str,
    run_id: str,
    canonical_plan_sha256: str,
) -> ApprovedTaskContractInputs:
    if not isinstance(manifest, Mapping):
        raise ProductionCanonicalAuthorityError(
            "sealed LV manifest must be a mapping",
            reason_taxonomy="PRODUCTION_CANONICAL_LV_MANIFEST_INVALID",
        )

    expected_identity = {
        "project_id": _require_text(project_id, field="project_id"),
        "gate_id": _require_text(gate_id, field="gate_id"),
        "lv_id": _require_text(lv_id, field="lv_id"),
        "run_id": _require_text(run_id, field="run_id"),
        "canonical_plan_sha256": _require_sha256(
            canonical_plan_sha256,
            field="canonical_plan_sha256",
        ),
    }
    for field, expected in expected_identity.items():
        if manifest.get(field) != expected:
            raise ProductionCanonicalAuthorityError(
                f"sealed LV manifest {field} drift",
                reason_taxonomy="PRODUCTION_CANONICAL_LV_IDENTITY_DRIFT",
            )

    raw_task = manifest.get("task")
    if not isinstance(raw_task, Mapping):
        raise ProductionCanonicalAuthorityError(
            "sealed LV task projection is missing",
            reason_taxonomy="PRODUCTION_CANONICAL_LV_TASK_INVALID",
        )
    purpose = raw_task.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ProductionCanonicalAuthorityError(
            "sealed LV task purpose is missing",
            reason_taxonomy="PRODUCTION_CANONICAL_LV_TASK_INVALID",
        )

    owned_raw = manifest.get("owned_files")
    checks_raw = manifest.get("completion_checks")
    if (
        not isinstance(owned_raw, list)
        or any(not isinstance(item, str) or not item for item in owned_raw)
        or not isinstance(checks_raw, list)
        or any(not isinstance(item, str) or not item for item in checks_raw)
        or not checks_raw
    ):
        raise ProductionCanonicalAuthorityError(
            "sealed LV scope or completion criteria are malformed",
            reason_taxonomy="PRODUCTION_CANONICAL_LV_SCOPE_INVALID",
        )
    owned_scope = tuple(owned_raw)

    raw_contracts = manifest.get("active_tool_authorization_contracts")
    projection = manifest.get("tool_authorization_projection")
    projection_digest = manifest.get("tool_authorization_projection_sha256")
    if not isinstance(raw_contracts, list) or not isinstance(projection, Mapping):
        raise ProductionCanonicalAuthorityError(
            "sealed DEC-007 authority is missing",
            reason_taxonomy="PRODUCTION_CANONICAL_TOOL_AUTHORITY_MISSING",
        )
    if (
        not isinstance(projection_digest, str)
        or _sha256_canonical(dict(projection)) != projection_digest
    ):
        raise ProductionCanonicalAuthorityError(
            "sealed Tool authorization projection digest drift",
            reason_taxonomy="PRODUCTION_CANONICAL_TOOL_PROJECTION_DRIFT",
        )

    contracts: list[ToolAuthorizationContract] = []
    try:
        for raw in raw_contracts:
            if not isinstance(raw, Mapping):
                raise TypeError("contract is not a mapping")
            value = dict(raw)
            value["requirement_refs"] = tuple(value.get("requirement_refs", ()))
            value["plan_task_refs"] = tuple(value.get("plan_task_refs", ()))
            contract = ToolAuthorizationContract(**value)
            validate_tool_authorization_contract(contract)
            contracts.append(contract)
    except (TypeError, ToolAuthorizationError) as exc:
        raise ProductionCanonicalAuthorityError(
            "sealed Tool authorization contract is invalid",
            reason_taxonomy="PRODUCTION_CANONICAL_TOOL_CONTRACT_INVALID",
        ) from exc

    expected_contract_ids = set(DEC007_CONTRACT_IDS.values())
    expected_operations = set(DEC007_CONTRACT_IDS)
    if (
        len(contracts) != len(expected_operations)
        or {item.contract_id for item in contracts} != expected_contract_ids
        or {item.operation_class_id for item in contracts} != expected_operations
        or projection.get("decision_ref") != DEC007_DECISION_REF
        or projection.get("worker_task_id") != DEC007_WORKER_TASK_ID
        or projection.get("active_contract_count") != len(expected_operations)
        or set(projection.get("contract_ids", ())) != expected_contract_ids
        or set(projection.get("operation_class_ids", ())) != expected_operations
        or projection.get("owned_scope_sha256") != owned_scope_digest(owned_scope)
    ):
        raise ProductionCanonicalAuthorityError(
            "sealed DEC-007 authorization set drift",
            reason_taxonomy="PRODUCTION_CANONICAL_TOOL_SET_DRIFT",
        )

    requirement_digests = projection.get("requirement_digests")
    if not isinstance(requirement_digests, Mapping):
        raise ProductionCanonicalAuthorityError(
            "sealed Tool requirement digest projection is missing",
            reason_taxonomy="PRODUCTION_CANONICAL_TOOL_REQUIREMENT_DRIFT",
        )

    for contract in contracts:
        if (
            contract.contract_status != "ACTIVE"
            or contract.worker_task_id != DEC007_WORKER_TASK_ID
            or contract.plan_task_refs != (DEC007_WORKER_TASK_ID,)
            or contract.authorization_decision_ref != DEC007_DECISION_REF
            or contract.project_id != project_id
            or contract.gate_id != gate_id
            or contract.lv_id != lv_id
            or contract.run_id != run_id
            or contract.canonical_plan_sha256 != canonical_plan_sha256
            or contract.owned_scope_sha256 != projection.get("owned_scope_sha256")
            or contract.package_binding_sha256 != projection.get("package_binding_sha256")
            or requirement_digests.get(contract.operation_class_id) != contract.requirement_digest
        ):
            raise ProductionCanonicalAuthorityError(
                "sealed Tool authorization lifecycle binding drift",
                reason_taxonomy="PRODUCTION_CANONICAL_TOOL_BINDING_DRIFT",
            )

    requirement_refs = tuple(
        sorted({ref for contract in contracts for ref in contract.requirement_refs})
    )
    if not requirement_refs:
        raise ProductionCanonicalAuthorityError(
            "sealed Tool authority provides no Requirement refs",
            reason_taxonomy="PRODUCTION_CANONICAL_REQUIREMENT_REFS_MISSING",
        )

    return ApprovedTaskContractInputs(
        requirement_refs=requirement_refs,
        plan_task_ref=DEC007_WORKER_TASK_ID,
        purpose=purpose.strip(),
        task_effect_policy=TaskEffectPolicy.MUTATING,
        validation_criteria=tuple(checks_raw),
        quality_criteria_contract_ref="",
        change_targets=owned_scope,
        owned_scope=owned_scope,
        allowed_worker_terminal_states=("BLOCKED", "CHANGED", "SKIPPED_SATISFIED"),
        allowed_capabilities=tuple(sorted(expected_operations)),
        permission_requirements=("DEC-007",),
        security_requirements=("BROKER_ONLY_EFFECT_PATH",),
        evidence_requirements=(
            "FROZEN_COMPLETION_AUTHORITY",
            "BROKER_EFFECT_RECEIPT",
        ),
        remediation_policy_ref="DEC-008:HOLD",
    )


def build_worker_authority_extra_context(
    *,
    manifest: Mapping[str, object],
    launch: CanonicalLaunchBridgeResult,
    requirements_sha256: str,
) -> Mapping[str, object]:
    run_requirement_digest = _require_sha256(
        requirements_sha256,
        field="requirements_sha256",
    )
    raw_contracts = manifest.get("active_tool_authorization_contracts")
    tool_projection = manifest.get("tool_authorization_projection")
    tool_projection_digest = manifest.get("tool_authorization_projection_sha256")
    owned_files = manifest.get("owned_files")
    if (
        not isinstance(raw_contracts, list)
        or not isinstance(tool_projection, Mapping)
        or not isinstance(tool_projection_digest, str)
        or _sha256_canonical(dict(tool_projection)) != tool_projection_digest
        or not isinstance(owned_files, list)
    ):
        raise ProductionCanonicalAuthorityError(
            "sealed Worker authority projection is incomplete",
            reason_taxonomy="PRODUCTION_CANONICAL_WORKER_CONTEXT_INVALID",
        )

    run_binding = launch.package.run_binding
    expected = {
        "project_id": run_binding.project_id,
        "gate_id": run_binding.gate_id,
        "lv_id": run_binding.lv_id,
        "run_id": run_binding.run_id,
        "canonical_plan_sha256": run_binding.plan_digest,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ProductionCanonicalAuthorityError(
                f"Worker context {field} drift",
                reason_taxonomy="PRODUCTION_CANONICAL_WORKER_CONTEXT_DRIFT",
            )
    if run_binding.requirement_digest != run_requirement_digest:
        raise ProductionCanonicalAuthorityError(
            "canonical run Requirement digest drift",
            reason_taxonomy="PRODUCTION_CANONICAL_WORKER_REQUIREMENT_DRIFT",
        )
    if launch.gateway_authority_binding.get("worker_task_id") != tool_projection.get("worker_task_id"):
        raise ProductionCanonicalAuthorityError(
            "canonical and Tool Worker task bindings disagree",
            reason_taxonomy="PRODUCTION_CANONICAL_WORKER_TASK_DRIFT",
        )

    return {
        "active_tool_authorization_contracts": [dict(item) for item in raw_contracts],
        "owned_files": list(owned_files),
        "requirement_digest": run_requirement_digest,
        "tool_authorization_projection": dict(tool_projection),
        "tool_authorization_projection_sha256": tool_projection_digest,
        "canonical_authority_binding": dict(launch.gateway_authority_binding),
        "canonical_authority_binding_digest": launch.gateway_authority_binding_digest,
    }

@dataclass(frozen=True, slots=True)
class RecoveryParentAuthoritySource:
    parent_manifest: Mapping[str, object]
    parent_manifest_sha256: str
    recovery_package_sha256: str
    recovery_preflight_sha256: str


def validate_recovery_parent_lv_authority(
    *,
    parent_package_root: str | Path,
    recovery_package: Mapping[str, object],
    recovery_preflight: Mapping[str, object],
    project_id: str,
    gate_id: str,
    lv_id: str,
    run_id: str,
    canonical_plan_sha256: str,
) -> RecoveryParentAuthoritySource:
    """Bind recovery execution to the pre-existing sealed LV authority.

    Recovery package/preflight artifacts are execution-lineage evidence only.
    They do not become a source of Requirement, scope, permission, or Worker-task
    authority.  Those semantics must come from the original sealed LV manifest.
    """
    package_root = Path(parent_package_root).resolve()
    if not package_root.is_dir() or package_root.is_symlink():
        raise ProductionCanonicalAuthorityError(
            "recovery parent LV package root is missing or unsafe",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PARENT_ROOT_INVALID",
        )

    manifest_path = package_root / "package.manifest.json"
    sidecar_path = package_root / "package.manifest.sha256"
    for path in (manifest_path, sidecar_path):
        if not path.is_file() or path.is_symlink():
            raise ProductionCanonicalAuthorityError(
                "recovery parent sealed LV manifest is missing or unsafe",
                reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PARENT_MISSING",
            )

    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        sidecar_sha256 = sidecar_path.read_text(encoding="ascii").strip()
    except (UnicodeError, OSError) as exc:
        raise ProductionCanonicalAuthorityError(
            "recovery parent LV manifest sidecar is unreadable",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PARENT_DIGEST_DRIFT",
        ) from exc
    if sidecar_sha256 != manifest_sha256:
        raise ProductionCanonicalAuthorityError(
            "recovery parent LV manifest digest drift",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PARENT_DIGEST_DRIFT",
        )

    try:
        parent_manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionCanonicalAuthorityError(
            "recovery parent LV manifest is malformed",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PARENT_INVALID",
        ) from exc
    if not isinstance(parent_manifest, Mapping):
        raise ProductionCanonicalAuthorityError(
            "recovery parent LV manifest must be an object",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PARENT_INVALID",
        )

    # This validates exact DEC-007 ACTIVE contracts, Requirement refs,
    # Worker task identity, owned scope, run identity, and tool projection.
    derive_approved_task_from_lv_manifest(
        parent_manifest,
        project_id=project_id,
        gate_id=gate_id,
        lv_id=lv_id,
        run_id=run_id,
        canonical_plan_sha256=canonical_plan_sha256,
    )

    if not isinstance(recovery_package, Mapping) or not isinstance(recovery_preflight, Mapping):
        raise ProductionCanonicalAuthorityError(
            "recovery package/preflight must be mappings",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_LINEAGE_INVALID",
        )

    expected_identity = {
        "project_id": project_id,
        "gate_id": gate_id,
        "lv_id": lv_id,
        "run_id": run_id,
        "canonical_plan_sha256": canonical_plan_sha256,
    }
    for artifact_name, artifact in (
        ("package", recovery_package),
        ("preflight", recovery_preflight),
    ):
        for field, expected in expected_identity.items():
            if artifact.get(field) != expected:
                raise ProductionCanonicalAuthorityError(
                    f"recovery {artifact_name} {field} drift",
                    reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_IDENTITY_DRIFT",
                )

    supplied_package_sha = recovery_package.get("package_sha256")
    package_unsigned = {
        key: value
        for key, value in recovery_package.items()
        if key != "package_sha256"
    }
    if (
        not isinstance(supplied_package_sha, str)
        or _sha256_canonical(package_unsigned) != supplied_package_sha
    ):
        raise ProductionCanonicalAuthorityError(
            "recovery package digest drift",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PACKAGE_DRIFT",
        )

    supplied_preflight_sha = recovery_preflight.get("preflight_sha256")
    preflight_unsigned = {
        key: value
        for key, value in recovery_preflight.items()
        if key != "preflight_sha256"
    }
    if (
        recovery_preflight.get("status") != "READY"
        or recovery_preflight.get("package_sha256") != supplied_package_sha
        or not isinstance(supplied_preflight_sha, str)
        or _sha256_canonical(preflight_unsigned) != supplied_preflight_sha
    ):
        raise ProductionCanonicalAuthorityError(
            "recovery preflight lineage drift",
            reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_PREFLIGHT_DRIFT",
        )

    parent_projection = {
        "parent_manifest_sha256": manifest_sha256,
        "recovery_package_sha256": supplied_package_sha,
        "recovery_preflight_sha256": supplied_preflight_sha,
        "project_id": project_id,
        "gate_id": gate_id,
        "lv_id": lv_id,
        "run_id": run_id,
        "canonical_plan_sha256": canonical_plan_sha256,
    }
    # Force canonical serializability now so a malformed recovery object cannot
    # pass this boundary and fail later in WorkerRequest construction.
    _sha256_canonical(parent_projection)

    return RecoveryParentAuthoritySource(
        parent_manifest=dict(parent_manifest),
        parent_manifest_sha256=manifest_sha256,
        recovery_package_sha256=supplied_package_sha,
        recovery_preflight_sha256=supplied_preflight_sha,
    )

def production_canonical_package_identity(
    *,
    project_id: str,
    gate_id: str,
    lv_id: str,
    run_id: str,
) -> tuple[str, int]:
    identity = {
        "project_id": _require_text(project_id, field="project_id"),
        "gate_id": _require_text(gate_id, field="gate_id"),
        "lv_id": _require_text(lv_id, field="lv_id"),
        "run_id": _require_text(run_id, field="run_id"),
        "worker_task_id": DEC007_WORKER_TASK_ID,
    }
    return "PKG-" + _sha256_canonical(identity)[:32], 1


def _canonical_materialization_created_at(
    authority_root: Path,
    *,
    project_id: str,
    gate_id: str,
    lv_id: str,
    run_id: str,
    preferred_created_at_utc: str,
) -> str:
    authority_root.mkdir(parents=True, exist_ok=True)
    if authority_root.is_symlink() or not authority_root.is_dir():
        raise ProductionCanonicalAuthorityError(
            "canonical materialization root is unsafe",
            reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_ROOT_INVALID",
        )

    path = authority_root / "materialization.json"
    identity = {
        "schema_version": "orchestration.production-canonical-materialization.v1",
        "project_id": project_id,
        "gate_id": gate_id,
        "lv_id": lv_id,
        "run_id": run_id,
    }

    def load_existing() -> str:
        if path.is_symlink() or not path.is_file():
            raise ProductionCanonicalAuthorityError(
                "canonical materialization metadata is unsafe",
                reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_DRIFT",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductionCanonicalAuthorityError(
                "canonical materialization metadata is unreadable",
                reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_DRIFT",
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProductionCanonicalAuthorityError(
                "canonical materialization metadata is malformed",
                reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_DRIFT",
            )
        supplied = payload.get("materialization_digest")
        unsigned = {k: v for k, v in payload.items() if k != "materialization_digest"}
        if not isinstance(supplied, str) or _sha256_canonical(unsigned) != supplied:
            raise ProductionCanonicalAuthorityError(
                "canonical materialization metadata digest drift",
                reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_DRIFT",
            )
        for field, expected in identity.items():
            if unsigned.get(field) != expected:
                raise ProductionCanonicalAuthorityError(
                    "canonical materialization identity drift",
                    reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_DRIFT",
                )
        created = unsigned.get("quality_contract_created_at_utc")
        if not isinstance(created, str) or not created.strip():
            raise ProductionCanonicalAuthorityError(
                "canonical materialization timestamp is missing",
                reason_taxonomy="PRODUCTION_CANONICAL_MATERIALIZATION_DRIFT",
            )
        return created.strip()

    if path.exists():
        return load_existing()

    unsigned = {
        **identity,
        "quality_contract_created_at_utc": preferred_created_at_utc,
    }
    payload = {
        **unsigned,
        "materialization_digest": _sha256_canonical(unsigned),
    }
    data = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(data)
    except FileExistsError:
        return load_existing()
    return preferred_created_at_utc


def build_production_canonical_worker_authority_provider(
    *,
    codex_auth_readiness: CodexAuthReadinessEvidence | None,
    readiness_recheck_probes: ReadinessProbeSet | None,
    verify_git_provenance: bool = True,
):
    """Compose production canonical authority without collecting readiness."""
    def provider(
        *,
        mode: str,
        project_root: Path,
        harness_root: Path,
        package_root: Path,
        parent_package_root: Path,
        manifest: Mapping[str, object] | None,
        recovery_package: Mapping[str, object] | None,
        recovery_preflight: Mapping[str, object] | None,
        requirements_sha256: str,
        project_id: str,
        gate_id: str,
        lv_id: str,
        run_id: str,
        canonical_plan_sha256: str,
    ) -> Mapping[str, object]:
        if codex_auth_readiness is None:
            raise ProductionCanonicalAuthorityError(
                "pre-collected Codex readiness evidence is required",
                reason_taxonomy="PRODUCTION_CANONICAL_READINESS_REQUIRED",
            )
        if readiness_recheck_probes is None:
            raise ProductionCanonicalAuthorityError(
                "explicit launch-adjacent readiness recheck probes are required",
                reason_taxonomy="PRODUCTION_CANONICAL_RECHECK_REQUIRED",
            )
        if mode not in {"normal", "recovery"}:
            raise ProductionCanonicalAuthorityError(
                "unsupported production canonical Worker mode",
                reason_taxonomy="PRODUCTION_CANONICAL_MODE_INVALID",
            )

        if mode == "normal":
            if not isinstance(manifest, Mapping):
                raise ProductionCanonicalAuthorityError(
                    "normal Worker requires sealed LV manifest",
                    reason_taxonomy="PRODUCTION_CANONICAL_LV_MANIFEST_INVALID",
                )
            authority_manifest = dict(manifest)
            remediation_attempt_event_id = ""
        else:
            if not isinstance(recovery_package, Mapping) or not isinstance(recovery_preflight, Mapping):
                raise ProductionCanonicalAuthorityError(
                    "recovery Worker requires exact recovery lineage",
                    reason_taxonomy="PRODUCTION_CANONICAL_RECOVERY_LINEAGE_INVALID",
                )
            recovery_source = validate_recovery_parent_lv_authority(
                parent_package_root=parent_package_root,
                recovery_package=recovery_package,
                recovery_preflight=recovery_preflight,
                project_id=project_id,
                gate_id=gate_id,
                lv_id=lv_id,
                run_id=run_id,
                canonical_plan_sha256=canonical_plan_sha256,
            )
            authority_manifest = dict(recovery_source.parent_manifest)
            raw_recovery_id = recovery_package.get("recovery_id", "")
            remediation_attempt_event_id = (
                raw_recovery_id.strip() if isinstance(raw_recovery_id, str) else ""
            )

        task = derive_approved_task_from_lv_manifest(
            authority_manifest,
            project_id=project_id,
            gate_id=gate_id,
            lv_id=lv_id,
            run_id=run_id,
            canonical_plan_sha256=canonical_plan_sha256,
        )
        package_id, package_revision = production_canonical_package_identity(
            project_id=project_id,
            gate_id=gate_id,
            lv_id=lv_id,
            run_id=run_id,
        )

        authority_root = (
            Path(harness_root).resolve()
            / "_workspace"
            / "orchestration-runs"
            / run_id
            / "canonical-authority"
            / lv_id
        )
        created_at = _canonical_materialization_created_at(
            authority_root,
            project_id=project_id,
            gate_id=gate_id,
            lv_id=lv_id,
            run_id=run_id,
            preferred_created_at_utc=codex_auth_readiness.verified_at_utc,
        )

        authority = materialize_production_canonical_contract_authority(
            project_root=project_root,
            harness_root=harness_root,
            completion_authority_root=authority_root,
            task=task,
            project_id=project_id,
            gate_id=gate_id,
            lv_id=lv_id,
            run_id=run_id,
            worker_task_id=DEC007_WORKER_TASK_ID,
            plan_version="FINAL-DP-2.0+R4.1-MIGRATION",
            canonical_plan_sha256=canonical_plan_sha256,
            requirement_version="FINAL-REQUIREMENT-BASELINE-1.0+RUN",
            requirements_sha256=requirements_sha256,
            semantic_version="FINAL-SC-1.0+R4-FROZEN",
            canonical_contract_id="CEC-TASK-4A-08",
            canonical_contract_version="1",
            quality_contract_id="MQC-TASK-4A-08",
            quality_contract_version="1",
            quality_contract_created_at_utc=created_at,
            verify_git_provenance=verify_git_provenance,
        )
        completion = evaluate_pre_execution_completion(authority, project_root)

        projection = authority_manifest.get("tool_authorization_projection")
        if not isinstance(projection, Mapping):
            raise ProductionCanonicalAuthorityError(
                "sealed Tool authorization projection is missing",
                reason_taxonomy="PRODUCTION_CANONICAL_TOOL_AUTHORITY_MISSING",
            )
        operation_ids = projection.get("operation_class_ids")
        if (
            not isinstance(operation_ids, list)
            or tuple(sorted(operation_ids)) != tuple(sorted(task.allowed_capabilities))
        ):
            raise ProductionCanonicalAuthorityError(
                "sealed Tool capability projection drift",
                reason_taxonomy="PRODUCTION_CANONICAL_TOOL_SET_DRIFT",
            )

        migration = authority.migration_authority
        migration_ref = (
            f"migration-authority://{migration.manifest_path}"
            f"#{migration.manifest_digest}"
        )
        pre_ref = (
            f"completion://{DEC007_WORKER_TASK_ID}/pre"
            f"#{completion.assessment.criterion_set_digest}"
        )
        launch = build_production_canonical_launch_authority(
            authority=authority,
            pre_execution_assessment_ref=pre_ref,
            pre_execution_assessment=completion.assessment,
            package_id=package_id,
            package_revision=package_revision,
            previous_package_digest="",
            runtime_selection={"backend": "HOST_GATEWAY"},
            exact_tool_authorization_projection=tuple(sorted(operation_ids)),
            security_policy_refs=("security://broker-only",),
            codex_auth_readiness=codex_auth_readiness,
            migration_authority_ref=migration_ref,
            readiness_recheck_probes=readiness_recheck_probes,
            remediation_attempt_event_id=remediation_attempt_event_id,
        )
        return build_worker_authority_extra_context(
            manifest=authority_manifest,
            launch=launch,
            requirements_sha256=requirements_sha256,
        )

    return provider
