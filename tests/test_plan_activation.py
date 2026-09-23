from __future__ import annotations

import hashlib
import inspect
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.ai_office.activation import AIActivationContextV1
from runtime.orchestrator.approved_work_binding import ApprovedWorkBindingV1
from runtime.orchestrator.plan_activation import PlanActivationError, activate_approved_work


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def init_repo(root: Path, files: dict[str, str]) -> None:
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")


class PlanActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project = base / "project"
        self.runtime = base / "runtime"
        self.state = base / "state"
        self.state.mkdir()
        init_repo(self.project, {
            "PLAN.md": "# Plan\n\n### Task T1: First\n### Task T2: Second\n",
            "SPEC.md": "# Spec\n",
        })
        init_repo(self.runtime, {"runtime.txt": "immutable runtime\n"})
        self.head = git(self.project, "rev-parse", "HEAD")
        self.plan_sha = hashlib.sha256((self.project / "PLAN.md").read_bytes()).hexdigest()
        self.spec_sha = hashlib.sha256((self.project / "SPEC.md").read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def binding(self, **changes) -> ApprovedWorkBindingV1:
        values = {
            "schema_version": "orchestration.approved-work-binding.v1",
            "activation_request_id": "ACT-1", "request_digest": "a" * 64,
            "project_alias": "demo", "project_id": "project", "project_root": str(self.project),
            "approved_plan_path": "PLAN.md", "approved_plan_sha256": self.plan_sha,
            "approved_spec_path": "SPEC.md", "approved_spec_sha256": self.spec_sha,
            "requirement_artifact_path": "requirements.json", "requirement_artifact_sha256": "b" * 64,
            "approval_ref": "approval:user", "expected_branch": "main", "expected_head": self.head,
            "task_ids": ("T1", "T2"), "runtime_release_digest": "c" * 64,
            "runtime_code_root": str(self.runtime),
        }
        values.update(changes)
        return ApprovedWorkBindingV1(**values)

    def context(self, **changes) -> AIActivationContextV1:
        values = {
            "schema_version": "ai-office.activation-context.v1",
            "activation_request_id": "ACT-1", "project_id": "project", "office_run_id": "ACT-1",
            "requirement_id": "approved-work:ACT-1", "requirement_envelope_digest": "d" * 64,
            "full_plan_plan_digest": self.plan_sha, "full_plan_spec_digest": self.spec_sha,
            "requirement_artifact_digest": "b" * 64, "approval_ref": "approval:user",
            "expected_head": self.head, "workflow_state": "INTAKE_READY", "workflow_revision": 1,
            "workflow_state_digest": "e" * 64,
        }
        values.update(changes)
        return AIActivationContextV1(**values)

    def test_registers_exact_approved_job_and_second_call_is_idempotent(self):
        first = activate_approved_work(
            self.binding(), ai_context=self.context(), harness_state_root=self.state,
            runtime_code_root=self.runtime,
        )
        self.assertEqual(first.status, "REGISTERED")
        self.assertTrue(Path(first.canonical_job_path).is_file())
        self.assertEqual(first.run_id, "ACT-1")
        self.assertTrue(first.authority_digest)
        second = activate_approved_work(
            self.binding(), ai_context=self.context(), harness_state_root=self.state,
            runtime_code_root=self.runtime,
        )
        self.assertEqual(second.status, "ALREADY_REGISTERED")
        self.assertEqual(second.canonical_job_path, first.canonical_job_path)
        self.assertEqual(second.authority_digest, first.authority_digest)

    def test_ai_context_must_match_exact_validated_binding(self):
        with self.assertRaisesRegex(PlanActivationError, "ACTIVATION_CONTEXT_MISMATCH"):
            activate_approved_work(
                self.binding(), ai_context=self.context(expected_head="f" * 40),
                harness_state_root=self.state, runtime_code_root=self.runtime,
            )

    def test_adapter_has_no_process_launch_provider_or_full_mcp_authority(self):
        import runtime.orchestrator.plan_activation as module
        source = inspect.getsource(module)
        for forbidden in ("systemd-run", "subprocess", "provider_router", "FullMCPRuntime", "run_job("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
