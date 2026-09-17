"""MPRF reroute request client; request generation only, never Router selection."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import MPRFContractError
from .failure import (
    FAILOVER_POLICY_VERSION_V1,
    FailureClassV1,
    FailoverPrerequisitesV1,
    evaluate_failover,
    failure_class,
)

REROUTE_REQUEST_SCHEMA_V1 = "mprf.reroute-request.v1"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MPRFContractError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class RerouteRequestV1:
    schema_version: str
    request_id: str
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    original_router_decision_digest: str
    original_stage: str
    failure_class: FailureClassV1
    requested_capabilities: tuple[str, ...]
    checkpoint_integrity_ref: str
    artifact_integrity_ref: str
    effect_reconciliation_ref: str
    authorization_validation_ref: str
    policy_validation_ref: str
    failover_policy_version: str = FAILOVER_POLICY_VERSION_V1

    def __post_init__(self) -> None:
        if self.schema_version != REROUTE_REQUEST_SCHEMA_V1:
            raise MPRFContractError("unsupported reroute request schema")
        for value, name in ((self.request_id, "request_id"), (self.project_id, "project_id"),
                            (self.run_id, "run_id"), (self.task_id, "task_id"),
                            (self.task_execution_id, "task_execution_id"),
                            (self.original_router_decision_digest, "original_router_decision_digest")):
            _text(value, name)
        if self.original_stage not in {"PREPARE", "ACTION", "VERIFY", "REVIEW"}:
            raise MPRFContractError("reroute request stage is invalid")
        if self.failover_policy_version != FAILOVER_POLICY_VERSION_V1:
            raise MPRFContractError("unsupported failover policy version")
        if not self.requested_capabilities or any(not isinstance(item, str) or not item for item in self.requested_capabilities):
            raise MPRFContractError("reroute request capabilities are invalid")
        if len(set(self.requested_capabilities)) != len(self.requested_capabilities):
            raise MPRFContractError("reroute request capabilities contain duplicates")
        for name in ("checkpoint_integrity_ref", "artifact_integrity_ref", "effect_reconciliation_ref",
                     "authorization_validation_ref", "policy_validation_ref"):
            _text(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "request_id": self.request_id,
                "project_id": self.project_id, "run_id": self.run_id, "task_id": self.task_id,
                "task_execution_id": self.task_execution_id,
                "original_router_decision_digest": self.original_router_decision_digest,
                "original_stage": self.original_stage, "failure_class": self.failure_class.value,
                "requested_capabilities": list(self.requested_capabilities),
                "checkpoint_integrity_ref": self.checkpoint_integrity_ref,
                "artifact_integrity_ref": self.artifact_integrity_ref,
                "effect_reconciliation_ref": self.effect_reconciliation_ref,
                "authorization_validation_ref": self.authorization_validation_ref,
                "policy_validation_ref": self.policy_validation_ref,
                "failover_policy_version": self.failover_policy_version}

    @property
    def request_digest(self) -> str:
        return _digest(self.to_dict())

    @property
    def router_reference(self) -> str:
        return f"mprf-reroute://{self.request_id}#{self.request_digest}"


def build_reroute_request(*, request_id: str, project_id: str, run_id: str, task_id: str,
                          task_execution_id: str, original_router_decision: Any,
                          failure: FailureClassV1 | str, prerequisites: FailoverPrerequisitesV1,
                          permission_related_auth: bool = False) -> RerouteRequestV1:
    from runtime.orchestrator.provider_router import RouterDecisionV2
    if not isinstance(original_router_decision, RouterDecisionV2):
        raise MPRFContractError("original RouterDecision.v2 is required")
    disposition = evaluate_failover(failure, prerequisites, permission_related_auth=permission_related_auth)
    if not disposition.reroute_eligible:
        raise MPRFContractError(f"reroute prohibited: {disposition.reason_code}")
    return RerouteRequestV1(
        REROUTE_REQUEST_SCHEMA_V1, _text(request_id, "request_id"), _text(project_id, "project_id"),
        _text(run_id, "run_id"), _text(task_id, "task_id"), _text(task_execution_id, "task_execution_id"),
        original_router_decision.decision_digest, original_router_decision.stage, failure_class(failure),
        tuple(sorted(set(original_router_decision.required_capabilities))),
        prerequisites.checkpoint_integrity_ref, prerequisites.artifact_integrity_ref,
        prerequisites.effect_reconciliation_ref, prerequisites.authorization_validation_ref,
        prerequisites.policy_validation_ref,
    )


def to_router_request_v2(reroute: RerouteRequestV1, *, directive_digest: str, eligibility_snapshot: Any):
    """Build the public RouterRequest.v2; Router remains the only decision authority."""
    from runtime.orchestrator.provider_router import (
        GOVERNED_POLICY_V1, MPRF_REROUTE_SOURCE_V1, ROUTER_REQUEST_SCHEMA_V2,
        ProviderEligibilitySnapshotV1, RouterRequestV2,
    )
    if not isinstance(reroute, RerouteRequestV1):
        raise MPRFContractError("RerouteRequest.v1 is required")
    if not isinstance(eligibility_snapshot, ProviderEligibilitySnapshotV1):
        raise MPRFContractError("ProviderEligibilitySnapshot.v1 is required")
    return RouterRequestV2(
        schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id=f"router-{reroute.request_id}",
        project_id=reroute.project_id, run_id=reroute.run_id, task_id=reroute.task_id,
        task_execution_id=reroute.task_execution_id, directive_digest=_text(directive_digest, "directive_digest"),
        stage=reroute.original_stage, required_capabilities=reroute.requested_capabilities,
        state_change_required=reroute.original_stage == "ACTION", policy_profile=GOVERNED_POLICY_V1,
        eligibility_snapshot=eligibility_snapshot, request_source=MPRF_REROUTE_SOURCE_V1,
        failure_class=reroute.failure_class.value, failover_request_ref=reroute.router_reference,
    )
