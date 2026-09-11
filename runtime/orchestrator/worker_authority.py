from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from .completion_contract import CompletionAssessment, CompletionState, ExecutionObligation
from .execution_contract import (
    ActivationProfile,
    CanonicalExecutionContract,
    ContractStatus,
    ExecutionPackage,
    PreflightResult,
)


BLOCKED_POST_QUALITY = "BLOCKED_POST_QUALITY"
BLOCKED_REMEDIATION_EXHAUSTED = "BLOCKED_REMEDIATION_EXHAUSTED"
INVALID_WORKER_COMPLETION = "INVALID_WORKER_COMPLETION"
REMEDIATION_ATTEMPT_STARTED = "REMEDIATION_ATTEMPT_STARTED"
REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED = "REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED"
REMEDIATION_ATTEMPT_REVIEWED = "REMEDIATION_ATTEMPT_REVIEWED"


class WorkerAuthorityError(ValueError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


class WorkerTerminalState(str, Enum):
    CHANGED = "CHANGED"
    COMPLETED = "COMPLETED"
    SKIPPED_SATISFIED = "SKIPPED_SATISFIED"
    BLOCKED = "BLOCKED"
    INVALID_COMPLETION = "INVALID_COMPLETION"


class WorkerGateState(str, Enum):
    ELIGIBLE_POST_QUALITY = "ELIGIBLE_POST_QUALITY"
    BLOCKED = "BLOCKED"
    INVALID_COMPLETION = "INVALID_COMPLETION"


class QualityState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RemediationMode(str, Enum):
    DISABLED = "DISABLED"
    BOUNDED = "BOUNDED"


class RemediationRoute(str, Enum):
    BLOCKED = "BLOCKED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sorted_unique(values: Sequence[str], *, field_name: str, allow_empty: bool = True) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise WorkerAuthorityError(
                f"{field_name} must contain non-empty strings",
                reason_taxonomy="WORKER_AUTHORITY_INPUT_INVALID",
            )
        normalized.append(value.strip())
    result = tuple(sorted(set(normalized)))
    if not allow_empty and not result:
        raise WorkerAuthorityError(
            f"{field_name} is required",
            reason_taxonomy="WORKER_AUTHORITY_INPUT_INVALID",
        )
    return result


def execution_package_ref(package: ExecutionPackage) -> str:
    return f"package://{package.package_id}@{package.package_revision}#{package.package_digest}"


def _validate_package_integrity(package: ExecutionPackage) -> None:
    if package.package_digest != _digest(package.canonical_projection()):
        raise WorkerAuthorityError(
            "Execution Package digest does not match its sealed projection",
            reason_taxonomy="WORKER_PACKAGE_TAMPER_OR_DRIFT",
        )
    if not package.contract_activation_digest.strip():
        raise WorkerAuthorityError(
            "Execution Package is not bound to an ACTIVE Contract activation",
            reason_taxonomy="WORKER_ACTIVE_CONTRACT_BINDING_MISSING",
        )


@dataclass(frozen=True, slots=True)
class WorkerLaunchAuthorization:
    package_ref: str
    package_digest: str
    contract_ref: str
    contract_digest: str
    task_ref: str
    execution_obligation: ExecutionObligation
    owned_scope: tuple[str, ...]
    exact_tool_authorization: tuple[str, ...]
    preflight_evidence_digest: str
    remediation_attempt_event_id: str = ""
    authorization_digest: str = ""

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "package_ref": self.package_ref,
            "package_digest": self.package_digest,
            "contract_ref": self.contract_ref,
            "contract_digest": self.contract_digest,
            "task_ref": self.task_ref,
            "execution_obligation": self.execution_obligation.value,
            "owned_scope": list(self.owned_scope),
            "exact_tool_authorization": list(self.exact_tool_authorization),
            "preflight_evidence_digest": self.preflight_evidence_digest,
            "remediation_attempt_event_id": self.remediation_attempt_event_id,
        }


def authorize_worker_launch(
    package: ExecutionPackage,
    preflight: PreflightResult,
    *,
    remediation_attempt_event_id: str = "",
) -> WorkerLaunchAuthorization:
    _validate_package_integrity(package)
    if (
        not preflight.ready
        or preflight.reason_taxonomy != "PASS"
        or not isinstance(preflight.evidence_digest, str)
        or not preflight.evidence_digest.strip()
    ):
        raise WorkerAuthorityError(
            "Worker launch requires sealed PASS preflight evidence",
            reason_taxonomy="WORKER_PREFLIGHT_NOT_READY",
        )
    if package.execution_obligation is ExecutionObligation.BLOCKED:
        raise WorkerAuthorityError(
            "BLOCKED execution obligation cannot launch Worker",
            reason_taxonomy="BLOCKED_COMPLETION_CONTRACT",
        )
    if not package.run_binding.worker_task_id.strip():
        raise WorkerAuthorityError(
            "package worker_task_id is required",
            reason_taxonomy="WORKER_TASK_BINDING_MISSING",
        )
    base = {
        "package_ref": execution_package_ref(package),
        "package_digest": package.package_digest,
        "contract_ref": package.contract_ref,
        "contract_digest": package.contract_digest,
        "task_ref": package.run_binding.worker_task_id,
        "execution_obligation": package.execution_obligation.value,
        "owned_scope": list(package.owned_scope_projection),
        "exact_tool_authorization": list(package.exact_tool_authorization_projection),
        "preflight_evidence_digest": preflight.evidence_digest,
        "remediation_attempt_event_id": remediation_attempt_event_id.strip(),
    }
    return WorkerLaunchAuthorization(
        package_ref=base["package_ref"],
        package_digest=package.package_digest,
        contract_ref=package.contract_ref,
        contract_digest=package.contract_digest,
        task_ref=package.run_binding.worker_task_id,
        execution_obligation=package.execution_obligation,
        owned_scope=package.owned_scope_projection,
        exact_tool_authorization=package.exact_tool_authorization_projection,
        preflight_evidence_digest=preflight.evidence_digest,
        remediation_attempt_event_id=base["remediation_attempt_event_id"],
        authorization_digest=_digest(base),
    )


@dataclass(frozen=True, slots=True)
class GovernedEffectEvidence:
    effect_id: str
    operation: str
    scope_ref: str
    intent_digest: str
    receipt_intent_digest: str
    receipt_digest: str
    authorized: bool
    mutation_performed: bool
    security_passed: bool
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "effect_id",
            "operation",
            "scope_ref",
            "intent_digest",
            "receipt_intent_digest",
            "receipt_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise WorkerAuthorityError(
                    f"{name} is required",
                    reason_taxonomy="EFFECT_EVIDENCE_INVALID",
                )
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "evidence_refs",
            _sorted_unique(self.evidence_refs, field_name="effect_evidence_refs", allow_empty=False),
        )

    @property
    def intent_receipt_consistent(self) -> bool:
        return self.intent_digest == self.receipt_intent_digest

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "operation": self.operation,
            "scope_ref": self.scope_ref,
            "intent_digest": self.intent_digest,
            "receipt_intent_digest": self.receipt_intent_digest,
            "receipt_digest": self.receipt_digest,
            "authorized": self.authorized,
            "mutation_performed": self.mutation_performed,
            "security_passed": self.security_passed,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class WorkerResultEnvelope:
    worker_id: str
    task_ref: str
    package_ref: str
    package_digest: str
    contract_ref: str
    contract_digest: str
    terminal_state: str
    reason_taxonomy: str = ""
    effect_evidence: tuple[GovernedEffectEvidence, ...] = ()
    output_artifact_refs: tuple[str, ...] = ()
    output_provenance_refs: tuple[str, ...] = ()
    security_evidence_refs: tuple[str, ...] = ()
    worker_claimed_obligation: str = ""

    def __post_init__(self) -> None:
        for name in (
            "worker_id",
            "task_ref",
            "package_ref",
            "package_digest",
            "contract_ref",
            "contract_digest",
            "terminal_state",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise WorkerAuthorityError(
                    f"{name} is required",
                    reason_taxonomy="WORKER_RESULT_INVALID",
                )
            object.__setattr__(self, name, value.strip())
        object.__setattr__(self, "reason_taxonomy", self.reason_taxonomy.strip())
        object.__setattr__(
            self,
            "output_artifact_refs",
            _sorted_unique(self.output_artifact_refs, field_name="output_artifact_refs"),
        )
        object.__setattr__(
            self,
            "output_provenance_refs",
            _sorted_unique(self.output_provenance_refs, field_name="output_provenance_refs"),
        )
        object.__setattr__(
            self,
            "security_evidence_refs",
            _sorted_unique(self.security_evidence_refs, field_name="security_evidence_refs"),
        )
        object.__setattr__(self, "worker_claimed_obligation", self.worker_claimed_obligation.strip())

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "task_ref": self.task_ref,
            "package_ref": self.package_ref,
            "package_digest": self.package_digest,
            "contract_ref": self.contract_ref,
            "contract_digest": self.contract_digest,
            "terminal_state": self.terminal_state,
            "reason_taxonomy": self.reason_taxonomy,
            "effect_evidence": [item.canonical_projection() for item in self.effect_evidence],
            "output_artifact_refs": list(self.output_artifact_refs),
            "output_provenance_refs": list(self.output_provenance_refs),
            "security_evidence_refs": list(self.security_evidence_refs),
            "worker_claimed_obligation": self.worker_claimed_obligation,
        }

    @property
    def result_digest(self) -> str:
        return _digest(self.canonical_projection())


@dataclass(frozen=True, slots=True)
class WorkerGateResult:
    state: WorkerGateState
    reason_taxonomy: str
    worker_result_digest: str
    authoritative_execution_obligation: ExecutionObligation

    @property
    def eligible_for_post_quality(self) -> bool:
        return self.state is WorkerGateState.ELIGIBLE_POST_QUALITY


_BOUNDED_BLOCK_REASONS = {
    "TECHNICAL_IMPOSSIBLE",
    "CAPABILITY_UNAVAILABLE",
    "AUTHORIZED_SCOPE_INSUFFICIENT",
    "TOOL_UNAVAILABLE",
    "SECURITY_BLOCK",
    "DEPENDENCY_BLOCKED",
}
_MUTATION_OPERATIONS = {"WRITE", "PROJECT_OWNED_FILE_WRITE"}


def _validate_result_binding(
    package: ExecutionPackage,
    launch: WorkerLaunchAuthorization,
    result: WorkerResultEnvelope,
) -> None:
    _validate_package_integrity(package)
    expected_package_ref = execution_package_ref(package)
    if launch.authorization_digest != _digest(launch.canonical_projection()):
        raise WorkerAuthorityError(
            "Worker launch authorization digest is invalid",
            reason_taxonomy="WORKER_LAUNCH_AUTHORIZATION_TAMPER",
        )
    if (
        launch.package_ref != expected_package_ref
        or launch.package_digest != package.package_digest
        or launch.contract_ref != package.contract_ref
        or launch.contract_digest != package.contract_digest
        or launch.task_ref != package.run_binding.worker_task_id
        or launch.execution_obligation is not package.execution_obligation
        or launch.owned_scope != package.owned_scope_projection
        or launch.exact_tool_authorization != package.exact_tool_authorization_projection
        or not launch.preflight_evidence_digest.strip()
    ):
        raise WorkerAuthorityError(
            "Worker launch authorization drifted from sealed Execution Package",
            reason_taxonomy="WORKER_LAUNCH_BINDING_DRIFT",
        )
    if (
        result.package_ref != expected_package_ref
        or result.package_digest != package.package_digest
        or result.contract_ref != package.contract_ref
        or result.contract_digest != package.contract_digest
        or result.task_ref != package.run_binding.worker_task_id
    ):
        raise WorkerAuthorityError(
            "Worker result is not bound to the ACTIVE Execution Package",
            reason_taxonomy="WORKER_RESULT_BINDING_DRIFT",
        )


def _is_exact_authorized_mutation(
    evidence: GovernedEffectEvidence,
    package: ExecutionPackage,
) -> bool:
    return (
        evidence.operation in _MUTATION_OPERATIONS
        and evidence.operation in package.exact_tool_authorization_projection
        and evidence.scope_ref in package.owned_scope_projection
        and evidence.authorized
        and evidence.mutation_performed
        and evidence.security_passed
        and evidence.intent_receipt_consistent
    )


def _effect_evidence_within_package(
    evidence: GovernedEffectEvidence,
    package: ExecutionPackage,
) -> bool:
    return (
        evidence.operation in package.exact_tool_authorization_projection
        and evidence.scope_ref in package.owned_scope_projection
        and evidence.authorized
        and evidence.security_passed
        and evidence.intent_receipt_consistent
    )


def evaluate_worker_result(
    package: ExecutionPackage,
    launch: WorkerLaunchAuthorization,
    result: WorkerResultEnvelope,
    *,
    post_completion_assessment: CompletionAssessment | None,
) -> WorkerGateResult:
    _validate_result_binding(package, launch, result)
    obligation = package.execution_obligation
    terminal = result.terminal_state

    if terminal not in package.allowed_worker_terminal_states:
        return WorkerGateResult(
            WorkerGateState.INVALID_COMPLETION,
            "WORKER_TERMINAL_STATE_NOT_AUTHORIZED",
            result.result_digest,
            obligation,
        )

    invalid_effects = [
        evidence
        for evidence in result.effect_evidence
        if not _effect_evidence_within_package(evidence, package)
    ]
    if invalid_effects:
        return WorkerGateResult(
            WorkerGateState.INVALID_COMPLETION,
            "EFFECT_OUTSIDE_PACKAGE_AUTHORITY",
            result.result_digest,
            obligation,
        )

    if terminal == WorkerTerminalState.BLOCKED.value:
        if result.reason_taxonomy not in _BOUNDED_BLOCK_REASONS:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "WORKER_BLOCK_REASON_UNBOUNDED",
                result.result_digest,
                obligation,
            )
        if any(evidence.mutation_performed for evidence in result.effect_evidence):
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "BLOCKED_WORKER_CANNOT_REPORT_COMMITTED_MUTATION",
                result.result_digest,
                obligation,
            )
        return WorkerGateResult(
            WorkerGateState.BLOCKED,
            result.reason_taxonomy,
            result.result_digest,
            obligation,
        )

    if obligation is ExecutionObligation.MUTATION_REQUIRED:
        if terminal != WorkerTerminalState.CHANGED.value:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                INVALID_WORKER_COMPLETION,
                result.result_digest,
                obligation,
            )
        exact_mutations = [
            evidence
            for evidence in result.effect_evidence
            if _is_exact_authorized_mutation(evidence, package)
        ]
        if not exact_mutations:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "REQUIRED_GOVERNED_MUTATION_EVIDENCE_MISSING",
                result.result_digest,
                obligation,
            )
        if post_completion_assessment is None:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "POST_COMPLETION_ASSESSMENT_MISSING",
                result.result_digest,
                obligation,
            )
        if post_completion_assessment.criterion_set_digest != package.criterion_set_digest:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "COMPLETION_CRITERIA_LINEAGE_DRIFT",
                result.result_digest,
                obligation,
            )
        if post_completion_assessment.overall_state is not CompletionState.SATISFIED:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "POST_COMPLETION_NOT_SATISFIED",
                result.result_digest,
                obligation,
            )
        if not result.output_artifact_refs or not result.output_provenance_refs:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "WORKER_OUTPUT_PROVENANCE_MISSING",
                result.result_digest,
                obligation,
            )
        if package.security_requirements and not result.security_evidence_refs:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "WORKER_SECURITY_PROVENANCE_MISSING",
                result.result_digest,
                obligation,
            )
        return WorkerGateResult(
            WorkerGateState.ELIGIBLE_POST_QUALITY,
            "PASS",
            result.result_digest,
            obligation,
        )

    if obligation is ExecutionObligation.READ_ONLY_EXECUTION:
        if terminal != WorkerTerminalState.COMPLETED.value:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                INVALID_WORKER_COMPLETION,
                result.result_digest,
                obligation,
            )
        if post_completion_assessment is None:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "POST_COMPLETION_ASSESSMENT_MISSING",
                result.result_digest,
                obligation,
            )
        if post_completion_assessment.criterion_set_digest != package.criterion_set_digest:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "COMPLETION_CRITERIA_LINEAGE_DRIFT",
                result.result_digest,
                obligation,
            )
        if any(evidence.mutation_performed for evidence in result.effect_evidence):
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "READ_ONLY_WORKER_REPORTED_MUTATION",
                result.result_digest,
                obligation,
            )
        if not result.output_artifact_refs or not result.output_provenance_refs:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "WORKER_OUTPUT_PROVENANCE_MISSING",
                result.result_digest,
                obligation,
            )
        if package.security_requirements and not result.security_evidence_refs:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                "WORKER_SECURITY_PROVENANCE_MISSING",
                result.result_digest,
                obligation,
            )
        return WorkerGateResult(
            WorkerGateState.ELIGIBLE_POST_QUALITY,
            "PASS",
            result.result_digest,
            obligation,
        )

    if obligation is ExecutionObligation.NONE_SATISFIED:
        if terminal != WorkerTerminalState.SKIPPED_SATISFIED.value:
            return WorkerGateResult(
                WorkerGateState.INVALID_COMPLETION,
                INVALID_WORKER_COMPLETION,
                result.result_digest,
                obligation,
            )
        return WorkerGateResult(
            WorkerGateState.ELIGIBLE_POST_QUALITY,
            "PASS",
            result.result_digest,
            obligation,
        )

    raise WorkerAuthorityError(
        "BLOCKED execution obligation cannot be evaluated as Worker success",
        reason_taxonomy="BLOCKED_COMPLETION_CONTRACT",
    )


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    reviewer_id: str
    worker_result_digest: str
    contract_digest: str
    package_digest: str
    completion_criterion_set_digest: str
    validation_criteria: tuple[str, ...]
    quality_criteria_contract_ref: str
    objective_tests_passed: bool
    security_passed: bool
    quality_passed: bool
    review_evidence_refs: tuple[str, ...] = ()
    security_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "reviewer_id",
            "worker_result_digest",
            "contract_digest",
            "package_digest",
            "completion_criterion_set_digest",
            "quality_criteria_contract_ref",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise WorkerAuthorityError(
                    f"{name} is required",
                    reason_taxonomy="QUALITY_ASSESSMENT_INVALID",
                )
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "validation_criteria",
            _sorted_unique(self.validation_criteria, field_name="validation_criteria", allow_empty=False),
        )
        object.__setattr__(
            self,
            "review_evidence_refs",
            _sorted_unique(self.review_evidence_refs, field_name="review_evidence_refs", allow_empty=False),
        )
        object.__setattr__(
            self,
            "security_evidence_refs",
            _sorted_unique(self.security_evidence_refs, field_name="quality_security_evidence_refs"),
        )

    @property
    def assessment_digest(self) -> str:
        return _digest(
            {
                "reviewer_id": self.reviewer_id,
                "worker_result_digest": self.worker_result_digest,
                "contract_digest": self.contract_digest,
                "package_digest": self.package_digest,
                "completion_criterion_set_digest": self.completion_criterion_set_digest,
                "validation_criteria": list(self.validation_criteria),
                "quality_criteria_contract_ref": self.quality_criteria_contract_ref,
                "objective_tests_passed": self.objective_tests_passed,
                "security_passed": self.security_passed,
                "quality_passed": self.quality_passed,
                "review_evidence_refs": list(self.review_evidence_refs),
                "security_evidence_refs": list(self.security_evidence_refs),
            }
        )


@dataclass(frozen=True, slots=True)
class PostQualityResult:
    state: QualityState
    reason_taxonomy: str
    worker_result_digest: str
    quality_assessment_digest: str

    @property
    def passed(self) -> bool:
        return self.state is QualityState.PASS


def review_post_quality(
    package: ExecutionPackage,
    active_contract: CanonicalExecutionContract,
    worker_result: WorkerResultEnvelope,
    worker_gate: WorkerGateResult,
    quality: QualityAssessment,
) -> PostQualityResult:
    def fail(reason: str) -> PostQualityResult:
        return PostQualityResult(
            QualityState.FAIL,
            reason,
            worker_result.result_digest,
            quality.assessment_digest,
        )

    if not worker_gate.eligible_for_post_quality:
        return fail("WORKER_NOT_ELIGIBLE_FOR_POST_QUALITY")
    try:
        _validate_package_integrity(package)
    except WorkerAuthorityError:
        return fail("PACKAGE_TAMPER_OR_DRIFT")
    if (
        active_contract.status is not ContractStatus.ACTIVE
        or not active_contract.activation_digest.strip()
        or active_contract.contract_digest != package.contract_digest
        or active_contract.activation_digest != package.contract_activation_digest
    ):
        return fail("ACTIVE_CONTRACT_BINDING_DRIFT")
    if quality.reviewer_id == worker_result.worker_id:
        return fail("QUALITY_REVIEWER_NOT_INDEPENDENT")
    if quality.worker_result_digest != worker_result.result_digest:
        return fail("SEALED_WORKER_RESULT_DRIFT")
    if (
        worker_gate.worker_result_digest != worker_result.result_digest
        or worker_gate.authoritative_execution_obligation is not package.execution_obligation
    ):
        return fail("WORKER_GATE_RESULT_BINDING_DRIFT")
    if quality.contract_digest != active_contract.contract_digest or quality.package_digest != package.package_digest:
        return fail("QUALITY_CONTRACT_PACKAGE_BINDING_DRIFT")
    if quality.completion_criterion_set_digest != package.criterion_set_digest:
        return fail("PRE_POST_COMPLETION_LINEAGE_DRIFT")
    if package.validation_criteria != active_contract.validation_criteria:
        return fail("PACKAGE_VALIDATION_LINEAGE_DRIFT")
    if quality.validation_criteria != tuple(sorted(package.validation_criteria)):
        return fail("PRE_POST_VALIDATION_LINEAGE_DRIFT")
    if package.quality_criteria_contract_ref != active_contract.quality_criteria_contract_ref:
        return fail("PACKAGE_QUALITY_LINEAGE_DRIFT")
    if quality.quality_criteria_contract_ref != package.quality_criteria_contract_ref:
        return fail("PRE_POST_QUALITY_LINEAGE_DRIFT")
    if package.quality_criteria_contract_ref not in package.quality_policy_refs:
        return fail("QUALITY_PACKAGE_LINEAGE_MISSING")
    if package.security_requirements:
        if not worker_result.security_evidence_refs or not quality.security_evidence_refs:
            return fail("SECURITY_PROVENANCE_INCOMPLETE")
        if set(quality.security_evidence_refs).issubset(set(worker_result.security_evidence_refs)):
            return fail("SECURITY_REVIEW_NOT_COMPLEMENTARY")
    if not quality.objective_tests_passed:
        return fail("OBJECTIVE_TESTS_FAILED")
    if not quality.security_passed:
        return fail("POST_QUALITY_SECURITY_FAILED")
    if not quality.quality_passed:
        return fail(BLOCKED_POST_QUALITY)
    return PostQualityResult(
        QualityState.PASS,
        "PASS",
        worker_result.result_digest,
        quality.assessment_digest,
    )


@dataclass(frozen=True, slots=True)
class RemediationPolicy:
    policy_ref: str
    mode: RemediationMode
    max_attempts: int = 0
    allowed_fix_scope: tuple[str, ...] = ()
    exhaustion_state: str = BLOCKED_REMEDIATION_EXHAUSTED

    def __post_init__(self) -> None:
        if not isinstance(self.policy_ref, str) or not self.policy_ref.strip():
            raise WorkerAuthorityError(
                "remediation policy_ref is required",
                reason_taxonomy="REMEDIATION_POLICY_INVALID",
            )
        object.__setattr__(self, "policy_ref", self.policy_ref.strip())
        scope = _sorted_unique(self.allowed_fix_scope, field_name="allowed_fix_scope")
        object.__setattr__(self, "allowed_fix_scope", scope)
        if self.mode is RemediationMode.BOUNDED:
            if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
                raise WorkerAuthorityError(
                    "BOUNDED remediation requires max_attempts > 0",
                    reason_taxonomy="REMEDIATION_MAX_ATTEMPTS_INVALID",
                )
            if not scope:
                raise WorkerAuthorityError(
                    "BOUNDED remediation requires explicit allowed_fix_scope",
                    reason_taxonomy="REMEDIATION_FIX_SCOPE_MISSING",
                )
        elif self.max_attempts not in (0,):
            raise WorkerAuthorityError(
                "DISABLED remediation cannot reserve attempts",
                reason_taxonomy="REMEDIATION_POLICY_INVALID",
            )
        if self.exhaustion_state != BLOCKED_REMEDIATION_EXHAUSTED:
            raise WorkerAuthorityError(
                "unsupported remediation exhaustion state",
                reason_taxonomy="REMEDIATION_POLICY_INVALID",
            )

    @property
    def policy_digest(self) -> str:
        return _digest(
            {
                "policy_ref": self.policy_ref,
                "mode": self.mode.value,
                "max_attempts": self.max_attempts,
                "allowed_fix_scope": list(self.allowed_fix_scope),
                "exhaustion_state": self.exhaustion_state,
            }
        )


def _validate_remediation_binding(
    policy: RemediationPolicy,
    package: ExecutionPackage,
    active_contract: CanonicalExecutionContract,
) -> None:
    _validate_package_integrity(package)
    if (
        active_contract.status is not ContractStatus.ACTIVE
        or not active_contract.activation_digest.strip()
        or active_contract.contract_digest != package.contract_digest
        or active_contract.activation_digest != package.contract_activation_digest
        or package.remediation_policy_ref != active_contract.remediation_policy_ref
        or policy.policy_ref != active_contract.remediation_policy_ref
    ):
        raise WorkerAuthorityError(
            "RemediationPolicy is not exact-bound to the ACTIVE Contract/Package",
            reason_taxonomy="REMEDIATION_POLICY_BINDING_DRIFT",
        )
    if not set(policy.allowed_fix_scope).issubset(set(package.owned_scope_projection)):
        raise WorkerAuthorityError(
            "RemediationPolicy allowed_fix_scope exceeds Package owned scope",
            reason_taxonomy="REMEDIATION_FIX_SCOPE_EXCEEDED",
        )
    if package.activation_profile is ActivationProfile.MIGRATION_APPROVED_PLAN and policy.mode is RemediationMode.BOUNDED:
        raise WorkerAuthorityError(
            "MIGRATION_APPROVED_PLAN requires remediation DISABLED",
            reason_taxonomy="REMEDIATION_POLICY_PROFILE_VIOLATION",
        )


@dataclass(frozen=True, slots=True)
class RemediationAttemptStartedEvent:
    attempt_event_id: str
    attempt_index: int
    task_ref: str
    contract_ref: str
    package_ref: str
    failure_owner: str
    policy_ref: str
    event_digest: str
    record_type: str = REMEDIATION_ATTEMPT_STARTED

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "attempt_event_id": self.attempt_event_id,
            "attempt_index": self.attempt_index,
            "task_ref": self.task_ref,
            "contract_ref": self.contract_ref,
            "package_ref": self.package_ref,
            "failure_owner": self.failure_owner,
            "policy_ref": self.policy_ref,
        }


@dataclass(frozen=True, slots=True)
class RemediationAttemptLaunchEvent:
    attempt_event_id: str
    attempt_index: int
    task_ref: str
    contract_ref: str
    package_ref: str
    policy_ref: str
    requested_fix_scope: tuple[str, ...]
    launch_binding_digest: str
    record_digest: str
    record_type: str = REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "attempt_event_id": self.attempt_event_id,
            "attempt_index": self.attempt_index,
            "task_ref": self.task_ref,
            "contract_ref": self.contract_ref,
            "package_ref": self.package_ref,
            "policy_ref": self.policy_ref,
            "requested_fix_scope": list(self.requested_fix_scope),
            "launch_binding_digest": self.launch_binding_digest,
        }


@dataclass(frozen=True, slots=True)
class RemediationAttemptReviewEvent:
    attempt_event_id: str
    quality_passed: bool
    quality_assessment_digest: str
    record_digest: str
    record_type: str = REMEDIATION_ATTEMPT_REVIEWED

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "attempt_event_id": self.attempt_event_id,
            "quality_passed": self.quality_passed,
            "quality_assessment_digest": self.quality_assessment_digest,
        }


def route_quality_failure(
    policy: RemediationPolicy,
    *,
    package: ExecutionPackage,
    active_contract: CanonicalExecutionContract,
) -> RemediationRoute:
    _validate_remediation_binding(policy, package, active_contract)
    if policy.mode is RemediationMode.DISABLED:
        return RemediationRoute.BLOCKED
    return RemediationRoute.REMEDIATION_REQUIRED


class RemediationLedger:
    """Append-only durable remediation-attempt ledger.

    `reserve_attempt()` atomically reads the current lineage, allocates the next
    monotonic attempt index, appends REMEDIATION_ATTEMPT_STARTED and fsyncs it.
    `authorize_remediation_launch()` then atomically records a one-shot launch
    authorization before the caller may start the remediation Worker. A crash
    after that authorization never permits a blind second launch of the same
    consumed attempt.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _locked_file(self):
        handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    @staticmethod
    def _read_records(handle) -> list[dict[str, Any]]:
        handle.seek(0)
        records: list[dict[str, Any]] = []
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WorkerAuthorityError(
                    "remediation ledger contains incomplete/corrupt record",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                ) from exc
            if not isinstance(payload, dict):
                raise WorkerAuthorityError(
                    "remediation ledger record must be object",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                )
            records.append(payload)
        return records

    @staticmethod
    def _event_from_record(record: dict[str, Any]) -> RemediationAttemptStartedEvent:
        try:
            projection = {
                "record_type": REMEDIATION_ATTEMPT_STARTED,
                "attempt_event_id": str(record["attempt_event_id"]),
                "attempt_index": int(record["attempt_index"]),
                "task_ref": str(record["task_ref"]),
                "contract_ref": str(record["contract_ref"]),
                "package_ref": str(record["package_ref"]),
                "failure_owner": str(record["failure_owner"]),
                "policy_ref": str(record["policy_ref"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerAuthorityError(
                "remediation attempt record is incomplete",
                reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
            ) from exc
        if projection["attempt_index"] <= 0:
            raise WorkerAuthorityError(
                "remediation attempt index must be positive",
                reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
            )
        expected_digest = _digest(projection)
        if str(record.get("event_digest", "")) != expected_digest:
            raise WorkerAuthorityError(
                "remediation attempt event digest mismatch",
                reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
            )
        return RemediationAttemptStartedEvent(
            attempt_event_id=projection["attempt_event_id"],
            attempt_index=projection["attempt_index"],
            task_ref=projection["task_ref"],
            contract_ref=projection["contract_ref"],
            package_ref=projection["package_ref"],
            failure_owner=projection["failure_owner"],
            policy_ref=projection["policy_ref"],
            event_digest=expected_digest,
        )

    @classmethod
    def _started_records(cls, records: Sequence[dict[str, Any]]) -> list[RemediationAttemptStartedEvent]:
        events = [
            cls._event_from_record(record)
            for record in records
            if record.get("record_type") == REMEDIATION_ATTEMPT_STARTED
        ]
        ids = [event.attempt_event_id for event in events]
        if len(ids) != len(set(ids)):
            raise WorkerAuthorityError(
                "duplicate remediation attempt_event_id",
                reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
            )
        return events

    @staticmethod
    def _review_records(records: Sequence[dict[str, Any]]) -> dict[str, RemediationAttemptReviewEvent]:
        reviews: dict[str, RemediationAttemptReviewEvent] = {}
        for record in records:
            if record.get("record_type") != REMEDIATION_ATTEMPT_REVIEWED:
                continue
            try:
                projection = {
                    "record_type": REMEDIATION_ATTEMPT_REVIEWED,
                    "attempt_event_id": str(record["attempt_event_id"]),
                    "quality_passed": bool(record["quality_passed"]),
                    "quality_assessment_digest": str(record["quality_assessment_digest"]),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkerAuthorityError(
                    "remediation review record is incomplete",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                ) from exc
            expected_digest = _digest(projection)
            if str(record.get("record_digest", "")) != expected_digest:
                raise WorkerAuthorityError(
                    "remediation review record digest mismatch",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                )
            event_id = projection["attempt_event_id"]
            if event_id in reviews:
                raise WorkerAuthorityError(
                    "duplicate remediation attempt review",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                )
            reviews[event_id] = RemediationAttemptReviewEvent(
                attempt_event_id=event_id,
                quality_passed=projection["quality_passed"],
                quality_assessment_digest=projection["quality_assessment_digest"],
                record_digest=expected_digest,
            )
        return reviews

    @staticmethod
    def _launch_records(records: Sequence[dict[str, Any]]) -> dict[str, RemediationAttemptLaunchEvent]:
        launches: dict[str, RemediationAttemptLaunchEvent] = {}
        for record in records:
            if record.get("record_type") != REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED:
                continue
            try:
                requested = tuple(str(item) for item in record["requested_fix_scope"])
                projection = {
                    "record_type": REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED,
                    "attempt_event_id": str(record["attempt_event_id"]),
                    "attempt_index": int(record["attempt_index"]),
                    "task_ref": str(record["task_ref"]),
                    "contract_ref": str(record["contract_ref"]),
                    "package_ref": str(record["package_ref"]),
                    "policy_ref": str(record["policy_ref"]),
                    "requested_fix_scope": list(requested),
                    "launch_binding_digest": str(record["launch_binding_digest"]),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkerAuthorityError(
                    "remediation launch record is incomplete",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                ) from exc
            expected_digest = _digest(projection)
            if str(record.get("record_digest", "")) != expected_digest:
                raise WorkerAuthorityError(
                    "remediation launch record digest mismatch",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                )
            event_id = projection["attempt_event_id"]
            if event_id in launches:
                raise WorkerAuthorityError(
                    "duplicate remediation Worker launch authorization",
                    reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
                )
            launches[event_id] = RemediationAttemptLaunchEvent(
                attempt_event_id=event_id,
                attempt_index=projection["attempt_index"],
                task_ref=projection["task_ref"],
                contract_ref=projection["contract_ref"],
                package_ref=projection["package_ref"],
                policy_ref=projection["policy_ref"],
                requested_fix_scope=requested,
                launch_binding_digest=projection["launch_binding_digest"],
                record_digest=expected_digest,
            )
        return launches

    @staticmethod
    def _append_record(handle, record: dict[str, Any]) -> None:
        handle.seek(0, os.SEEK_END)
        handle.write(_canonical_json(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    @staticmethod
    def _lineage(
        events: Sequence[RemediationAttemptStartedEvent],
        *,
        task_ref: str,
        contract_ref: str,
        package_ref: str,
        policy_ref: str,
    ) -> list[RemediationAttemptStartedEvent]:
        lineage = [
            event
            for event in events
            if event.task_ref == task_ref
            and event.contract_ref == contract_ref
            and event.package_ref == package_ref
            and event.policy_ref == policy_ref
        ]
        lineage.sort(key=lambda event: event.attempt_index)
        indices = [event.attempt_index for event in lineage]
        if len(indices) != len(set(indices)):
            raise WorkerAuthorityError(
                "duplicate remediation attempt_index in lineage",
                reason_taxonomy="REMEDIATION_LEDGER_CORRUPT",
            )
        return lineage

    @staticmethod
    def _binding(
        package: ExecutionPackage,
        active_contract: CanonicalExecutionContract,
        policy: RemediationPolicy,
    ) -> tuple[str, str, str, str]:
        _validate_remediation_binding(policy, package, active_contract)
        return (
            package.run_binding.worker_task_id,
            package.contract_ref,
            execution_package_ref(package),
            policy.policy_ref,
        )

    def reserve_attempt(
        self,
        policy: RemediationPolicy,
        *,
        package: ExecutionPackage,
        active_contract: CanonicalExecutionContract,
        failure_owner: str,
    ) -> RemediationAttemptStartedEvent:
        task_ref, contract_ref, package_ref, policy_ref = self._binding(
            package, active_contract, policy
        )
        if policy.mode is RemediationMode.DISABLED:
            raise WorkerAuthorityError(
                "remediation is DISABLED",
                reason_taxonomy=BLOCKED_POST_QUALITY,
            )
        if not isinstance(failure_owner, str) or not failure_owner.strip():
            raise WorkerAuthorityError(
                "failure_owner taxonomy is required",
                reason_taxonomy="REMEDIATION_RESERVATION_INVALID",
            )
        failure_owner = failure_owner.strip()

        handle = self._locked_file()
        try:
            records = self._read_records(handle)
            started = self._started_records(records)
            reviews = self._review_records(records)
            self._launch_records(records)  # validates durable launch records
            lineage = self._lineage(
                started,
                task_ref=task_ref,
                contract_ref=contract_ref,
                package_ref=package_ref,
                policy_ref=policy_ref,
            )
            if lineage:
                last_event = lineage[-1]
                if last_event.attempt_event_id not in reviews:
                    raise WorkerAuthorityError(
                        "a committed remediation attempt is still open; resume it instead of allocating another",
                        reason_taxonomy="REMEDIATION_ATTEMPT_ALREADY_RESERVED",
                    )
                last_review = reviews[last_event.attempt_event_id]
                if last_review.quality_passed:
                    raise WorkerAuthorityError(
                        "last committed remediation review already passed",
                        reason_taxonomy="REMEDIATION_NOT_REQUIRED_AFTER_PASS",
                    )
                current_index = last_event.attempt_index
            else:
                current_index = 0

            next_index = current_index + 1
            if next_index > policy.max_attempts:
                raise WorkerAuthorityError(
                    "remediation attempts exhausted",
                    reason_taxonomy=BLOCKED_REMEDIATION_EXHAUSTED,
                )
            event_id = "rem-" + _digest(
                {
                    "policy_ref": policy_ref,
                    "task_ref": task_ref,
                    "contract_ref": contract_ref,
                    "package_ref": package_ref,
                    "failure_owner": failure_owner,
                    "attempt_index": next_index,
                }
            )[:24]
            projection = {
                "record_type": REMEDIATION_ATTEMPT_STARTED,
                "attempt_event_id": event_id,
                "attempt_index": next_index,
                "task_ref": task_ref,
                "contract_ref": contract_ref,
                "package_ref": package_ref,
                "failure_owner": failure_owner,
                "policy_ref": policy_ref,
            }
            event_digest = _digest(projection)
            self._append_record(handle, {**projection, "event_digest": event_digest})
            return RemediationAttemptStartedEvent(
                attempt_event_id=event_id,
                attempt_index=next_index,
                task_ref=task_ref,
                contract_ref=contract_ref,
                package_ref=package_ref,
                failure_owner=failure_owner,
                policy_ref=policy_ref,
                event_digest=event_digest,
            )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def resume_open_attempt(
        self,
        policy: RemediationPolicy,
        *,
        package: ExecutionPackage,
        active_contract: CanonicalExecutionContract,
    ) -> RemediationAttemptStartedEvent:
        task_ref, contract_ref, package_ref, policy_ref = self._binding(
            package, active_contract, policy
        )
        handle = self._locked_file()
        try:
            records = self._read_records(handle)
            reviews = self._review_records(records)
            self._launch_records(records)
            lineage = self._lineage(
                self._started_records(records),
                task_ref=task_ref,
                contract_ref=contract_ref,
                package_ref=package_ref,
                policy_ref=policy_ref,
            )
            if not lineage:
                raise WorkerAuthorityError(
                    "no committed remediation attempt to resume",
                    reason_taxonomy="REMEDIATION_ATTEMPT_NOT_FOUND",
                )
            event = lineage[-1]
            if event.attempt_event_id in reviews:
                raise WorkerAuthorityError(
                    "latest remediation attempt is already reviewed",
                    reason_taxonomy="REMEDIATION_ATTEMPT_ALREADY_REVIEWED",
                )
            return event
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def authorize_remediation_launch(
        self,
        event: RemediationAttemptStartedEvent,
        policy: RemediationPolicy,
        *,
        package: ExecutionPackage,
        active_contract: CanonicalExecutionContract,
        requested_fix_scope: Sequence[str],
    ) -> str:
        task_ref, contract_ref, package_ref, policy_ref = self._binding(
            package, active_contract, policy
        )
        if policy.mode is not RemediationMode.BOUNDED:
            raise WorkerAuthorityError(
                "remediation launch requires BOUNDED policy",
                reason_taxonomy=BLOCKED_POST_QUALITY,
            )
        requested = _sorted_unique(
            requested_fix_scope,
            field_name="requested_fix_scope",
            allow_empty=False,
        )
        if not set(requested).issubset(set(policy.allowed_fix_scope)):
            raise WorkerAuthorityError(
                "remediation requested scope exceeds allowed_fix_scope",
                reason_taxonomy="REMEDIATION_FIX_SCOPE_EXCEEDED",
            )

        handle = self._locked_file()
        try:
            records = self._read_records(handle)
            started = {
                item.attempt_event_id: item for item in self._started_records(records)
            }
            reviews = self._review_records(records)
            launches = self._launch_records(records)
            committed = started.get(event.attempt_event_id)
            if committed is None:
                raise WorkerAuthorityError(
                    "attempt event is not durably committed",
                    reason_taxonomy="REMEDIATION_ATTEMPT_NOT_DURABLE",
                )
            if committed != event:
                raise WorkerAuthorityError(
                    "remediation launch event binding drift",
                    reason_taxonomy="REMEDIATION_ATTEMPT_BINDING_DRIFT",
                )
            if (
                event.task_ref != task_ref
                or event.contract_ref != contract_ref
                or event.package_ref != package_ref
                or event.policy_ref != policy_ref
            ):
                raise WorkerAuthorityError(
                    "remediation launch is not bound to current Task/Contract/Package",
                    reason_taxonomy="REMEDIATION_ATTEMPT_BINDING_DRIFT",
                )
            if event.attempt_event_id in reviews:
                raise WorkerAuthorityError(
                    "reviewed remediation attempt cannot launch again",
                    reason_taxonomy="REMEDIATION_ATTEMPT_ALREADY_REVIEWED",
                )
            if event.attempt_event_id in launches:
                raise WorkerAuthorityError(
                    "remediation attempt Worker launch was already consumed",
                    reason_taxonomy="REMEDIATION_ATTEMPT_ALREADY_LAUNCHED",
                )
            launch_binding_digest = _digest(
                {
                    "attempt_event_id": event.attempt_event_id,
                    "event_digest": event.event_digest,
                    "attempt_index": event.attempt_index,
                    "task_ref": task_ref,
                    "contract_ref": contract_ref,
                    "package_ref": package_ref,
                    "policy_ref": policy_ref,
                    "requested_fix_scope": list(requested),
                }
            )
            projection = {
                "record_type": REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED,
                "attempt_event_id": event.attempt_event_id,
                "attempt_index": event.attempt_index,
                "task_ref": task_ref,
                "contract_ref": contract_ref,
                "package_ref": package_ref,
                "policy_ref": policy_ref,
                "requested_fix_scope": list(requested),
                "launch_binding_digest": launch_binding_digest,
            }
            record_digest = _digest(projection)
            self._append_record(handle, {**projection, "record_digest": record_digest})
            return launch_binding_digest
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def commit_attempt_review(
        self,
        event: RemediationAttemptStartedEvent,
        policy: RemediationPolicy,
        *,
        package: ExecutionPackage,
        active_contract: CanonicalExecutionContract,
        quality_passed: bool,
        quality_assessment_digest: str,
    ) -> RemediationAttemptReviewEvent:
        task_ref, contract_ref, package_ref, policy_ref = self._binding(
            package, active_contract, policy
        )
        if not isinstance(quality_assessment_digest, str) or not quality_assessment_digest.strip():
            raise WorkerAuthorityError(
                "quality assessment digest is required",
                reason_taxonomy="REMEDIATION_REVIEW_INVALID",
            )
        handle = self._locked_file()
        try:
            records = self._read_records(handle)
            started = {
                item.attempt_event_id: item for item in self._started_records(records)
            }
            launches = self._launch_records(records)
            reviews = self._review_records(records)
            committed = started.get(event.attempt_event_id)
            if committed is None:
                raise WorkerAuthorityError(
                    "attempt event is not durably committed",
                    reason_taxonomy="REMEDIATION_ATTEMPT_NOT_DURABLE",
                )
            if committed != event:
                raise WorkerAuthorityError(
                    "attempt event binding drift",
                    reason_taxonomy="REMEDIATION_ATTEMPT_BINDING_DRIFT",
                )
            if (
                event.task_ref != task_ref
                or event.contract_ref != contract_ref
                or event.package_ref != package_ref
                or event.policy_ref != policy_ref
            ):
                raise WorkerAuthorityError(
                    "attempt review is not bound to current Task/Contract/Package",
                    reason_taxonomy="REMEDIATION_ATTEMPT_BINDING_DRIFT",
                )
            if event.attempt_event_id not in launches:
                raise WorkerAuthorityError(
                    "attempt review requires a durably authorized Worker launch",
                    reason_taxonomy="REMEDIATION_ATTEMPT_NOT_LAUNCHED",
                )
            if event.attempt_event_id in reviews:
                raise WorkerAuthorityError(
                    "attempt review already committed",
                    reason_taxonomy="REMEDIATION_ATTEMPT_REVIEW_DUPLICATE",
                )
            projection = {
                "record_type": REMEDIATION_ATTEMPT_REVIEWED,
                "attempt_event_id": event.attempt_event_id,
                "quality_passed": bool(quality_passed),
                "quality_assessment_digest": quality_assessment_digest.strip(),
            }
            record_digest = _digest(projection)
            self._append_record(handle, {**projection, "record_digest": record_digest})
            return RemediationAttemptReviewEvent(
                attempt_event_id=event.attempt_event_id,
                quality_passed=bool(quality_passed),
                quality_assessment_digest=quality_assessment_digest.strip(),
                record_digest=record_digest,
            )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
