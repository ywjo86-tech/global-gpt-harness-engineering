from __future__ import annotations

import unittest

from runtime.orchestrator.summary_rendering import render_fanin_markdown, render_stage_gate_markdown
from runtime.orchestrator.schemas import FanInReport


class SummaryRenderingTest(unittest.TestCase):
    def test_render_fanin_markdown_uses_standard_headings(self) -> None:
        report = FanInReport(
            threads_received=["T1"],
            completed_outputs=["T1"],
            missing_outputs=[],
            failed_workers=[],
            conflicts=[],
            duplicate_work=[],
            requirement_coverage="complete",
            risk_summary=[],
            qa_required=False,
            next_step_decision="request stage gate review",
            final_handoff_readiness="ready",
        )

        markdown = render_fanin_markdown(report)

        self.assertIn("# Fan-In Summary", markdown)
        self.assertIn("## Snapshot", markdown)
        self.assertIn("## Conflicts", markdown)
        self.assertIn("## Risk Summary", markdown)

    def test_render_stage_gate_markdown_uses_standard_headings(self) -> None:
        markdown = render_stage_gate_markdown(
            {
                "decision": "GO",
                "phase": "phase-1",
                "completion_criteria_checked": "yes",
                "fan_in_reviewed": "yes",
                "evidence_reviewed": ["docs", "logs"],
                "conditions": [],
                "open_questions": [],
                "remaining_risks": [],
                "next_step": "phase-2",
                "authorization": "next phase may start",
                "blocker_summary": "",
            }
        )

        self.assertIn("# Stage Gate Summary", markdown)
        self.assertIn("## Decision", markdown)
        self.assertIn("## Evidence Reviewed", markdown)
        self.assertIn("## Remaining Risks", markdown)


if __name__ == "__main__":
    unittest.main()
