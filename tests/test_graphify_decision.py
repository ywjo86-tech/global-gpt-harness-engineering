from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poc.graphify.decision import evaluate_decision


def _report(graphify_count=4, baseline_count=0):
    return {
        "rows": [
            {"result": {"write_performed": False}}
            for _ in range(max(graphify_count, baseline_count, 1))
        ],
        "metrics": {
            "graphify": {"verified_count": graphify_count, "verified_rate": graphify_count / 4},
            "existing_inspection": {"verified_count": baseline_count, "verified_rate": baseline_count / 4},
        },
    }


def _evidence(value=True):
    keys = [
        "fallback_pass", "backend_independence", "phase_boundary",
        "current_repository_boundary", "memory_independence", "source_precedence",
        "context_assembly_boundary", "reserved_phase_isolation", "core_regression_pass",
    ]
    return {key: value for key in keys}


class GraphifyDecisionTests(unittest.TestCase):
    def _policy(self, root: Path) -> Path:
        path = root / "policy.yaml"
        path.write_text("policy: sealed\n", encoding="utf-8")
        return path

    def test_go_when_safety_and_material_benefit_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record = evaluate_decision(
                _report(), _evidence(), policy_path=self._policy(root),
                predecessor_baseline_ref="1" * 40,
                source_reverification_ref="2" * 40,
                graphify_version="0.9.58",
            )
            self.assertEqual(record["decision"], "GO")
            self.assertTrue(record["decision_finalized"])

    def test_hard_failure_forces_no_go(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = _evidence()
            evidence["memory_independence"] = False
            record = evaluate_decision(
                _report(), evidence, policy_path=self._policy(root),
                predecessor_baseline_ref="1" * 40,
                source_reverification_ref="2" * 40,
                graphify_version="0.9.58",
            )
            self.assertEqual(record["decision"], "NO_GO")

    def test_equal_verified_count_is_conditional_go(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record = evaluate_decision(
                _report(4, 4), _evidence(), policy_path=self._policy(root),
                predecessor_baseline_ref="1" * 40,
                source_reverification_ref="2" * 40,
                graphify_version="0.9.58",
            )
            self.assertEqual(record["decision"], "CONDITIONAL_GO")

    def test_same_inputs_produce_same_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kwargs = dict(
                policy_path=self._policy(root), predecessor_baseline_ref="1" * 40,
                source_reverification_ref="2" * 40, graphify_version="0.9.58",
            )
            first = evaluate_decision(_report(), _evidence(), **kwargs)
            second = evaluate_decision(_report(), _evidence(), **kwargs)
            self.assertEqual(first["decision_digest"], second["decision_digest"])


if __name__ == "__main__":
    unittest.main()
