from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.graphify import baseline_guard

BASELINE_REF = "958d335c2d85dfbbe4ed5a45bf6d78f14bdc9c37"


class GraphifyBaselineGuardTests(unittest.TestCase):
    def _verify_baseline_snapshot(self, *, requested_change_paths=()):
        source_root = Path(__file__).resolve().parents[1]
        blobs = {}
        for relative_path in baseline_guard.PROTECTED_PATHS:
            blobs[relative_path] = subprocess.check_output(
                ["git", "show", f"{BASELINE_REF}:{relative_path}"], cwd=source_root
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative_path, data in blobs.items():
                target = root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            with patch.object(baseline_guard, "_git_commit_exists", return_value=True), \
                 patch.object(baseline_guard, "_git_blob", side_effect=lambda _root, _ref, path: blobs.get(path)):
                return baseline_guard.verify_controlled_baseline(
                    root, BASELINE_REF, requested_change_paths=requested_change_paths
                )

    def test_baseline_snapshot_guard_is_clear(self) -> None:
        record = self._verify_baseline_snapshot()
        self.assertEqual(record["guard_status"], "CLEAR")
        self.assertEqual(record["verification_status"], "VERIFIED")
        self.assertTrue(record["entry_eligible"])
        self.assertFalse(record["controlled_change_required"])
        self.assertEqual(record["reasons"], [])
        self.assertEqual(len(record["verified_hashes"]), len(baseline_guard.PROTECTED_PATHS))

    def test_requested_core_change_requires_external_controlled_change(self) -> None:
        record = self._verify_baseline_snapshot(
            requested_change_paths=["runtime/orchestrator/stage_gate.py"]
        )
        self.assertEqual(record["guard_status"], "CONTROLLED_CHANGE_REQUIRED")
        self.assertFalse(record["entry_eligible"])
        self.assertTrue(record["controlled_change_required"])
        self.assertEqual(
            record["escalation_record"]["required_external_sequence"],
            list(baseline_guard.CONTROLLED_CHANGE_SEQUENCE),
        )
        self.assertFalse(record["escalation_record"]["phase2_can_execute_change"])

    def test_poc_only_change_request_remains_clear(self) -> None:
        record = self._verify_baseline_snapshot(
            requested_change_paths=["poc/graphify/graphify_adapter.py"]
        )
        self.assertEqual(record["guard_status"], "CLEAR")
        self.assertTrue(record["entry_eligible"])
        self.assertEqual(record["requested_protected_paths"], [])

    def test_expected_absent_hook_presence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hook = root / ".codex" / "hooks.json"
            hook.parent.mkdir(parents=True)
            hook.write_text("{}\n", encoding="utf-8")
            with patch.object(baseline_guard, "_git_commit_exists", return_value=True):
                record = baseline_guard.verify_controlled_baseline(
                    root,
                    BASELINE_REF,
                    protected_paths=(),
                    expected_absent_paths=(".codex/hooks.json",),
                )
            self.assertEqual(record["guard_status"], "CONTROLLED_CHANGE_REQUIRED")
            self.assertFalse(record["entry_eligible"])
            self.assertIn(
                "expected_absent_path_present:.codex/hooks.json",
                record["reasons"],
            )

    def test_missing_baseline_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            record = baseline_guard.verify_controlled_baseline(
                temp_dir,
                "1" * 40,
                protected_paths=(),
                expected_absent_paths=(),
            )

        self.assertEqual(record["guard_status"], "GUARD_FAILED_CLOSED")
        self.assertFalse(record["entry_eligible"])
        self.assertFalse(record["controlled_change_required"])
        self.assertIn("baseline_git_commit_missing", record["reasons"])


if __name__ == "__main__":
    unittest.main()
