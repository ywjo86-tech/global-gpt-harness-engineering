from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.audit_log import append_audit_event, read_recent_audit_events


class AuditLogTest(unittest.TestCase):
    def test_appends_and_reads_structured_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "audit.log"
            append_audit_event(log_path, "task", "created task", task_id="T1")
            append_audit_event(log_path, "gate", "stage gate", decision="GO")

            events = read_recent_audit_events(log_path)

            self.assertEqual(len(events), 2)
            self.assertEqual(events[-1]["event_type"], "gate")
            self.assertEqual(events[-1]["fields"]["decision"], "GO")


if __name__ == "__main__":
    unittest.main()
