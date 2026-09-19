from __future__ import annotations

import tempfile
import unittest

from runtime.ai_office.capability_governance import CAPABILITY_NEED_SCHEMA_V1, CapabilityNeedV1, route_capability_need
from runtime.ai_office.context_assembly import ContextSourceRefV1, assemble_context
from runtime.ai_office.execution_coordinator import AIExecutionCoordinator
from runtime.ai_office.foundry import PROJECT_DEFINITION_SCHEMA_V1, OfficeProjectDefinitionV1, create_operating_contract, create_scaffold_intent
from runtime.ai_office.governance import HUMAN_APPROVAL_SCHEMA_V1, RISK_ENVELOPE_SCHEMA_V1, HumanApprovalV1, RiskEnvelopeV1, evaluate_governance
from runtime.ai_office.reporting import build_office_report
from runtime.ai_office.requirement_intake import intake_requirement
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import FullPlanCompletionRefV1, WorkflowCoordinator
from runtime.orchestrator.office_execution_backend_adapter import OfficeExecutionBackendAdapter
from runtime.orchestrator.office_execution_contract import OFFICE_EXECUTION_REQUEST_SCHEMA_V1, OfficeExecutionRequestV1

D1, D2, D3, D4, D5 = (ch * 64 for ch in "abcde")


def _requirement():
    approved = {"REQ-E2E-FACTORY": {"source_ref":"plan:REQ-E2E-FACTORY", "source_digest":D1,
                                     "planning_authority_ref":"full-plan:approved", "constraints_refs":("constraint:scope",)}}
    candidate = {**approved["REQ-E2E-FACTORY"], "requirement_id":"REQ-E2E-FACTORY", "correlation_id":"corr-factory"}
    return intake_requirement(candidate, approved_register=approved)


def _execution_request(governance_digest: str, risk_digest: str) -> OfficeExecutionRequestV1:
    return OfficeExecutionRequestV1(
        OFFICE_EXECUTION_REQUEST_SCHEMA_V1, "PHASE5_AI_OFFICE_HARNESS_UPGRADE", "factory-run",
        "factory-workflow", "TASK-015", "factory-task-exec", "scaffold:intent", D1,
        "STATE_CHANGING", "governance:factory", governance_digest, "risk:factory", risk_digest,
        "approval:user", D2, "authorization:binding", D3, "package:factory", D4,
        "contract:factory", D5, "full-plan:assignment-015", D1, "GATE-005",
        "ai-office-ph5-gate005", "TASK-015", "corr-factory",
    )


class AIOfficeProjectFactoryE2ETest(unittest.TestCase):
    def test_026_authorized_factory_flow_reaches_report_without_owning_routing_or_effect_truth(self) -> None:
        requirement = _requirement()
        context = assemble_context([requirement], (
            ContextSourceRefV1("repository", "VERIFIED_REPOSITORY", "repo:factory", D2),
            ContextSourceRefV1("run-state", "VERIFIED_STATE", "state:factory", D3),
        ))
        self.assertEqual(len(context.context_digest), 64)

        definition = OfficeProjectDefinitionV1(
            PROJECT_DEFINITION_SCHEMA_V1, "office-project-factory", "CEO",
            "/workspace/project/factory", "/workspace/project", requirement.requirement_id,
            f"context:{context.context_digest}", "template:factory", D4, ("policy:factory",),
        )
        risk = RiskEnvelopeV1(RISK_ENVELOPE_SCHEMA_V1, "action:scaffold", "scope:factory", "scope:factory",
                              "HIGH", ("permission:filesystem",))
        approval = HumanApprovalV1(HUMAN_APPROVAL_SCHEMA_V1, "approval:user", D2, "scope:factory", 100, 200)
        governance = evaluate_governance(risk, permission_allow=True, approval=approval,
                                         expected_approval_digest=D2, now_epoch=150)
        self.assertEqual(governance.decision, "ALLOW")
        contract = create_operating_contract(definition, governance_decision_ref="governance:factory",
                                             allowed_scaffold_scope=("runtime/factory", "tests/factory"))
        intent = create_scaffold_intent(contract, intended_paths=("runtime/factory/main.py", "tests/factory/test_main.py"),
                                        expected_changes=("create runtime", "create tests"), validation_refs=("TEST-026",))
        self.assertEqual(contract.lifecycle_state, "GOVERNED")
        self.assertEqual(len(intent.intent_digest), 64)

        eligibility = route_capability_need(CapabilityNeedV1(
            CAPABILITY_NEED_SCHEMA_V1, "need:factory-effect", ("filesystem_write",), "STATE_CHANGING",
            "purpose:factory", "scope:factory"))
        self.assertEqual((eligibility.disposition, eligibility.owner_boundary), ("ROUTABLE", "EXECUTION_BACKEND"))
        self.assertFalse({"provider", "provider_ref", "model", "model_ref"}.intersection(eligibility.to_dict()))

        request = _execution_request(governance.decision_digest, risk.envelope_digest)
        captured = {}
        def handler(payload):
            captured.update(payload)
            return {"office_request_digest":request.request_digest, "project_id":request.project_id,
                    "project_run_id":request.project_run_id, "workflow_item_id":request.workflow_item_id,
                    "task_execution_id":request.task_execution_id, "correlation_id":request.correlation_id,
                    "status":"COMPLETED", "result_digest":D5, "effect_ref":"effect:factory",
                    "audit_ref":"audit:factory", "reconciliation_state":"CONFIRMED", "error_code":""}
        result = AIExecutionCoordinator.execute(request, OfficeExecutionBackendAdapter(handler))
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(captured["full_plan_assignment_binding"]["task_id"], "TASK-015")
        self.assertFalse({"provider", "provider_ref", "model", "model_ref"}.intersection(captured))

        with tempfile.TemporaryDirectory() as directory:
            store = AIOfficeStateStore(directory, project_id=request.project_id, run_id=request.project_run_id)
            store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:mvp-goal-pass")
            workflow = WorkflowCoordinator(store, office_id="CEO", department_id="PROJECT_FACTORY", schedule_ref="schedule:factory")
            workflow.transition("REQUIREMENT_ACCEPTED", reason_ref="requirement:accepted")
            workflow.transition("CONTEXT_ASSEMBLED", reason_ref=f"context:{context.context_digest}")
            workflow.transition("FULL_PLAN_HANDOFF_REFERENCED", reason_ref="full-plan:handoff",
                                external_assignment_ref=request.full_plan_assignment_ref)
            workflow.transition("GOVERNANCE_READY", reason_ref=f"governance:{governance.decision_digest}")
            workflow.transition("EXECUTION_ACCEPTED", reason_ref=f"execution:{request.request_digest}")
            workflow.transition("RESULT_REFS_COMPLETE", reason_ref=result.audit_ref)
            completion = FullPlanCompletionRefV1("ai-office-ph5-gate005", "GATE-005", "gate:go", D4, "fanin:task-015", D5)
            finished = workflow.transition("GATE_GO_REFERENCED", reason_ref="gate:go", full_plan_completion=completion)
            report = build_office_report(store.load(), external_assignment_ref=finished.external_full_plan_assignment_ref,
                                         full_plan_completion=completion, observation_refs=(result.audit_ref,))
        self.assertEqual(report.status.workflow_state, "COMPLETE")
        self.assertEqual(report.external_fanin_ref, "fanin:task-015")
        payload = report.to_dict()
        self.assertFalse({"provider", "model", "action_truth", "provider_truth", "gate_decision", "fanin_decision"}.intersection(payload))

    def test_026_factory_scope_escape_is_not_created_by_e2e_fixture(self) -> None:
        requirement = _requirement()
        definition = OfficeProjectDefinitionV1(PROJECT_DEFINITION_SCHEMA_V1, "office-project-factory", "CEO",
            "/workspace/project/factory", "/workspace/project", requirement.requirement_id,
            "context:approved", "template:factory", D4, ("policy:factory",))
        contract = create_operating_contract(definition, governance_decision_ref="governance:factory",
                                             allowed_scaffold_scope=("runtime/factory",))
        with self.assertRaises(Exception):
            create_scaffold_intent(contract, intended_paths=("../escape.py",), expected_changes=("escape",),
                                   validation_refs=("TEST-026",))


if __name__ == "__main__":
    unittest.main()
