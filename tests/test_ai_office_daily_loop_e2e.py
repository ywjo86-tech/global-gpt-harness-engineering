from __future__ import annotations

import tempfile
import unittest

from runtime.ai_office.capability_governance import CAPABILITY_NEED_SCHEMA_V1, CapabilityNeedV1, route_capability_need
from runtime.ai_office.context_assembly import ContextSourceRefV1, assemble_context
from runtime.ai_office.execution_coordinator import AIExecutionCoordinator
from runtime.ai_office.governance import HUMAN_APPROVAL_SCHEMA_V1, RISK_ENVELOPE_SCHEMA_V1, HumanApprovalV1, RiskEnvelopeV1, evaluate_governance
from runtime.ai_office.reporting import build_office_report
from runtime.ai_office.requirement_intake import intake_requirement
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import FullPlanCompletionRefV1, WorkflowCoordinator
from runtime.orchestrator.observability_source_adapters import action_runtime_observation_from_record
from runtime.orchestrator.office_execution_backend_adapter import OfficeExecutionBackendAdapter
from runtime.orchestrator.office_execution_contract import OFFICE_EXECUTION_REQUEST_SCHEMA_V1, OfficeExecutionRequestV1
from runtime.orchestrator.public_observability_contract import CORRELATED_OBSERVATION_SCHEMA_V1, CorrelatedObservationV1

D1, D2, D3, D4 = (ch * 64 for ch in "abcd")


def _request(governance_digest: str, risk_digest: str) -> OfficeExecutionRequestV1:
    return OfficeExecutionRequestV1(
        OFFICE_EXECUTION_REQUEST_SCHEMA_V1, "PHASE5_AI_OFFICE_HARNESS_UPGRADE", "daily-run",
        "daily-workflow", "TASK-015", "daily-task-exec", "intent:daily", D1, "STATE_CHANGING",
        "governance:daily", governance_digest, "risk:daily", risk_digest, "approval:daily", D2,
        "authorization:daily", D3, "package:daily", D4, "contract:daily", D1,
        "full-plan:assignment-daily", D2, "GATE-005", "ai-office-ph5-gate005", "TASK-015", "corr-daily",
    )


class AIOfficeDailyLoopE2ETest(unittest.TestCase):
    def test_027_daily_loop_preserves_external_authority_and_correlates_observability(self) -> None:
        approved = {"REQ-E2E-DAILY": {"source_ref":"plan:REQ-E2E-DAILY", "source_digest":D1,
                                      "planning_authority_ref":"full-plan:approved", "constraints_refs":("constraint:daily",)}}
        requirement = intake_requirement({**approved["REQ-E2E-DAILY"], "requirement_id":"REQ-E2E-DAILY",
                                          "correlation_id":"corr-daily"}, approved_register=approved)
        context = assemble_context([requirement], (
            ContextSourceRefV1("repository", "VERIFIED_REPOSITORY", "repo:daily", D2),
            ContextSourceRefV1("runtime", "VERIFIED_STATE", "state:daily", D3),
        ))
        eligibility = route_capability_need(CapabilityNeedV1(
            CAPABILITY_NEED_SCHEMA_V1, "need:daily-review", ("reasoning", "review"), "READ_ONLY",
            "purpose:daily", "scope:daily"))
        self.assertEqual((eligibility.disposition, eligibility.owner_boundary), ("ROUTABLE", "MULTI_PROVIDER_ROUTER"))
        self.assertFalse({"provider", "provider_ref", "model", "model_ref", "selected", "final_assignee"}.intersection(eligibility.to_dict()))

        risk = RiskEnvelopeV1(RISK_ENVELOPE_SCHEMA_V1, "action:daily", "scope:daily", "scope:daily",
                              "HIGH", ("permission:filesystem",))
        approval = HumanApprovalV1(HUMAN_APPROVAL_SCHEMA_V1, "approval:daily", D2, "scope:daily", 100, 200)
        governance = evaluate_governance(risk, permission_allow=True, approval=approval,
                                         expected_approval_digest=D2, now_epoch=150)
        request = _request(governance.decision_digest, risk.envelope_digest)
        def handler(_payload):
            return {"office_request_digest":request.request_digest, "project_id":request.project_id,
                    "project_run_id":request.project_run_id, "workflow_item_id":request.workflow_item_id,
                    "task_execution_id":request.task_execution_id, "correlation_id":request.correlation_id,
                    "status":"COMPLETED", "result_digest":D4, "effect_ref":"effect:daily",
                    "audit_ref":"audit:daily", "reconciliation_state":"CONFIRMED", "error_code":""}
        result = AIExecutionCoordinator.execute(request, OfficeExecutionBackendAdapter(handler))

        action_record = {"schema_version":"gch.full-mcp.execution-event.v1", "operation_request_id":"op-daily",
                         "correlation_id":request.correlation_id, "operation":"office-daily-effect", "state":"AUTHORIZED",
                         "sequence":1, "occurred_at_utc":"2026-09-19T00:00:00.000Z", "result_digest":None,
                         "effect_id":result.effect_ref, "error_code":None, "audit_ref":result.audit_ref}
        action_observation = action_runtime_observation_from_record(
            action_record, project_id=request.project_id, project_run_id=request.project_run_id,
            task_execution_id=request.task_execution_id, source_ref="full-mcp:event:daily")
        correlated = CorrelatedObservationV1(
            CORRELATED_OBSERVATION_SCHEMA_V1, request.project_id, request.project_run_id,
            request.task_execution_id, request.correlation_id, "op-daily", (action_observation,), ())
        self.assertEqual(len(correlated.correlation_digest), 64)

        with tempfile.TemporaryDirectory() as directory:
            store = AIOfficeStateStore(directory, project_id=request.project_id, run_id=request.project_run_id)
            store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:mvp-goal-pass")
            workflow = WorkflowCoordinator(store, office_id="CEO", department_id="DAILY_LOOP", schedule_ref="schedule:daily")
            workflow.transition("REQUIREMENT_ACCEPTED", reason_ref=requirement.source_ref)
            workflow.transition("CONTEXT_ASSEMBLED", reason_ref=f"context:{context.context_digest}")
            handoff = workflow.transition("FULL_PLAN_HANDOFF_REFERENCED", reason_ref="full-plan:handoff",
                                          external_assignment_ref=request.full_plan_assignment_ref)
            self.assertEqual(handoff.external_full_plan_assignment_ref, request.full_plan_assignment_ref)
            workflow.transition("GOVERNANCE_READY", reason_ref=f"governance:{governance.decision_digest}")
            workflow.transition("EXECUTION_ACCEPTED", reason_ref=f"execution:{request.request_digest}")
            workflow.transition("RESULT_REFS_COMPLETE", reason_ref=result.audit_ref)
            completion = FullPlanCompletionRefV1("ai-office-ph5-gate005", "GATE-005", "gate:go", D3, "fanin:daily", D4)
            workflow.transition("GATE_GO_REFERENCED", reason_ref="gate:go", full_plan_completion=completion)
            first = build_office_report(store.load(), external_assignment_ref=request.full_plan_assignment_ref,
                                        full_plan_completion=completion,
                                        observation_refs=(f"observation:{correlated.correlation_digest}",))
            second = build_office_report(store.load(), external_assignment_ref=request.full_plan_assignment_ref,
                                         full_plan_completion=completion,
                                         observation_refs=(f"observation:{correlated.correlation_digest}",))
        self.assertEqual(first.report_digest, second.report_digest)
        self.assertEqual(first.status.workflow_state, "COMPLETE")
        self.assertEqual(first.kpi.observation_ref_count, 1)
        self.assertFalse({"provider", "model", "assignment_decision", "gate_decision", "action_truth", "provider_truth"}.intersection(first.to_dict()))

    def test_027_mixed_owner_capability_cannot_become_an_ai_office_assignment(self) -> None:
        mixed = route_capability_need(CapabilityNeedV1(
            CAPABILITY_NEED_SCHEMA_V1, "need:mixed", ("reasoning", "filesystem_write"), "STATE_CHANGING",
            "purpose:daily", "scope:daily"))
        self.assertEqual(mixed.disposition, "BLOCKED")
        self.assertEqual(mixed.owner_boundary, "")


if __name__ == "__main__":
    unittest.main()
