from __future__ import annotations

import unittest

from gui.orchestration_panel import build_orchestration_lines


class OrchestrationPanelTests(unittest.TestCase):
    def test_empty_summary_uses_safe_defaults(self) -> None:
        lines = build_orchestration_lines(None)

        self.assertEqual(lines[0], "Bridge: DISCONNECTED")
        self.assertIn("Project: none", lines[1])
        self.assertIn("Run ID: none", lines[2])
        self.assertIn("Active Workers: 0", lines[8])
        self.assertIn("- none", lines)

    def test_populated_summary_formats_key_sections(self) -> None:
        lines = build_orchestration_lines(
            {
                "connected": True,
                "project_name": "jarvis-assistant",
                "run_id": "run-001",
                "current_phase": "gate-8-b",
                "next_step": "stage safe slice",
                "fanout_status": "ready",
                "fanin_status": "idle",
                "collection_status": "ready",
                "stage_gate_result": {"status": "GO"},
                "approval_required": True,
                "pending_approvals": [
                    {"thread_id": "t-1", "assigned_agent": "worker-a", "approval_classification": "safe"}
                ],
                "active_workers": [
                    {"thread_id": "t-2", "assigned_agent": "worker-b", "status": "running"}
                ],
                "recent_logs": ["line-1", "line-2"],
            }
        )

        self.assertEqual(lines[0], "Bridge: CONNECTED")
        self.assertIn("Project: jarvis-assistant", lines[1])
        self.assertIn("Run ID: run-001", lines[2])
        self.assertIn("Current Phase: gate-8-b", lines[3])
        self.assertIn("Next Step: stage safe slice", lines[4])
        self.assertIn("Fan-out: ready | Fan-in: idle", lines[5])
        self.assertIn("Collection: ready | Stage Gate: GO", lines[6])
        self.assertIn("Approvals Required: YES | Pending: 1", lines[7])
        self.assertIn("Active Workers: 1 | Recent Logs: 2", lines[8])
        self.assertIn("- t-2 | worker-b | running", lines)
        self.assertIn("- t-1 | worker-a | safe", lines)
        self.assertTrue(lines[-1].endswith("line-2"))


if __name__ == "__main__":
    unittest.main()
