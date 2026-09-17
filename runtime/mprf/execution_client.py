"""Public-boundary-only execution client reserved for the future MPRF consumer."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from runtime.orchestrator.public_execution_contract import (
    PublicExecutionRequestV1,
    PublicExecutionResultV1,
    public_execution_result_from_mapping,
)

PublicExecutionTransport = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class PublicExecutionClientError(ValueError):
    pass


class PublicExecutionClient:
    def __init__(self, transport: PublicExecutionTransport) -> None:
        if not callable(transport):
            raise PublicExecutionClientError("public execution transport must be callable")
        self._transport = transport

    def execute(self, request: PublicExecutionRequestV1) -> PublicExecutionResultV1:
        if not isinstance(request, PublicExecutionRequestV1):
            raise PublicExecutionClientError("request must use the public execution contract")
        raw = self._transport(request.to_dict())
        if not isinstance(raw, Mapping):
            raise PublicExecutionClientError("public execution transport returned a non-object")
        result = public_execution_result_from_mapping(raw)
        if result.operation_request_id != request.operation_request_id or result.correlation_id != request.correlation_id:
            raise PublicExecutionClientError("public execution response binding mismatch")
        return result

# TASK-013: ordered recovery/resume orchestration over public references only.
from dataclasses import dataclass

from .checkpoint import CHECKPOINT_VALID, MPRFCheckpointV1, validate_checkpoint
from .contracts import MPRFContractError
from .failure import FailureClassV1, FailoverPrerequisitesV1, evaluate_failover
from .router_client import RerouteRequestV1, build_reroute_request as build_public_reroute

RECOVERY_SEQUENCE_SCHEMA_V1 = "mprf.recovery-sequence-result.v1"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
RESUMED = "RESUMED"
EFFECT_CONFIRMED = "CONFIRMED"
EFFECT_AMBIGUOUS = "AMBIGUOUS"
EFFECT_FAILED = "FAILED"
RECOVERY_STAGES_V1 = (
    "CHECKPOINT", "ARTIFACT", "EFFECT_RECONCILIATION", "AUTHORIZATION",
    "FAILOVER_POLICY", "ROUTER", "RESUME",
)


def _recovery_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MPRFContractError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class RecoverySequenceResultV1:
    schema_version: str
    status: str
    completed_stages: tuple[str, ...]
    blocked_stage: str
    reason_code: str
    checkpoint_ref: str
    reroute_request_ref: str = ""
    router_decision_ref: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != RECOVERY_SEQUENCE_SCHEMA_V1:
            raise MPRFContractError("unsupported recovery sequence result schema")
        if self.status not in {RECOVERY_REQUIRED, RESUMED}:
            raise MPRFContractError("unknown recovery sequence status")
        if any(stage not in RECOVERY_STAGES_V1 for stage in self.completed_stages):
            raise MPRFContractError("unknown recovery stage in trace")
        if tuple(RECOVERY_STAGES_V1[:len(self.completed_stages)]) != self.completed_stages:
            raise MPRFContractError("recovery stages are not an ordered prefix")
        if self.blocked_stage and self.blocked_stage not in RECOVERY_STAGES_V1:
            raise MPRFContractError("unknown blocked recovery stage")
        _recovery_text(self.reason_code, "reason_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "status": self.status,
            "completed_stages": list(self.completed_stages), "blocked_stage": self.blocked_stage,
            "reason_code": self.reason_code, "checkpoint_ref": self.checkpoint_ref,
            "reroute_request_ref": self.reroute_request_ref, "router_decision_ref": self.router_decision_ref,
        }


def _blocked_recovery(completed: list[str], stage: str, reason: str, checkpoint_ref: str,
                      reroute_ref: str = "", decision_ref: str = "") -> RecoverySequenceResultV1:
    return RecoverySequenceResultV1(
        RECOVERY_SEQUENCE_SCHEMA_V1, RECOVERY_REQUIRED, tuple(completed), stage, reason,
        checkpoint_ref, reroute_ref, decision_ref,
    )


def execute_recovery_sequence(*, checkpoint: MPRFCheckpointV1, project_id: str, run_id: str,
                              task_id: str, task_execution_id: str, expected_parent_checkpoint_ref: str,
                              artifact_integrity_ref: str, artifact_valid: bool,
                              effect_reconciliation_ref: str, effect_status: str,
                              authorization_validation_ref: str, authorization_valid: bool,
                              policy_validation_ref: str, policy_valid: bool,
                              failure: FailureClassV1 | str, original_router_decision: Any,
                              reroute_request_id: str, network_safe_policy_evidence_ref: str = "",
                              permission_related_auth: bool = False,
                              router_exchange: Callable[[RerouteRequestV1], Any],
                              resume_exchange: Callable[[str], bool]) -> RecoverySequenceResultV1:
    """Enforce approved recovery order; Router/resume authorities stay external."""
    completed: list[str] = []
    check = validate_checkpoint(
        checkpoint, project_id=project_id, run_id=run_id, task_id=task_id,
        task_execution_id=task_execution_id, expected_parent_checkpoint_ref=expected_parent_checkpoint_ref,
    )
    if check.status != CHECKPOINT_VALID:
        return _blocked_recovery(completed, "CHECKPOINT", check.reason_code, check.checkpoint_ref)
    completed.append("CHECKPOINT")

    if not isinstance(artifact_valid, bool) or not artifact_valid or not artifact_integrity_ref:
        return _blocked_recovery(completed, "ARTIFACT", "ARTIFACT_INTEGRITY_INVALID", check.checkpoint_ref)
    completed.append("ARTIFACT")

    if effect_status not in {EFFECT_CONFIRMED, EFFECT_AMBIGUOUS, EFFECT_FAILED} or not effect_reconciliation_ref:
        return _blocked_recovery(completed, "EFFECT_RECONCILIATION", "EFFECT_RECONCILIATION_INVALID", check.checkpoint_ref)
    if effect_status != EFFECT_CONFIRMED:
        reason = "ACTION_SIDE_EFFECT_AMBIGUOUS" if effect_status == EFFECT_AMBIGUOUS else "EFFECT_RECONCILIATION_FAILED"
        return _blocked_recovery(completed, "EFFECT_RECONCILIATION", reason, check.checkpoint_ref)
    completed.append("EFFECT_RECONCILIATION")

    if not isinstance(authorization_valid, bool) or not authorization_valid or not authorization_validation_ref:
        return _blocked_recovery(completed, "AUTHORIZATION", "AUTHORIZATION_REVALIDATION_FAILED", check.checkpoint_ref)
    completed.append("AUTHORIZATION")

    if not isinstance(policy_valid, bool) or not policy_valid or not policy_validation_ref:
        return _blocked_recovery(completed, "FAILOVER_POLICY", "FAILOVER_POLICY_INVALID", check.checkpoint_ref)
    prerequisites = FailoverPrerequisitesV1(
        "mprf.failover-prerequisites.v1", check.checkpoint_ref, artifact_integrity_ref,
        effect_reconciliation_ref, authorization_validation_ref, policy_validation_ref,
        network_safe_policy_evidence_ref,
    )
    disposition = evaluate_failover(failure, prerequisites, permission_related_auth=permission_related_auth)
    if not disposition.reroute_eligible:
        return _blocked_recovery(completed, "FAILOVER_POLICY", disposition.reason_code, check.checkpoint_ref)
    completed.append("FAILOVER_POLICY")

    reroute = build_public_reroute(
        request_id=_recovery_text(reroute_request_id, "reroute_request_id"), project_id=project_id,
        run_id=run_id, task_id=task_id, task_execution_id=task_execution_id,
        original_router_decision=original_router_decision, failure=failure,
        prerequisites=prerequisites, permission_related_auth=permission_related_auth,
    )
    decision = router_exchange(reroute)
    eligible = getattr(decision, "eligible", None)
    stage = getattr(decision, "stage", None)
    capabilities = getattr(decision, "required_capabilities", None)
    decision_id = getattr(decision, "decision_id", None)
    decision_digest = getattr(decision, "decision_digest", None)
    if eligible is not True or not isinstance(decision_id, str) or not decision_id or not isinstance(decision_digest, str):
        return _blocked_recovery(completed, "ROUTER", "ROUTER_DECISION_BLOCKED", check.checkpoint_ref, reroute.router_reference)
    if stage != reroute.original_stage or not isinstance(capabilities, tuple) or capabilities != tuple(reroute.requested_capabilities):
        return _blocked_recovery(completed, "ROUTER", "ROUTER_DECISION_BINDING_MISMATCH", check.checkpoint_ref, reroute.router_reference)
    decision_ref = f"router-decision://{decision_id}#{decision_digest}"
    completed.append("ROUTER")

    if resume_exchange(decision_ref) is not True:
        return _blocked_recovery(completed, "RESUME", "RESUME_REJECTED", check.checkpoint_ref, reroute.router_reference, decision_ref)
    completed.append("RESUME")
    return RecoverySequenceResultV1(
        RECOVERY_SEQUENCE_SCHEMA_V1, RESUMED, tuple(completed), "", "RESUME_COMPLETED",
        check.checkpoint_ref, reroute.router_reference, decision_ref,
    )
