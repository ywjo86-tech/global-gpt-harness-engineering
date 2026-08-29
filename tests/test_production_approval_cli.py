from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.cli import main
from runtime.orchestrator.production_approval import ProductionApprovalError, load_v2_event_log, write_production_approval


SHA = "a" * 64


def run(*args, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


class ProductionApprovalWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "generic-project"
        self.root.mkdir()
        run("init", "-b", "main", cwd=self.root)
        run("config", "user.email", "fixture@example.invalid", cwd=self.root)
        run("config", "user.name", "Fixture", cwd=self.root)
        (self.root / "plan.md").write_text("plan\n", encoding="utf-8")
        run("add", "plan.md", cwd=self.root); run("commit", "-m", "baseline", cwd=self.root)
        self.scope = {
            "canonical_lv_scope": ["G1-LV3-1"],
            "owned_file_scope": {"G1-LV3-1": ["app/a.py"]},
            "completion_conditions_sha256": "c" * 64,
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, **changes):
        values = dict(
            project_root=self.root, output_path="approval-v2.json", gate_id="GATE-1",
            plan_sha256=SHA, approval_mode="GATE_BY_GATE", authorization_source="USER_OWNER",
            **self.scope,
        )
        values.update(changes)
        return write_production_approval(**values)

    def test_new_and_correction_writer_use_git_and_real_utc_clock(self):
        first = self.write()
        self.assertEqual(first["status"], "WRITTEN")
        event = load_v2_event_log(self.root / "approval-v2.json")[0]
        self.assertEqual(event["branch"], "main")
        self.assertEqual(event["baseline_head"], run("rev-parse", "HEAD", cwd=self.root))
        self.assertTrue(event["recorded_at"].endswith("Z"))
        second = self.write(correction_of=event["event_id"])
        chain = load_v2_event_log(self.root / "approval-v2.json")
        self.assertEqual(second["event"]["event_type"], "CORRECTION")
        self.assertEqual(chain[1]["predecessor"], chain[0]["record_hash"])

    def test_dry_run_and_read_only_do_not_write(self):
        for flag in ({"dry_run": True}, {"read_only": True}):
            with self.subTest(flag=flag):
                result = self.write(**flag)
                self.assertFalse(result["mutation_performed"])
                self.assertFalse((self.root / "approval-v2.json").exists())

    def test_dirty_and_detached_git_are_blocked(self):
        (self.root / "dirty.txt").write_text("dirty", encoding="utf-8")
        with self.assertRaisesRegex(ProductionApprovalError, "clean"):
            self.write()
        (self.root / "dirty.txt").unlink()
        run("checkout", "--detach", cwd=self.root)
        with self.assertRaisesRegex(ProductionApprovalError, "attached"):
            self.write()

    def test_atomic_write_rollback_preserves_existing_log(self):
        self.write()
        path = self.root / "approval-v2.json"
        before = path.read_bytes()
        target = load_v2_event_log(path)[0]["event_id"]
        with patch("runtime.orchestrator.production_approval.os.replace", side_effect=OSError("fixture replace failure")):
            with self.assertRaises(OSError):
                self.write(correction_of=target)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(any(item.name.startswith(".approval-v2.json.") for item in self.root.iterdir()))

    def test_cli_create_and_read_only(self):
        scope_file = self.root / "scope.json"
        scope_file.write_text(json.dumps(self.scope), encoding="utf-8")
        run("add", "scope.json", cwd=self.root); run("commit", "-m", "scope", cwd=self.root)
        argv = ["production-approval-create", "--project-root", str(self.root), "--output", "approval-v2.json",
                "--gate-id", "GATE-1", "--plan-sha256", SHA, "--scope-file", str(scope_file),
                "--authorization-source", "USER_OWNER", "--read-only"]
        self.assertEqual(main(argv), 0)
        self.assertFalse((self.root / "approval-v2.json").exists())

    def test_cross_project_traversal_symlink_and_secret_are_blocked_without_echo(self):
        outside = Path(self.temp.name) / "outside.json"
        with self.assertRaisesRegex(ProductionApprovalError, "escapes"):
            self.write(output_path=outside)
        link = self.root / "approval-v2.json"; link.symlink_to(outside)
        with self.assertRaisesRegex(ProductionApprovalError, "unsafe"):
            self.write()
        link.unlink()
        secret = "token=sk-abcdefghijklmnopqrstuvwxyz"
        with self.assertRaises(ProductionApprovalError) as caught:
            self.write(authorization_source=secret)
        self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
