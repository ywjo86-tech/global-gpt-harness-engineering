from datetime import datetime, timezone
import unittest

from runtime.diagnostics.process_lifecycle import diagnose_process_lifecycle


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


if __name__ == "__main__":
    unittest.main()
