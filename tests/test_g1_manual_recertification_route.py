"""Regression: a reverted approved baseline must not shadow a valid manual Router."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import (
    GateControllerError, _pending_authorized_manual_patch_needs_execution,
)


class G1ManualRecertificationRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "-C", str(self.repo), "init", "-b", "main"], capture_output=True, check=True)
        (self.repo / "canary.txt").write_text("baseline\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "canary.txt"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test",
                        "-c", "user.email=tests@localhost.invalid", "commit", "-m", "baseline"],
                       capture_output=True, check=True)
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.plan = SimpleNamespace(project_id="CANARY",gate_id="GATE-001",canonical_plan_sha256="1"*64)
        self.selected_lv=SimpleNamespace(owned_files=["canary.txt"])
        self.action = {"source_head":self.head,
                       "patch":"diff --git a/canary.txt b/canary.txt\n"
                       "--- a/canary.txt\n+++ b/canary.txt\n@@ -1 +1 @@\n-baseline\n+done\n"}
        self.authorization = {"approved":"specific-action"}
    def check(self, **overrides):
        kw = {"lv_id":"TASK-001","lv_run_id":"RUN-GATE-001",
              "approved_head":self.head,"manual_package":self.action,
              "manual_authorization":self.authorization}
        kw.update(overrides)
        return _pending_authorized_manual_patch_needs_execution(
            self.repo,self.plan,self.selected_lv,**kw)
    def test_applicable_owner_bound_patch_uses_router_without_mutating(self):
        with patch("runtime.orchestrator.production_manual_action.validate_action_package") as validator:
            self.assertTrue(self.check())
            validator.assert_called_once()
        self.assertEqual((self.repo/"canary.txt").read_text(),"baseline\n")
        self.assertEqual(subprocess.run(["git","-C",str(self.repo),"status","--porcelain","-uall"],
             capture_output=True,text=True,check=True).stdout.strip(),"")
    def test_stale_source_rejected(self):
        with self.assertRaisesRegex(GateControllerError,"exact approved"):
            self.check(approved_head="0"*40)
    def test_modified_authorization_rejected(self):
        with patch("runtime.orchestrator.production_manual_action.validate_action_package",
                   side_effect=ValueError("invalid owner authorization")):
            with self.assertRaisesRegex(GateControllerError,"invalid owner authorization"):
                self.check()
    def test_already_applied_patch_cannot_be_redone(self):
        (self.repo/"canary.txt").write_text("done\n")
        subprocess.run(["git","-C",str(self.repo),"add","canary.txt"],check=True,capture_output=True)
        subprocess.run(["git","-C",str(self.repo),"-c","user.name=Test",
                        "-c","user.email=tests@localhost.invalid","commit","-m","completed"],
                       capture_output=True,check=True)
        head=subprocess.run(["git","-C",str(self.repo),"rev-parse","HEAD"],
                            capture_output=True,text=True,check=True).stdout.strip()
        action={**self.action,"source_head":head}
        with patch("runtime.orchestrator.production_manual_action.validate_action_package"):
            self.assertFalse(self.check(approved_head=head,manual_package=action))
    def test_dirty_worktree_rejected(self):
        (self.repo/"untracked.txt").write_text("no")
        with self.assertRaisesRegex(GateControllerError,"clean"):
            self.check()
