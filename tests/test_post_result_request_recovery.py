from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.recovery_contract import (
    RecoveryError,
    prepare_post_result_missing_request_recovery,
    verify_post_result_checkpoint_recovery,
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class PostResultRequestRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test"], check=True)
        (self.project / "owned.py").write_text("VALUE = 1\n")
        (self.project / "outside.py").write_text("OUTSIDE = 1\n")
        (self.project / "test_smoke.py").write_text(
            "import unittest\nclass Smoke(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n"
        )
        (self.project / ".gitignore").write_text("__pycache__/\n*.pyc\n")
        subprocess.run(["git", "-C", str(self.project), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "baseline"], check=True)
        self.baseline = self.git("rev-parse", "HEAD")
        self.baseline_tree = self.git("rev-parse", "HEAD^{tree}")
        (self.project / "owned.py").write_text("VALUE = 2\n")
        subprocess.run(["git", "-C", str(self.project), "add", "owned.py"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "task"], check=True)
        self.checkpoint = self.git("rev-parse", "HEAD")
        (self.project / "outside.py").write_text("OUTSIDE = 2\n")
        subprocess.run(["git", "-C", str(self.project), "add", "outside.py"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "later outside scope"], check=True)
        self.current = self.git("rev-parse", "HEAD")
        self.package = self.root / "_workspace" / "orchestration-runs" / "r" / "TASK-013"
        (self.package / "preflight").mkdir(parents=True)
        self.plan_sha = "a" * 64
        self.manifest = {
            "project_id":"P", "gate_id":"G", "lv_id":"TASK-013", "run_id":"r",
            "canonical_plan_sha256":self.plan_sha, "approval_id":"APR",
            "approval_record_hash":"b" * 64, "source_head":self.baseline,
            "owned_files":["owned.py"],
        }
        self.manifest_path = self.package / "package.manifest.json"
        self.manifest_path.write_bytes(canonical(self.manifest))
        package_sha = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()
        self.manifest_path.with_suffix(".sha256").write_text(package_sha + "\n")
        self.preflight_path = self.package / "preflight" / "preflight.evidence.json"
        self.preflight = {"project_id":"P", "gate_id":"G", "lv_id":"TASK-013", "run_id":"r",
                          "package_manifest_sha256":package_sha}
        self.preflight_path.write_bytes(canonical(self.preflight))
        preflight_sha = hashlib.sha256(self.preflight_path.read_bytes()).hexdigest()
        self.preflight_path.with_suffix(".sha256").write_text(preflight_sha + "\n")
        py = sys.executable
        commands = {
            "focused_test":{"command":[py,"-m","unittest","-q","test_smoke"]},
            "full_regression":{"command":[py,"-m","unittest","-q","test_smoke"]},
            "compile_import":{"command":[py,"-m","compileall","-q","."]},
            "git_diff_check":{"command":["git","diff","--check"]},
        }
        self.worker = {
            "project_id":"P", "gate_id":"G", "lv_id":"TASK-013", "run_id":"r",
            "plan_sha256":self.plan_sha, "status":"completed", "completion_mode":"GPT_OPERATOR_MANUAL_ACTION",
            "hard_stop":True, "attempt":1, "preflight_evidence_sha256":preflight_sha,
            "checkpoint_commit":self.checkpoint, "baseline_head":self.baseline,
            "baseline_tree":self.baseline_tree, "changed_files":["owned.py"], "tests":["TEST-X"],
            "commands":commands,
        }
        self.worker_path = self.package / "worker.result.json"
        self.worker_path.write_bytes(canonical(self.worker))
        worker_sha = hashlib.sha256(self.worker_path.read_bytes()).hexdigest()
        self.review_path = self.package / "production.review-request-01.json"
        self.review = {"project_id":"P", "gate_id":"G", "lv_id":"TASK-013", "run_id":"r",
                       "package_manifest_sha256":package_sha, "worker_result_sha256":worker_sha,
                       "canonical_plan_sha256":self.plan_sha}
        self.review_path.write_bytes(canonical(self.review))

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True, check=True).stdout.strip()

    def prepare(self):
        return prepare_post_result_missing_request_recovery(
            self.root, project_root=self.project, package_manifest_path=self.manifest_path,
            preflight_path=self.preflight_path, worker_result_path=self.worker_path,
            review_request_path=self.review_path, approval_event_id="APR", branch="feature/recovery")

    def test_missing_request_is_rejected_then_checkpoint_is_verification_only_adoptable(self):
        recovery = self.prepare()
        self.assertEqual(recovery["classification"]["status"], "REJECTED_POST_RESULT_REQUEST_MISSING")
        self.assertEqual(recovery["next_attempt"], 2)
        self.assertFalse((self.package / "worker.request.json").exists())
        verified = verify_post_result_checkpoint_recovery(
            project_root=self.project, source_worker_path=self.worker_path,
            package_manifest_path=self.manifest_path)
        self.assertEqual(verified["completion_mode"], "VERIFIED_CHECKPOINT_ADOPTION")
        self.assertEqual(verified["checkpoint_commit"], self.checkpoint)
        self.assertEqual(verified["current_head"], self.current)
        self.assertEqual(verified["changed_files"], ["owned.py"])
        self.assertEqual(verified["commands"]["git_diff_check"]["exit_code"], 0)

    def test_existing_request_blocks_post_result_recovery(self):
        (self.package / "worker.request.json").write_text("{}")
        with self.assertRaisesRegex(RecoveryError, "requires the original worker request to be absent"):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
