from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "harness"


class Orch04DispositionConsistencyTests(unittest.TestCase):
    def test_latest_deferred_issues_match_authority_record_and_current_document_sections(self):
        disposition = json.loads(
            (DOCS / "ORCH04_AUTHORITY_DISPOSITION_20260912.json").read_text(encoding="utf-8")
        )
        expected = {
            issue_id
            for issue_id, state in disposition["issue_dispositions"].items()
            if state == "DEFERRED"
        }
        self.assertEqual(
            expected,
            {
                "ISSUE-056", "ISSUE-059", "ISSUE-063", "ISSUE-064",
                "ISSUE-066", "ISSUE-067", "ISSUE-069", "ISSUE-071",
            },
        )

        index = (DOCS / "ORCH04_REMAINING_ISSUE_EVIDENCE_INDEX.md").read_text(encoding="utf-8")
        for issue_id in expected:
            self.assertIn(f"| `{issue_id}` |", index)
            row = next(line for line in index.splitlines() if f"| `{issue_id}` |" in line)
            self.assertIn("`DEFERRED`", row)

        for document_name in (
            "orchestration-state.md",
            "ORCH04_HANDOFF_READINESS_ADDENDUM.md",
        ):
            document = (DOCS / document_name).read_text(encoding="utf-8")
            latest = document.split("## Latest Disposition Supersession — 2026-09-12", 1)[1]
            for issue_id in expected:
                self.assertIn(issue_id, latest)

    def test_historical_sections_are_labeled_and_do_not_claim_current_status(self):
        state = (DOCS / "orchestration-state.md").read_text(encoding="utf-8")
        addendum = (DOCS / "ORCH04_HANDOFF_READINESS_ADDENDUM.md").read_text(encoding="utf-8")
        self.assertIn("## Historical Issue Triage and Handoff Readiness — 2026-09-11", state)
        self.assertIn("## Historical Closure Classification — 2026-09-11", addendum)
        self.assertIn("## Latest Disposition Supersession — 2026-09-12", state)
        self.assertIn("## Latest Disposition Supersession — 2026-09-12", addendum)


if __name__ == "__main__":
    unittest.main()
