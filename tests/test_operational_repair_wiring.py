from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.monitor_health import (
    MonitorHealthError,
    load_attention_monitor_health,
    record_attention_monitor_health,
)
from runtime.orchestrator.operational_acceptance import (
    load_latest_acceptance,
    record_operational_acceptance,
)


class MonitorHealthTests(unittest.TestCase):
    def test_health_receipt_is_durable_and_stale_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            now = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
            with patch("runtime.orchestrator.monitor_health.discover_registered_jobs", return_value=[{"run_id":"R1"}]),                  patch("runtime.orchestrator.monitor_health.discover_pending_attention", return_value=[]):
                receipt = record_attention_monitor_health(
                    root, search_root=root, scanned_at=now.isoformat(timespec="seconds"),
                )
            self.assertEqual(receipt.status, "HEALTHY")
            path = root / "_workspace" / "operations-health" / "attention-monitor.json"
            loaded = load_attention_monitor_health(path, now=now + timedelta(seconds=60), stale_after_seconds=180)
            self.assertEqual(loaded.receipt_sha256, receipt.receipt_sha256)
            with self.assertRaisesRegex(MonitorHealthError, "stale"):
                load_attention_monitor_health(path, now=now + timedelta(seconds=181), stale_after_seconds=180)

    def test_current_attention_makes_health_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("runtime.orchestrator.monitor_health.discover_registered_jobs", return_value=[{"run_id":"R1"}]),                  patch("runtime.orchestrator.monitor_health.discover_pending_attention", return_value=[{
                     "event_id":"e"*64, "state":"RUNNING",
                 }]):
                receipt = record_attention_monitor_health(root, search_root=root)
            self.assertEqual(receipt.status, "BLOCKED")
            self.assertEqual(receipt.current_attention_count, 1)


class OperationalAcceptanceTests(unittest.TestCase):
    def test_completed_execution_can_remain_operationally_blocked_without_state_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job = {
                "project_id":"P", "run_id":"R", "authority_core_sha256":"a"*64,
                "gates":[{"gate_id":"G1"}], "harness_state_root":str(root),
            }
            state = {
                "state":"COMPLETED", "terminal_reason":"ALL_GATES_COMPLETED",
                "state_sha256":"s"*64,
            }
            gate = {
                "status":"PASS", "failures":[],
                "attention_monitor_health":{"receipt_sha256":"m"*64},
            }
            process = {"snapshot_sha256":"p"*64, "blocking_count":1}
            with patch("runtime.orchestrator.operational_acceptance.load_job", return_value=job),                  patch("runtime.orchestrator.operational_acceptance._state_for_job", return_value=state),                  patch("runtime.orchestrator.operational_acceptance.evaluate_post_change_gate", return_value=gate),                  patch("runtime.orchestrator.operational_acceptance.load_process_lifecycle_snapshot", return_value=process):
                record = record_operational_acceptance(root / "job.json", now=datetime.now(timezone.utc))
            self.assertEqual(record["execution_state"], "COMPLETED")
            self.assertEqual(record["status"], "BLOCKED")
            self.assertIn("PROCESS_LIFECYCLE_BLOCKED", record["failures"])
            latest = load_latest_acceptance(root, "P", "R")
            self.assertEqual(latest["record_sha256"], record["record_sha256"])

    def test_healthy_completed_execution_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job = {
                "project_id":"P", "run_id":"R", "authority_core_sha256":"a"*64,
                "gates":[{"gate_id":"G1"}], "harness_state_root":str(root),
            }
            state = {
                "state":"COMPLETED", "terminal_reason":"ALL_GATES_COMPLETED",
                "state_sha256":"s"*64,
            }
            gate = {
                "status":"PASS", "failures":[],
                "attention_monitor_health":{"receipt_sha256":"m"*64},
            }
            process = {"snapshot_sha256":"p"*64, "blocking_count":0}
            with patch("runtime.orchestrator.operational_acceptance.load_job", return_value=job),                  patch("runtime.orchestrator.operational_acceptance._state_for_job", return_value=state),                  patch("runtime.orchestrator.operational_acceptance.evaluate_post_change_gate", return_value=gate),                  patch("runtime.orchestrator.operational_acceptance.load_process_lifecycle_snapshot", return_value=process):
                record = record_operational_acceptance(root / "job.json", now=datetime.now(timezone.utc))
            self.assertEqual(record["status"], "ACCEPTED")
            self.assertEqual(record["failures"], [])


if __name__ == "__main__":
    unittest.main()
