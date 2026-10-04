from datetime import datetime, timezone
import unittest

from pathlib import Path
import tempfile

from runtime.diagnostics.process_lifecycle import collect_process_ownership_facts, diagnose_process_lifecycle


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
