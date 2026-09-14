from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from poc.graphify import decision_closure

ROOT = Path(__file__).resolve().parents[1]
POC_ROOT = Path("/tmp/gch-graphify-poc/gch-graphify-poc-20260914T191500")


def _load(relative: str) -> dict:
    return json.loads((POC_ROOT / relative).read_text(encoding="utf-8"))


class GraphifyDecisionClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision = _load("results/decision_record.json")
        self.review = _load("records/independent_regression_review.json")
        self.reserved = _load("records/reserved_phase_isolation.json")

    def test_valid_finalized_decision_closes_without_outcome_mutation(self) -> None:
        record = decision_closure.finalize_decision_closure(
            self.decision, self.review, self.reserved
        )
        self.assertEqual(record["state"], "GRAPHIFY_DECISION_CLOSED")
        self.assertEqual(record["decision"], self.decision["decision"])
        self.assertEqual(record["decision_digest"], self.decision["decision_digest"])
        self.assertTrue(record["decision_outcome_unchanged"])
        self.assertEqual(record["reasons"], [])

    def test_tampered_digest_fails_closed(self) -> None:
        decision = copy.deepcopy(self.decision)
        decision["comparative_metric_summary"]["graphify"]["verified_count"] = 3
        record = decision_closure.finalize_decision_closure(
            decision, self.review, self.reserved
        )
        self.assertEqual(record["state"], "CLOSURE_BLOCKED")
        self.assertIn("decision_digest_mismatch", record["reasons"])

    def test_invalid_outcome_fails_closed(self) -> None:
        decision = copy.deepcopy(self.decision)
        decision["decision"] = "MAYBE"
        record = decision_closure.finalize_decision_closure(
            decision, self.review, self.reserved
        )
        self.assertEqual(record["state"], "CLOSURE_BLOCKED")
        self.assertIn("decision_outcome_invalid_or_ambiguous", record["reasons"])

    def test_failed_review_blocks_closure(self) -> None:
        review = copy.deepcopy(self.review)
        review["review_status"] = "FAIL"
        record = decision_closure.finalize_decision_closure(
            self.decision, review, self.reserved
        )
        self.assertFalse(record["closure_eligible"])
        self.assertIn("independent_review_not_pass", record["reasons"])

    def test_wrong_next_phase_blocks_closure(self) -> None:
        decision = copy.deepcopy(self.decision)
        decision["next_master_phase"] = "PHASE_4_AI_OFFICE"
        record = decision_closure.finalize_decision_closure(
            decision, self.review, self.reserved
        )
        self.assertFalse(record["closure_eligible"])
        self.assertIn("next_master_phase_mismatch", record["reasons"])


if __name__ == "__main__":
    unittest.main()
