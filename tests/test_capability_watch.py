from __future__ import annotations

import unittest

from tests.capability_lifecycle_fixtures import active_record

from runtime.orchestrator.capability_watch import (
    evaluate_capability_watch,
)


class CapabilityWatchTests(unittest.TestCase):

    def setUp(self) -> None:
        self.record = active_record()
        self.now = "2026-09-27T00:00:00+00:00"

    def test_watch_is_not_a_resident_or_every_call_network_scanner(self):
        decision = evaluate_capability_watch(
            records=(self.record,),
            capability_gaps=(),
            metrics=(),
            last_scan_at=self.now,
            now=self.now,
            scan_interval_seconds=86400,
        )

        self.assertFalse(decision.scan_due)
        self.assertEqual(decision.actions, ("NO_ACTION",))

    def test_degraded_overlap_only_recommends_replacement_review(self):
        decision = evaluate_capability_watch(
            records=(self.record,),
            capability_gaps=(),
            metrics=(
                {
                    "contract_id": self.record.contract.contract_id,
                    "health": "DEGRADED",
                    "overlap_candidate_ref": "candidate:2",
                },
            ),
            last_scan_at="2026-09-22T00:00:00+00:00",
            now=self.now,
            scan_interval_seconds=86400,
        )

        self.assertTrue(decision.scan_due)
        self.assertIn("REPLACEMENT_REVIEW", decision.actions)

        # Watch is recommendation-only.
        self.assertEqual(self.record.state, "ACTIVE")

    def test_due_capability_gap_recommends_search_only(self):
        decision = evaluate_capability_watch(
            records=(self.record,),
            capability_gaps=("document_analysis",),
            metrics=(),
            last_scan_at="2026-09-22T00:00:00+00:00",
            now=self.now,
            scan_interval_seconds=86400,
        )

        self.assertTrue(decision.scan_due)
        self.assertIn("SEARCH", decision.actions)

    def test_invalid_or_future_scan_timing_fails_closed(self):
        with self.assertRaises(ValueError):
            evaluate_capability_watch(
                records=(self.record,),
                capability_gaps=(),
                metrics=(),
                last_scan_at="2026-09-28T00:00:00+00:00",
                now=self.now,
                scan_interval_seconds=86400,
            )


if __name__ == "__main__":
    unittest.main()
