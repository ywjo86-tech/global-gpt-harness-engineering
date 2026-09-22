from __future__ import annotations

import copy
import unittest

from poc.graphify import handoff
from tests.graphify_test_fixture import (
    closed_decision_and_closure,
    comparative_report,
    evidence_index,
    gate009,
)


class GraphifyHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision, self.closure = closed_decision_and_closure()
        self.gate009 = gate009()
        self.metrics = comparative_report()["metrics"]
        self.evidence = evidence_index()

    def test_valid_phase3_handoff_is_ready(self) -> None:
        package = handoff.build_phase3_handoff(
            self.decision,
            self.closure,
            evidence_index=self.evidence,
            comparative_metrics=self.metrics,
        )
        gate = handoff.evaluate_gate006(package, self.gate009)
        self.assertEqual(package["next_master_phase"], handoff.NEXT_MASTER_PHASE)
        self.assertEqual(package["fallback_provider"], "existing_inspection")
        self.assertFalse(package["production_adoption_allowed"])
        self.assertEqual(gate["gate_status"], "GO")

    def test_handoff_before_closure_is_rejected(self) -> None:
        decision = copy.deepcopy(self.decision)
        decision["closure_state"] = None
        with self.assertRaises(ValueError):
            handoff.build_phase3_handoff(
                decision, self.closure,
                evidence_index=self.evidence,
                comparative_metrics=self.metrics,
            )

    def test_missing_evidence_blocks_gate006(self) -> None:
        evidence = dict(self.evidence)
        evidence["memory_independence"] = ""
        package = handoff.build_phase3_handoff(
            self.decision,
            self.closure,
            evidence_index=evidence,
            comparative_metrics=self.metrics,
        )
        gate = handoff.evaluate_gate006(package, self.gate009)
        self.assertEqual(gate["gate_status"], "NO_GO")
        self.assertTrue(any(r.startswith("missing_evidence:") for r in gate["reasons"]))

    def test_direct_future_phase_route_blocks_gate006(self) -> None:
        package = handoff.build_phase3_handoff(
            self.decision,
            self.closure,
            evidence_index=self.evidence,
            comparative_metrics=self.metrics,
        )
        package["next_master_phase"] = "PHASE_5_AI_OFFICE"
        gate = handoff.evaluate_gate006(package, self.gate009)
        self.assertEqual(gate["gate_status"], "NO_GO")
        self.assertIn("next_master_phase_mismatch", gate["reasons"])

    def test_production_policy_is_prerequisite_not_implicit_approval(self) -> None:
        package = handoff.build_phase3_handoff(
            self.decision,
            self.closure,
            evidence_index=self.evidence,
            comparative_metrics=self.metrics,
        )
        self.assertEqual(package["current_artifact_policy"], "LOCAL_ONLY_POC")
        self.assertFalse(package["production_adoption_allowed"])
        self.assertTrue(any("GATE-005" in item for item in package["production_policy_prerequisites"]))


if __name__ == "__main__":
    unittest.main()
