from __future__ import annotations

import unittest

from runtime.orchestrator.execution_backend_preflight import (
    PREFLIGHT_CONTRACT_VERSION,
    PREFLIGHT_FAIL,
    PREFLIGHT_PASS,
    PREFLIGHT_RECORD_TYPE,
    ExecutionBackendPreflightInput,
    collect_execution_backend_preflight,
    evaluate_execution_backend_preflight,
)


def _passing_payload() -> dict[str, object]:
    return {
        "identity_baseline_binding": {"project_id": "graphify", "baseline_ref": "phase2-final"},
        "cli": {"detected": True, "version": "codex-cli 0.test", "executable": "sha256:fake"},
        "launcher_contract": {
            "supported_invocation_verified": True,
            "launcher_compatibility": True,
            "legacy_or_unsupported_invocation_detected": False,
        },
        "process_policy": {
            "automatic_retry_count": 0,
            "cwd_mode": "explicit-project-root",
            "output_transport": "output-last-message-json",
        },
        "fallback_policy": {
            "codex_to_manual_fallback_preserved": True,
            "nvidia_to_codex_auto_fallback_absent": True,
        },
        "result_flow_contract": {
            "provider_neutral_normalization_preserved": True,
            "stage_gate_authority_preserved": True,
            "provider_router_authority_preserved": True,
        },
        "known_issue": {
            "issue_id": "GRAPHIFY_PHASE2_LAUNCHER_MISMATCH",
            "observed_phase": "phase2",
            "temporary_recovery": "manual",
            "required_phase3_action": "codex launcher contract",
            "historical_completion_preserved": True,
            "no_core_modification_preserved": True,
        },
        "compatibility_status": PREFLIGHT_PASS,
        "blocking_reasons": [],
        "evidence_references": ["runtime/orchestrator/codex_launcher.py"],
    }


class ExecutionBackendPreflightTests(unittest.TestCase):
    def test_evaluate_passes_complete_compatible_record(self) -> None:
        result = evaluate_execution_backend_preflight(_passing_payload())

        self.assertEqual(result["record_type"], PREFLIGHT_RECORD_TYPE)
        self.assertEqual(result["contract_version"], PREFLIGHT_CONTRACT_VERSION)
        self.assertEqual(result["compatibility_status"], PREFLIGHT_PASS)
        self.assertTrue(result["preflight_passed"])
        self.assertEqual(result["blocking_reasons"], [])

    def test_evaluate_fails_closed_on_missing_cli_and_legacy_invocation(self) -> None:
        payload = _passing_payload()
        payload["cli"] = {"detected": False, "version": "", "executable": ""}
        payload["launcher_contract"] = {
            "supported_invocation_verified": False,
            "launcher_compatibility": False,
            "legacy_or_unsupported_invocation_detected": True,
        }

        result = evaluate_execution_backend_preflight(payload)

        self.assertEqual(result["compatibility_status"], PREFLIGHT_FAIL)
        self.assertFalse(result["preflight_passed"])
        self.assertIn("cli_not_detected", result["blocking_reasons"])
        self.assertIn("legacy_or_unsupported_invocation_detected", result["blocking_reasons"])

    def test_pass_claim_with_blockers_is_not_accepted(self) -> None:
        payload = _passing_payload()
        payload["fallback_policy"] = {"codex_to_manual_fallback_preserved": False}

        result = evaluate_execution_backend_preflight(payload)

        self.assertEqual(result["compatibility_status"], PREFLIGHT_FAIL)
        self.assertIn("codex_to_manual_fallback_not_preserved", result["blocking_reasons"])

    def test_collect_normalizes_input_dataclass_and_recomputes_status(self) -> None:
        payload = _passing_payload()
        payload.pop("compatibility_status")
        payload.pop("blocking_reasons")
        record = collect_execution_backend_preflight(
            ExecutionBackendPreflightInput(
                identity_baseline_binding=payload["identity_baseline_binding"],
                cli=payload["cli"],
                launcher_contract=payload["launcher_contract"],
                process_policy=payload["process_policy"],
                fallback_policy=payload["fallback_policy"],
                result_flow_contract=payload["result_flow_contract"],
                known_issue=payload["known_issue"],
                evidence_references=tuple(payload["evidence_references"]),
            )
        )

        self.assertEqual(record["record_type"], PREFLIGHT_RECORD_TYPE)
        self.assertEqual(record["compatibility_status"], PREFLIGHT_PASS)
        self.assertEqual(record["blocking_reasons"], [])

    def test_missing_required_known_issue_fields_fail_closed(self) -> None:
        payload = _passing_payload()
        payload["known_issue"] = {
            "issue_id": "GRAPHIFY_PHASE2_LAUNCHER_MISMATCH",
            "historical_completion_preserved": True,
            "no_core_modification_preserved": True,
        }

        result = evaluate_execution_backend_preflight(payload)

        self.assertEqual(result["compatibility_status"], PREFLIGHT_FAIL)
        self.assertFalse(result["preflight_passed"])
        self.assertIn("known_issue_observed_phase_missing", result["blocking_reasons"])
        self.assertIn("known_issue_temporary_recovery_missing", result["blocking_reasons"])
        self.assertIn("known_issue_required_phase3_action_missing", result["blocking_reasons"])

    def test_missing_evidence_references_fail_closed(self) -> None:
        payload = _passing_payload()
        payload["evidence_references"] = []

        result = evaluate_execution_backend_preflight(payload)

        self.assertEqual(result["compatibility_status"], PREFLIGHT_FAIL)
        self.assertFalse(result["preflight_passed"])
        self.assertIn("evidence_references_missing", result["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
