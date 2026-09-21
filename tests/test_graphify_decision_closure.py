from __future__ import annotations

import copy
import unittest

from poc.graphify import decision_closure
from tests.graphify_test_fixture import (
    independent_review,
    open_decision,
    reserved_phase_isolation,
)


class GraphifyDecisionClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision = open_decision()
        self.review = independent_review()
        self.reserved = reserved_phase_isolation()

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
