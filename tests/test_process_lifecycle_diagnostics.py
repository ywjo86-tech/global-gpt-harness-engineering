from datetime import datetime, timezone
import unittest

from pathlib import Path
import tempfile

from runtime.diagnostics.process_lifecycle import (
    collect_process_ownership_facts, diagnose_process_lifecycle,
    discover_managed_process_lifecycle,
)


class ProcessLifecycleDiagnosticTests(unittest.TestCase):
    def test_missing_owner_state_marks_orphan_suspected_without_cleanup_method(self):
        diagnostic = diagnose_process_lifecycle({
            "pid": 550360,
            "owner_ref": "run:DCC_LIVE_AUTO_CANARY",
            "owner_state_exists": False,
            "lock_exists": False,
            "expected_lifecycle_state": "PAUSED_TEST",
            "last_semantic_progress": "2026-09-23T00:00:00+00:00",
        }, now=datetime(2026, 9, 24, tzinfo=timezone.utc))
        self.assertEqual(diagnostic.status, "ORPHAN_SUSPECTED")
        self.assertTrue(diagnostic.cleanup_authorization_required)
        self.assertFalse(hasattr(diagnostic, "kill"))

    def test_bounded_listener_lifetime_is_orphan_suspected(self):
        diagnostic = diagnose_process_lifecycle({
            "pid": 42,
            "owner_ref": "ledger:proof",
            "owner_state_exists": True,
            "lock_exists": True,
            "expected_lifecycle_state": "HOST_GATEWAY_LISTENER",
            "age_seconds": 1861,
            "max_lifetime_seconds": 1860,
            "process_kind": "HOST_GATEWAY",
        }, now=datetime(2026, 10, 4, tzinfo=timezone.utc))
        self.assertEqual(diagnostic.status, "ORPHAN_SUSPECTED")
        self.assertEqual(diagnostic.orphan_suspicion_reason, "process exceeded bounded lifetime")

    def test_proc_discovery_classifies_missing_full_plan_owner(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            proc = Path(td)
            (proc/"101").mkdir()
            with patch(
                "runtime.diagnostics.process_lifecycle._proc_observation",
                return_value=(
                    ["python3","-m","runtime.orchestrator.production_full_plan_entry",
                     "--job",str(proc/"missing.job.json")],
                    1, 1000.0,
                ),
            ):
                rows = discover_managed_process_lifecycle(
                    proc_root=proc, now=datetime(2026,10,4,tzinfo=timezone.utc),
                )
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].process_kind,"FULL_PLAN")
        self.assertEqual(rows[0].status,"ORPHAN_SUSPECTED")

    def test_read_only_ownership_fact_collector_wires_to_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            facts = collect_process_ownership_facts(
                pid=38602,
                owner_ref="run:proof-host-gateway",
                owner_state_path=root / "missing-state.json",
                lock_path=root / "missing.lock",
                expected_lifecycle_state="IDLE",
            )
        self.assertEqual(facts["collection_mode"], "READ_ONLY")
        diagnostic = diagnose_process_lifecycle(facts, now=datetime(2026, 9, 24, tzinfo=timezone.utc))
        self.assertEqual(diagnostic.status, "ORPHAN_SUSPECTED")


if __name__ == "__main__":
    unittest.main()
