import unittest

from runtime.orchestrator.operations_diagnostic_projection import (
    build_diagnostic_health_projection,
)


class OperationsDiagnosticProjectionTests(unittest.TestCase):
    def test_historical_attention_does_not_become_current_self_diagnosis_issue(self):
        result = build_diagnostic_health_projection(
            current_state={"normalized_state": "RUNNING", "freshness": "FRESH"},
            diagnostic_findings=(),
            attention_events=(
                {"kind": "STALL_CONFIRMED", "state": "HISTORICAL", "evidence_ref": "attention:old"},
            ),
            recovery_refs=(),
        )
        self.assertEqual(result.overall_state, "HEALTHY")
        self.assertEqual(result.current_issue_count, 0)
        self.assertFalse(result.user_action_required)

    def test_self_diagnosis_contract_has_no_mutation_methods(self):
        result = build_diagnostic_health_projection(
            current_state={"normalized_state": "FAILED", "freshness": "FRESH"},
            diagnostic_findings=(
                {"domain": "runtime_binding", "state": "BLOCKED", "evidence_ref": "diag:1"},
            ),
            attention_events=(),
            recovery_refs=(),
        )
        self.assertEqual(result.overall_state, "BLOCKED")
        for name in ("restart", "kill", "recover", "complete_gate"):
            self.assertFalse(hasattr(result, name))


if __name__ == "__main__":
    unittest.main()
