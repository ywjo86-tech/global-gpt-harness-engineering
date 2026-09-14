from __future__ import annotations

import unittest

from poc.graphify.source_precedence import verify_source_precedence


class SourcePrecedenceTests(unittest.TestCase):
    def test_current_repository_wins_conflict(self) -> None:
        record = verify_source_precedence(
            current_repository_fact="A",
            approved_baseline_fact="B",
            lower_priority_fixtures=["C", "D"],
        )
        self.assertTrue(record["verified"])
        self.assertEqual(record["authoritative_source"], "CURRENT_REPOSITORY")
        self.assertEqual(record["authoritative_value"], "A")
        self.assertFalse(record["lower_priority_override_applied"])

    def test_baseline_used_when_current_fact_absent(self) -> None:
        record = verify_source_precedence(
            current_repository_fact=None,
            approved_baseline_fact="BASELINE",
            lower_priority_fixtures=["MEMORY"],
        )
        self.assertEqual(record["authoritative_source"], "APPROVED_BASELINE")
        self.assertEqual(record["authoritative_value"], "BASELINE")


if __name__ == "__main__":
    unittest.main()
