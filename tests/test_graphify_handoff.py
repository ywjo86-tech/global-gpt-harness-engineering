from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from poc.graphify import handoff

POC_ROOT = Path("/tmp/gch-graphify-poc/gch-graphify-poc-20260914T191500")


def _load(relative: str) -> dict:
    return json.loads((POC_ROOT / relative).read_text(encoding="utf-8"))


def _evidence_index() -> dict[str, str]:
    return {
        "decision_record": str(POC_ROOT / "results/decision_record.closed.json"),
        "decision_closure": str(POC_ROOT / "results/graphify_decision_closure.json"),
        "backend_independence": str(POC_ROOT / "records/backend_independence.json"),
        "phase_boundary": str(POC_ROOT / "records/phase_boundary.json"),
        "current_repository_boundary": str(POC_ROOT / "records/current_repository_boundary.json"),
        "memory_independence": str(POC_ROOT / "records/memory_independence.json"),
        "source_precedence": str(POC_ROOT / "records/source_precedence.json"),
        "context_boundary": str(POC_ROOT / "records/context_assembly_boundary.json"),
        "reserved_phase_isolation": str(POC_ROOT / "records/reserved_phase_isolation.json"),
        "independent_regression_review": str(POC_ROOT / "records/independent_regression_review.json"),
        "fallback_evidence": str(POC_ROOT / "results/fallback_evidence.json"),
        "comparative_report": str(POC_ROOT / "results/comparative_report.json"),
    }

class GraphifyHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision = _load("results/decision_record.closed.json")
        self.closure = _load("results/graphify_decision_closure.json")
        self.gate009 = _load("records/gate009.json")
        self.metrics = _load("results/comparative_report.json")["metrics"]
        self.evidence = _evidence_index()

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
