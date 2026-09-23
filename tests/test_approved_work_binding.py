from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.approved_work_binding import (
    ApprovedWorkBindingError,
    resolve_committed_project_file,
    validate_approved_work_binding,
)
from runtime.orchestrator.gate_orchestrator import REQUIREMENT_IDS
from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.runtime_release import RuntimeReleaseManifest


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


class ApprovedWorkBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.root = self.base / "project"; self.root.mkdir()
        self.plan = self.root / "IMPLEMENTATION_PLAN.md"
        self.spec = self.root / "SPEC.md"
        self.plan.write_text("# Plan\n\n### Task G1: first\n\n### Task G2: second\n", encoding="utf-8")
        self.spec.write_text("# Spec\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "baseline"], cwd=self.root, check=True, capture_output=True)
        self.requirement = self.root / "requirements.json"
        self._write_requirement()
        subprocess.run(["git", "add", "requirements.json"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "requirements"], cwd=self.root, check=True, capture_output=True)
        self.mapping_root = self.base / "mapping"
        self.registry = OnboardingRegistry(self.mapping_root / "aliases")
        self.assertEqual(self.registry.register(self.root, "demo")["status"], "REGISTERED")
        self.runtime_root = self.base / "runtime-release"; self.runtime_root.mkdir()
        self.release = RuntimeReleaseManifest(
            schema_version="gch.runtime-release.v2", source_head="a"*40, source_tree="b"*40,
            release_path=str(self.runtime_root), runtime_entry="runtime/orchestrator/production_full_plan_boot.py",
            runtime_entry_sha256="c"*64, manifest_sha256="d"*64, publication_head="a"*40,
        )

    def tearDown(self): self.tmp.cleanup()

    def _write_requirement(self, *, malformed=False):
        if malformed:
            self.requirement.write_text("{bad", encoding="utf-8"); return
        payload = {
            "schema_version": "orchestration.requirement-evidence.v1",
            "requirements_sha256": sha(self.plan),
            "evidence": {rid: {} for rid in REQUIREMENT_IDS},
        }
        self.requirement.write_text(json.dumps(payload), encoding="utf-8")

    def request(self, **changes):
        value = {
            "schema_version": "orchestration.approved-work-activation-request.v1",
            "activation_request_id": "ACT-1", "project_alias": "demo",
            "approved_plan_path": "IMPLEMENTATION_PLAN.md", "approved_plan_sha256": sha(self.plan),
            "approved_spec_path": "SPEC.md", "approved_spec_sha256": sha(self.spec),
            "requirement_artifact_path": "requirements.json",
            "requirement_artifact_sha256": sha(self.requirement) if self.requirement.exists() else "0"*64,
            "approval_ref": "USER-APPROVAL-20260923", "expected_branch": "main",
            "expected_head": git(self.root, "rev-parse", "HEAD"), "task_ids": ["G1", "G2"],
            "runtime_release_digest": self.release.manifest_sha256,
        }
        value.update(changes); return value

    def validate(self, request=None):
        return validate_approved_work_binding(request or self.request(), registry=self.registry, runtime_release=self.release)

    def test_public_committed_file_helper_preserves_v1_rejections(self):
        resolved, relative = resolve_committed_project_file(self.root, "IMPLEMENTATION_PLAN.md", "approved plan")
        self.assertEqual(resolved, self.plan.resolve())
        self.assertEqual(relative, "IMPLEMENTATION_PLAN.md")
        untracked = self.root / "untracked.md"; untracked.write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(ApprovedWorkBindingError, "COMMITTED_EVIDENCE_REQUIRED"):
            resolve_committed_project_file(self.root, "untracked.md", "untracked")

    def test_valid_binding_derives_project_and_exact_committed_evidence(self):
        binding = self.validate()
        self.assertEqual(binding.project_id, "project")
        self.assertEqual(binding.approved_plan_sha256, sha(self.plan))
        self.assertEqual(binding.expected_head, git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(binding.task_ids, ("G1", "G2"))
        self.assertEqual(binding.runtime_code_root, str(self.runtime_root))
        self.assertEqual(len(binding.binding_digest), 64)

    def test_unknown_alias_and_missing_approval_fail_closed(self):
        with self.assertRaisesRegex(ApprovedWorkBindingError, "PROJECT_NOT_REGISTERED"):
            self.validate(self.request(project_alias="missing"))
        with self.assertRaisesRegex(ApprovedWorkBindingError, "APPROVED_BINDING_REQUIRED"):
            self.validate(self.request(approval_ref=""))

    def test_branch_head_and_digest_drift_fail_before_binding(self):
        with self.assertRaisesRegex(ApprovedWorkBindingError, "SOURCE_BINDING_MISMATCH"):
            self.validate(self.request(expected_branch="other"))
        with self.assertRaisesRegex(ApprovedWorkBindingError, "SOURCE_BINDING_MISMATCH"):
            self.validate(self.request(expected_head="0"*40))
        with self.assertRaisesRegex(ApprovedWorkBindingError, "EVIDENCE_DIGEST_MISMATCH"):
            self.validate(self.request(approved_spec_sha256="0"*64))
        with self.assertRaisesRegex(ApprovedWorkBindingError, "RUNTIME_RELEASE_MISMATCH"):
            self.validate(self.request(runtime_release_digest="0"*64))

    def test_uncommitted_dirty_or_symlink_plan_and_spec_fail_closed(self):
        self.plan.write_text(self.plan.read_text() + "dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(ApprovedWorkBindingError, "COMMITTED_EVIDENCE_REQUIRED"):
            self.validate(self.request(approved_plan_sha256=sha(self.plan)))
        subprocess.run(["git", "restore", "IMPLEMENTATION_PLAN.md"], cwd=self.root, check=True)
        self.spec.unlink(); self.spec.symlink_to(self.plan.name)
        with self.assertRaisesRegex(ApprovedWorkBindingError, "COMMITTED_EVIDENCE_REQUIRED"):
            self.validate(self.request(approved_spec_sha256=sha(self.plan)))

    def test_malformed_or_missing_requirement_artifact_is_never_synthesized(self):
        self._write_requirement(malformed=True)
        with self.assertRaisesRegex(ApprovedWorkBindingError, "APPROVED_BINDING_REQUIRED"):
            self.validate(self.request(requirement_artifact_sha256=sha(self.requirement)))
        self.requirement.unlink()
        with self.assertRaisesRegex(ApprovedWorkBindingError, "APPROVED_BINDING_REQUIRED"):
            self.validate(self.request(requirement_artifact_sha256="0"*64))

    def test_requested_tasks_must_come_from_committed_approved_plan(self):
        with self.assertRaisesRegex(ApprovedWorkBindingError, "TASK_NOT_APPROVED"):
            self.validate(self.request(task_ids=["G1", "G3"]))

    def test_unknown_or_authority_bearing_fields_are_rejected(self):
        for field in ("provider", "model", "backend", "editable_scope", "command", "argv", "environment"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ApprovedWorkBindingError, "REQUEST_FIELDS_MISMATCH"):
                    self.validate({**self.request(), field: "forbidden"})

    def test_validator_has_no_registration_or_network_side_effect(self):
        import inspect, runtime.orchestrator.approved_work_binding as module
        source = inspect.getsource(module)
        for forbidden in ("register_job(", "AIOfficeStateStore", "requests.", "urllib", "socket", "Popen"):
            with self.subTest(forbidden=forbidden): self.assertNotIn(forbidden, source)


if __name__ == "__main__": unittest.main()
