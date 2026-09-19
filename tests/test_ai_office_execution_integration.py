from __future__ import annotations

import unittest

from runtime.orchestrator.office_execution_backend_adapter import (
    OfficeExecutionBackendAdapter, OfficeExecutionBackendAdapterError,
)
from runtime.orchestrator.office_execution_contract import OFFICE_EXECUTION_REQUEST_SCHEMA_V1, OfficeExecutionRequestV1

D = "b" * 64


def request(effect: str = "STATE_CHANGING") -> OfficeExecutionRequestV1:
    return OfficeExecutionRequestV1(
        OFFICE_EXECUTION_REQUEST_SCHEMA_V1, "proj", "run", "workflow", "task", "task-exec",
        "intent-ref", D, effect, "gov-ref", D, "risk-ref", D, "delegated-auth", D,
        "auth-binding", D, "execution-package", D, "execution-contract", D,
        "full-plan-assignment", D, "GATE-005", "full-plan-run", "task", "corr",
    )


class AIOfficeExecutionIntegrationTest(unittest.TestCase):
    def test_004_injected_handler_receives_exact_authorization_lineage(self) -> None:
        req = request(); captured = {}
        def handler(payload):
            captured.update(payload)
            return {"office_request_digest": req.request_digest, "project_id":"proj", "project_run_id":"run",
                    "workflow_item_id":"workflow", "task_execution_id":"task-exec", "correlation_id":"corr",
                    "status":"COMPLETED", "result_digest":D, "effect_ref":"effect-ref", "audit_ref":"audit-ref",
                    "reconciliation_state":"CONFIRMED", "error_code":""}
        result = OfficeExecutionBackendAdapter(handler).execute(req)
        self.assertEqual("COMPLETED", result.status)
        self.assertEqual(req.request_digest, captured["office_request_digest"])
        self.assertEqual(req.authorization_binding_digest,
                         captured["authorization_lineage"]["authorization_binding_digest"])
        self.assertEqual("STATE_CHANGING", captured["expected_effect_semantics"])
        self.assertEqual("full-plan-assignment", captured["full_plan_assignment_binding"]["assignment_ref"])
        self.assertEqual("task", captured["full_plan_assignment_binding"]["task_id"])

    def test_004_read_only_cannot_receive_mutation_effect(self) -> None:
        req = request("READ_ONLY")
        def handler(payload):
            return {"office_request_digest": req.request_digest, "project_id":"proj", "project_run_id":"run",
                    "workflow_item_id":"workflow", "task_execution_id":"task-exec", "correlation_id":"corr",
                    "status":"COMPLETED", "result_digest":D, "effect_ref":"effect-ref", "audit_ref":"audit-ref",
                    "reconciliation_state":"NOT_REQUIRED", "error_code":""}
        with self.assertRaises(OfficeExecutionBackendAdapterError): OfficeExecutionBackendAdapter(handler).execute(req)

    def test_004_state_change_result_identity_is_fail_closed(self) -> None:
        req = request()
        def handler(payload):
            return {"office_request_digest": req.request_digest, "project_id":"other", "project_run_id":"run",
                    "workflow_item_id":"workflow", "task_execution_id":"task-exec", "correlation_id":"corr",
                    "status":"BLOCKED", "result_digest":"", "effect_ref":"", "audit_ref":"audit-ref",
                    "reconciliation_state":"FAILED", "error_code":"AUTH_BLOCKED"}
        with self.assertRaises(OfficeExecutionBackendAdapterError): OfficeExecutionBackendAdapter(handler).execute(req)


if __name__ == "__main__": unittest.main()
