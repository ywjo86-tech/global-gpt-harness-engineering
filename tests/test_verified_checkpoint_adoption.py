import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_approval import calculate_v2_record_hash
from runtime.orchestrator.verified_checkpoint_adoption import (
    ADOPTION_MODE,
    VerifiedCheckpointAdoptionError,
    build_verified_checkpoint_result,
    write_verified_checkpoint_result,
)


PLAN = "a" * 64
CONDITIONS = "b" * 64


class VerifiedCheckpointAdoptionTests(unittest.TestCase):
    def fixture(self, root: Path):
        project = root / "fixture-project"; project.mkdir()
        subprocess.run(["git", "init", "-q", project], check=True)
        subprocess.run(["git", "-C", project, "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", project, "config", "user.name", "Fixture"], check=True)
        (project / "app").mkdir(); (project / "tests").mkdir(); (project / ".venv/bin").mkdir(parents=True)
        (project / ".gitignore").write_text(".venv/\n")
        (project / "app/a.py").write_text("before\n"); (project / "tests/test_a.py").write_text("before\n")
        subprocess.run(["git", "-C", project, "add", ".gitignore", "app/a.py", "tests/test_a.py"], check=True)
        subprocess.run(["git", "-C", project, "commit", "-qm", "base"], check=True)
        (project / "app/a.py").write_text("after\n"); (project / "tests/test_a.py").write_text("after\n")
        subprocess.run(["git", "-C", project, "add", "app/a.py", "tests/test_a.py"], check=True)
        subprocess.run(["git", "-C", project, "commit", "-qm", "checkpoint"], check=True)
        checkpoint = subprocess.run(["git", "-C", project, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        (project / "docs").mkdir(); (project / "docs/gov.md").write_text("governance\n")
        subprocess.run(["git", "-C", project, "add", "docs/gov.md"], check=True)
        subprocess.run(["git", "-C", project, "commit", "-qm", "governance"], check=True)
        for name in ("python", "pytest"):
            path = project / ".venv/bin" / name; path.write_text(""); path.chmod(0o700)
        package = root / "package"; package.mkdir(); (package / "preflight").mkdir()
        event = {
            "schema_version": "orchestration.production-approval.v2", "event_id": "APR-G1-1",
            "event_type": "APPROVED", "project_id": "fixture-project", "gate_id": "G1", "plan_sha256": PLAN,
            "branch": "master", "baseline_head": checkpoint, "approved_at": "2026-01-01T00:00:00Z",
            "recorded_at": "2026-01-01T00:00:00Z", "approval_mode": "GATE_BY_GATE", "canonical_lv_scope": ["L1"],
            "owned_file_scope": {"L1": ["app/a.py", "tests/test_a.py"]}, "completion_conditions_sha256": CONDITIONS,
            "predecessor": None, "supersedes": None, "authorization_source": "USER_OWNER", "record_hash": "0" * 64,
        }
        event["record_hash"] = calculate_v2_record_hash(event)
        manifest = {
            "project_id": "fixture-project", "gate_id": "G1", "lv_id": "L1", "run_id": "run-1",
            "owned_files": ["app/a.py", "tests/test_a.py"], "canonical_plan_sha256": PLAN,
            "approval_record_hash": event["record_hash"], "completion_checks": ["tests pass"],
        }
        (package / "package.manifest.json").write_text(json.dumps(manifest))
        (package / "preflight/preflight.evidence.json").write_text("{}")
        approval = root / "approval.json"
        approval.write_text(json.dumps({"schema_version": "orchestration.production-approval-log.v2", "events": [event]}))
        return project, package, approval, checkpoint

    @staticmethod
    def command(_root, argv):
        return {"command": argv, "exit_code": 0, "timeout": False, "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64}

    def test_builds_exact_scope_checkpoint_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            project, package, approval, checkpoint = self.fixture(Path(directory))
            with patch("runtime.orchestrator.verified_checkpoint_adoption._command", self.command):
                result = build_verified_checkpoint_result(project_root=project, package_root=package,
                                                          approval_log=approval, approval_event_id="APR-G1-1")
            self.assertEqual(result["completion_mode"], ADOPTION_MODE)
            self.assertEqual(result["checkpoint_commit"], checkpoint)
            self.assertEqual(result["changed_files"], ["app/a.py", "tests/test_a.py"])
            self.assertEqual(result["adoption"]["worker_provenance"], "NOT_APPLICABLE_CHECKPOINT_ADOPTION")

    def test_rejects_owned_file_change_after_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            project, package, approval, _ = self.fixture(Path(directory))
            (project / "app/a.py").write_text("later\n")
            subprocess.run(["git", "-C", project, "add", "app/a.py"], check=True)
            subprocess.run(["git", "-C", project, "commit", "-qm", "owned drift"], check=True)
            with self.assertRaisesRegex(VerifiedCheckpointAdoptionError, "owned files changed"):
                build_verified_checkpoint_result(project_root=project, package_root=package,
                                                 approval_log=approval, approval_event_id="APR-G1-1")

    def test_writes_private_sealed_result_once(self):
        with tempfile.TemporaryDirectory() as directory:
            project, package, approval, _ = self.fixture(Path(directory))
            with patch("runtime.orchestrator.verified_checkpoint_adoption._command", self.command):
                written = write_verified_checkpoint_result(project_root=project, package_root=package,
                                                           approval_log=approval, approval_event_id="APR-G1-1")
            target = package / "worker.result.json"
            self.assertEqual(written["status"], "WRITTEN")
            self.assertTrue(target.is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(VerifiedCheckpointAdoptionError, "already exists"):
                write_verified_checkpoint_result(project_root=project, package_root=package,
                                                 approval_log=approval, approval_event_id="APR-G1-1")


if __name__ == "__main__":
    unittest.main()
