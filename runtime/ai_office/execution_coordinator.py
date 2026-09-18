"""AI Office execution coordination without action or provider authority."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from runtime.orchestrator.office_execution_backend_adapter import OfficeExecutionBackendAdapter
from runtime.orchestrator.office_execution_contract import (
    MANUAL_ACTION_HANDOFF_SCHEMA_V1,
    NON_MUTATING_CONTINUATION_SCHEMA_V1,
    ManualActionHandoffRefV1,
    NonMutatingContinuationRefV1,
    OfficeExecutionRequestV1,
    OfficeExecutionResultV1,
)

WAIT_STATE = "WAITING_STATE_CHANGE_AUTHORITY"
EXECUTION_PENDING = "EXECUTION_PENDING"


class AIExecutionCoordinationError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _safe_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise AIExecutionCoordinationError(f"{label} is not a SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionWaitStateV1:
    project_id: str
    project_run_id: str
    workflow_item_id: str
    task_execution_id: str
    correlation_id: str
    office_request_digest: str
    state: str
    router_decision_ref: str
    router_decision_digest: str
    blocked_reason_ref: str
    blocked_reason_digest: str
    manual_action_handoff_digest: str = ""
    non_mutating_continuation_digest: str = ""

    def __post_init__(self) -> None:
        if self.state != WAIT_STATE:
            raise AIExecutionCoordinationError("execution wait state is invalid")
        for value, label in ((self.office_request_digest, "office_request_digest"),
                             (self.router_decision_digest, "router_decision_digest"),
                             (self.blocked_reason_digest, "blocked_reason_digest")):
            _safe_digest(value, label)
        for value, label in ((self.manual_action_handoff_digest, "manual_action_handoff_digest"),
                             (self.non_mutating_continuation_digest, "non_mutating_continuation_digest")):
            if value:
                _safe_digest(value, label)
        if not self.manual_action_handoff_digest and not self.non_mutating_continuation_digest:
            raise AIExecutionCoordinationError("wait state requires a bounded handoff or non-mutating continuation")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def state_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExecutionResumeRefV1:
    project_id: str
    project_run_id: str
    workflow_item_id: str
    task_execution_id: str
    correlation_id: str
    prior_wait_state_digest: str
    manual_action_handoff_digest: str
    manual_action_result_ref: str
    manual_action_result_digest: str
    next_state: str = EXECUTION_PENDING

    def __post_init__(self) -> None:
        if self.next_state != EXECUTION_PENDING:
            raise AIExecutionCoordinationError("manual action resume target is invalid")
        _safe_digest(self.prior_wait_state_digest, "prior_wait_state_digest")
        _safe_digest(self.manual_action_handoff_digest, "manual_action_handoff_digest")
        _safe_digest(self.manual_action_result_digest, "manual_action_result_digest")
        if not self.manual_action_result_ref:
            raise AIExecutionCoordinationError("manual action result ref is required")

    @property
    def resume_digest(self) -> str:
        return _digest(asdict(self))


class AIExecutionCoordinator:
    """Coordinate public execution and typed waits; never execute Manual Action."""

    @staticmethod
    def execute(request: OfficeExecutionRequestV1, adapter: OfficeExecutionBackendAdapter) -> OfficeExecutionResultV1:
        if not isinstance(request, OfficeExecutionRequestV1) or not isinstance(adapter, OfficeExecutionBackendAdapter):
            raise AIExecutionCoordinationError("public request and backend-neutral adapter are required")
        return adapter.execute(request)

    @staticmethod
    def blocked_state_change(
        request: OfficeExecutionRequestV1, *, router_decision_ref: str, router_decision_digest: str,
        blocked_reason_ref: str, blocked_reason_digest: str,
        manual_action: Mapping[str, str] | None = None,
        continuation: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionWaitStateV1, ManualActionHandoffRefV1 | None, NonMutatingContinuationRefV1 | None]:
        if request.expected_effect_semantics != "STATE_CHANGING":
            raise AIExecutionCoordinationError("only blocked state-changing requests may enter the wait state")
        manual_ref = None
        continuation_ref = None
        if manual_action is not None:
            manual_ref = ManualActionHandoffRefV1(
                schema_version=MANUAL_ACTION_HANDOFF_SCHEMA_V1,
                project_id=request.project_id, project_run_id=request.project_run_id,
                workflow_item_id=request.workflow_item_id, task_execution_id=request.task_execution_id,
                correlation_id=request.correlation_id,
                action_package_ref=str(manual_action.get("action_package_ref", "")),
                action_package_digest=str(manual_action.get("action_package_digest", "")),
                authorization_ref=str(manual_action.get("authorization_ref", "")),
                authorization_digest=str(manual_action.get("authorization_digest", "")),
                source_identity_ref=str(manual_action.get("source_identity_ref", "")),
                source_identity_digest=str(manual_action.get("source_identity_digest", "")),
            )
        if continuation is not None:
            continuation_ref = NonMutatingContinuationRefV1(
                schema_version=NON_MUTATING_CONTINUATION_SCHEMA_V1,
                project_id=request.project_id, project_run_id=request.project_run_id,
                workflow_item_id=request.workflow_item_id, task_execution_id=request.task_execution_id,
                correlation_id=request.correlation_id,
                required_capabilities=tuple(continuation.get("required_capabilities", ())),
                execution_authority=str(continuation.get("execution_authority", "")),
                dependency_safe=bool(continuation.get("dependency_safe", False)),
                dependency_safety_ref=str(continuation.get("dependency_safety_ref", "")),
                dependency_safety_digest=str(continuation.get("dependency_safety_digest", "")),
                full_plan_router_handoff_ref=str(continuation.get("full_plan_router_handoff_ref", "")),
                full_plan_router_handoff_digest=str(continuation.get("full_plan_router_handoff_digest", "")),
            )
        state = ExecutionWaitStateV1(
            project_id=request.project_id, project_run_id=request.project_run_id,
            workflow_item_id=request.workflow_item_id, task_execution_id=request.task_execution_id,
            correlation_id=request.correlation_id, office_request_digest=request.request_digest,
            state=WAIT_STATE, router_decision_ref=router_decision_ref,
            router_decision_digest=router_decision_digest, blocked_reason_ref=blocked_reason_ref,
            blocked_reason_digest=blocked_reason_digest,
            manual_action_handoff_digest="" if manual_ref is None else manual_ref.handoff_digest,
            non_mutating_continuation_digest="" if continuation_ref is None else continuation_ref.continuation_digest,
        )
        return state, manual_ref, continuation_ref

    @staticmethod
    def resume_after_manual_action(
        wait_state: ExecutionWaitStateV1, handoff: ManualActionHandoffRefV1, *,
        manual_action_result_ref: str, manual_action_result_digest: str,
    ) -> ExecutionResumeRefV1:
        if wait_state.manual_action_handoff_digest != handoff.handoff_digest:
            raise AIExecutionCoordinationError("manual action handoff does not match the waiting state")
        identity = (wait_state.project_id, wait_state.project_run_id, wait_state.workflow_item_id,
                    wait_state.task_execution_id, wait_state.correlation_id)
        if identity != (handoff.project_id, handoff.project_run_id, handoff.workflow_item_id,
                        handoff.task_execution_id, handoff.correlation_id):
            raise AIExecutionCoordinationError("manual action handoff identity mismatch")
        return ExecutionResumeRefV1(
            project_id=wait_state.project_id, project_run_id=wait_state.project_run_id,
            workflow_item_id=wait_state.workflow_item_id, task_execution_id=wait_state.task_execution_id,
            correlation_id=wait_state.correlation_id, prior_wait_state_digest=wait_state.state_digest,
            manual_action_handoff_digest=handoff.handoff_digest,
            manual_action_result_ref=manual_action_result_ref,
            manual_action_result_digest=manual_action_result_digest,
        )
