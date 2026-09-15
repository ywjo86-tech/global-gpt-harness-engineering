from __future__ import annotations

import unittest

from runtime.orchestrator.execution_backend_entry_gate import (
    ENTRY_GATE_CONTRACT_VERSION,
    ENTRY_GATE_RECORD_TYPE,
    GO,
    NO_GO,
    evaluate_execution_backend_entry_gate,
)


def _yes_questions() -> tuple[dict[str, str], ...]:
    return tuple({"question_id": f"Q{index:02d}", "answer": "YES"} for index in range(1, 11))


def _passing_evidence() -> dict[str, object]:
    return {
        "preflight": {
            "compatibility_status": "PASS",
            "cli": {"detected": True, "version": "codex-cli 0.test"},
            "launcher_contract": {
                "supported_invocation_verified": True,
                "launcher_compatibility": True,
            },
        },
        "smoke_records": {
            "read_only_backend_diagnostic": {"status": "PASS"},
            "isolated_state_changing": {"status": "PASS", "protected_product_core_mutation_count": 0},
        },
        "fallback_record": {"status": "PASS", "manual_fallback_artifact_created": True},
        "routing_record": {
            "status": "PASS",
            "planner_provider_neutral": True,
            "state_changing_routes_to_codex": True,
            "read_only_reasoning_routes_to_nvidia": True,
            "nvidia_to_codex_auto_fallback_absent": True,
            "provider_router_authority_preserved": True,
        },
        "regression_records": {
            "full_plan_core": {"status": "PASS"},
            "graphify_phase2": {"status": "PASS", "historical_status_preserved": True},
        },
        "changed_file_record": {
            "status": "PASS",
            "only_approved_targets_changed": True,
            "protected_product_core_mutation_count": 0,
        },
        "core_change_record": {
            "core_change_classification": "NO_CORE_AUTHORITY_CHANGE",
            "authority_semantics_changed": False,
        },
        "known_issue_closure": {
            "issue_id": "GRAPHIFY_PHASE2_LAUNCHER_MISMATCH",
            "historical_completion_preserved": True,
            "manual_recovery_history_preserved": True,
            "no_core_modification_preserved": True,
            "closure_evidence_bound": True,
            "closure_status": "PASS",
        },
        "final_question_matrix": _yes_questions(),
        "evidence_references": tuple(f"evidence-{index:02d}" for index in range(1, 17)),
        "independent_review_reference": "independent-review.md",
    }


class ExecutionBackendEntryGateTests(unittest.TestCase):
    def test_gate_go_requires_all_mandatory_predicates_and_evidence(self) -> None:
        result = evaluate_execution_backend_entry_gate(_passing_evidence())

        self.assertEqual(result["record_type"], ENTRY_GATE_RECORD_TYPE)
        self.assertEqual(result["contract_version"], ENTRY_GATE_CONTRACT_VERSION)
        self.assertEqual(result["decision"], GO)
        self.assertEqual(result["blocking_reasons"], [])
        self.assertTrue(all(result["mandatory_predicates"].values()))

    def test_gate_no_go_when_preflight_launcher_not_compatible(self) -> None:
        evidence = _passing_evidence()
        evidence["preflight"] = {
            "compatibility_status": "BACKEND_LAUNCHER_COMPATIBILITY_FAILED",
            "cli": {"detected": True, "version": "codex-cli 0.test"},
            "launcher_contract": {
                "supported_invocation_verified": True,
                "launcher_compatibility": False,
            },
        }

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], NO_GO)
        self.assertIn("launcher_compatibility_pass", result["blocking_reasons"])

    def test_gate_no_go_when_final_question_matrix_is_incomplete(self) -> None:
        evidence = _passing_evidence()
        evidence["final_question_matrix"] = _yes_questions()[:9]

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], NO_GO)
        self.assertIn("final_10_questions_yes", result["blocking_reasons"])
        self.assertEqual(result["final_question_count"], 9)

    def test_gate_no_go_when_state_changing_smoke_mutates_protected_core(self) -> None:
        evidence = _passing_evidence()
        evidence["smoke_records"] = {
            "read_only_backend_diagnostic": {"status": "PASS"},
            "isolated_state_changing": {"status": "PASS", "protected_product_core_mutation_count": 1},
        }

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], NO_GO)
        self.assertIn("isolated_state_changing_smoke_pass", result["blocking_reasons"])

    def test_controlled_core_change_requires_pass_record(self) -> None:
        evidence = _passing_evidence()
        evidence["core_change_record"] = {
            "core_change_classification": "SEMANTICS_PRESERVING_CONTROLLED_CHANGE",
            "controlled_change_record_status": "PASS",
        }

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], GO)
        self.assertEqual(result["core_change_classification"], "SEMANTICS_PRESERVING_CONTROLLED_CHANGE")

    def test_plan_revision_required_is_no_go(self) -> None:
        evidence = _passing_evidence()
        evidence["core_change_record"] = {"core_change_classification": "PLAN_REVISION_REQUIRED"}

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], NO_GO)
        self.assertIn("core_change_classification_allowed", result["blocking_reasons"])

    def test_missing_known_issue_closure_fields_fail_closed(self) -> None:
        evidence = _passing_evidence()
        evidence["known_issue_closure"] = {
            "issue_id": "GRAPHIFY_PHASE2_LAUNCHER_MISMATCH",
            "historical_completion_preserved": True,
        }

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], NO_GO)
        self.assertFalse(result["known_issue_closure_bound"])
        self.assertIn("graphify_known_issue_closure_bound", result["blocking_reasons"])

    def test_missing_evidence_package_fields_do_not_claim_final_closure(self) -> None:
        evidence = _passing_evidence()
        evidence["evidence_references"] = tuple(f"evidence-{index:02d}" for index in range(1, 16))
        evidence["independent_review_reference"] = ""

        result = evaluate_execution_backend_entry_gate(evidence)

        self.assertEqual(result["decision"], NO_GO)
        self.assertIn("evidence_package_complete", result["blocking_reasons"])
        self.assertTrue(result["known_issue_closure_bound"])


if __name__ == "__main__":
    unittest.main()
