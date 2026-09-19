from __future__ import annotations

import unittest

from runtime.ai_office.execution_coordinator import AIExecutionCoordinator, AIExecutionCoordinationError, WAIT_STATE
from runtime.orchestrator.office_execution_contract import OFFICE_EXECUTION_REQUEST_SCHEMA_V1, OfficeExecutionRequestV1

D = "c" * 64


def request() -> OfficeExecutionRequestV1:
    return OfficeExecutionRequestV1(
        OFFICE_EXECUTION_REQUEST_SCHEMA_V1, "proj", "run", "workflow", "task", "task-exec",
        "intent-ref", D, "STATE_CHANGING", "gov-ref", D, "risk-ref", D, "delegated-auth", D,
        "auth-binding", D, "execution-package", D, "execution-contract", D,
        "full-plan-assignment", D, "GATE-005", "full-plan-run", "task", "corr",
    )


class AIOfficeManualActionCoordinationTest(unittest.TestCase):
    def test_005_blocked_mutation_keeps_read_only_continuation_eligible(self) -> None:
        state, manual, continuation = AIExecutionCoordinator.blocked_state_change(
            request(), router_decision_ref="router-decision", router_decision_digest=D,
            blocked_reason_ref="action-provider-blocked", blocked_reason_digest=D,
            continuation={"required_capabilities": ("reasoning", "review", "documentation"),
                          "execution_authority":"READ_ONLY", "dependency_safe":True,
                          "dependency_safety_ref":"dependency-safe", "dependency_safety_digest":D,
                          "full_plan_router_handoff_ref":"full-plan-router-handoff",
                          "full_plan_router_handoff_digest":D},
        )
        self.assertEqual(WAIT_STATE, state.state); self.assertIsNone(manual); self.assertIsNotNone(continuation)
        self.assertEqual("READ_ONLY", continuation.execution_authority)
        self.assertNotIn("provider", str(continuation.to_dict()).lower())
        self.assertNotIn("model", str(continuation.to_dict()).lower())

    def test_006_bounded_manual_action_reference_can_resume_same_identity(self) -> None:
        state, handoff, _ = AIExecutionCoordinator.blocked_state_change(
            request(), router_decision_ref="router-decision", router_decision_digest=D,
            blocked_reason_ref="action-provider-blocked", blocked_reason_digest=D,
            manual_action={"action_package_ref":"manual-package", "action_package_digest":D,
                           "authorization_ref":"manual-auth", "authorization_digest":D,
                           "source_identity_ref":"source-identity", "source_identity_digest":D},
        )
        resume = AIExecutionCoordinator.resume_after_manual_action(
            state, handoff, manual_action_result_ref="manual-result", manual_action_result_digest=D,
        )
        self.assertEqual("EXECUTION_PENDING", resume.next_state)
        self.assertEqual(handoff.handoff_digest, resume.manual_action_handoff_digest)

    def test_006_unbound_manual_action_cannot_resume(self) -> None:
        state, handoff, _ = AIExecutionCoordinator.blocked_state_change(
            request(), router_decision_ref="router-decision", router_decision_digest=D,
            blocked_reason_ref="action-provider-blocked", blocked_reason_digest=D,
            manual_action={"action_package_ref":"manual-package", "action_package_digest":D,
                           "authorization_ref":"manual-auth", "authorization_digest":D,
                           "source_identity_ref":"source-identity", "source_identity_digest":D},
        )
        altered = type(handoff)(handoff.schema_version, handoff.project_id, handoff.project_run_id,
                                handoff.workflow_item_id, handoff.task_execution_id, handoff.correlation_id,
                                "different-package", D, handoff.authorization_ref, D,
                                handoff.source_identity_ref, D)
        with self.assertRaises(AIExecutionCoordinationError):
            AIExecutionCoordinator.resume_after_manual_action(
                state, altered, manual_action_result_ref="manual-result", manual_action_result_digest=D)


if __name__ == "__main__": unittest.main()
