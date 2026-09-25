from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.project_onboarding_remote import (
    ProjectOnboardingAdmission,
    ProjectOnboardingRemoteError,
    ProjectOnboardingRequest,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def _project(tmp_path: Path, name: str = "commerce-project") -> tuple[Path, str]:
    root = tmp_path / name
    root.mkdir()
    (root / "IMPLEMENTATION_PLAN.md").write_text("# Plan\n\nM6 only.\n", encoding="utf-8")
    _git(root, "init", "-b", "m6-successor")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "add", "IMPLEMENTATION_PLAN.md")
    _git(root, "commit", "-m", "initial")
    return root, _git(root, "rev-parse", "HEAD")


def _request(root: Path, mapping_root: Path, head: str, *, mode: str, preflight_digest: str | None = None) -> ProjectOnboardingRequest:
    return ProjectOnboardingRequest(
        schema_version="orchestration.project-onboarding-request.v1",
        alias="ai-commerce-intelligence",
        project_root=str(root),
        mapping_root=str(mapping_root),
        expected_branch="m6-successor",
        expected_head=head,
        mode=mode,
        preflight_digest=preflight_digest,
    )


class ProjectOnboardingRemoteTests(unittest.TestCase):
    def test_dry_run_is_read_only_and_returns_bound_preflight_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
            result = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            self.assertEqual(result["schema_version"], "orchestration.project-onboarding-result.v1")
            self.assertEqual(result["status"], "REGISTRATION_READY")
            self.assertFalse(result["mutation_performed"])
            self.assertEqual(result["binding"]["branch"], "m6-successor")
            self.assertEqual(result["binding"]["head"], head)
            self.assertTrue(result["binding"]["clean"])
            self.assertEqual(len(result["preflight_digest"]), 64)
            self.assertFalse(registry_root.exists())
            self.assertFalse(mapping_root.exists())

    def test_bootstrap_requires_exact_prior_preflight_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "preflight"):
                admission.execute(_request(root, mapping_root, head, mode="BOOTSTRAP"))
            dry_run = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            result = admission.execute(_request(root, mapping_root, head, mode="BOOTSTRAP", preflight_digest=dry_run["preflight_digest"]))
            self.assertEqual(result["status"], "BOOTSTRAPPED")
            self.assertTrue(result["mutation_performed"])
            entry = json.loads((registry_root / "ai-commerce-intelligence.json").read_text(encoding="utf-8"))
            self.assertEqual(entry["project_root"], str(root))
            self.assertTrue((mapping_root / f"{root.name}.json").is_file())

    def test_branch_or_head_drift_fails_closed_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "branch"):
                admission.execute(ProjectOnboardingRequest("orchestration.project-onboarding-request.v1", "ai-commerce-intelligence", str(root), str(mapping_root), "wrong-branch", head, "DRY_RUN", None))
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "HEAD"):
                admission.execute(ProjectOnboardingRequest("orchestration.project-onboarding-request.v1", "ai-commerce-intelligence", str(root), str(mapping_root), "m6-successor", "0" * 40, "DRY_RUN", None))
            self.assertFalse(registry_root.exists())
            self.assertFalse(mapping_root.exists())

    def test_dirty_worktree_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            (root / "local.txt").write_text("uncommitted\n", encoding="utf-8")
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "clean"):
                admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            self.assertFalse(registry_root.exists())
            self.assertFalse(mapping_root.exists())

    def test_preflight_digest_is_invalidated_by_head_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
            dry_run = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            (root / "IMPLEMENTATION_PLAN.md").write_text("# Plan\n\nM6 changed.\n", encoding="utf-8")
            _git(root, "add", "IMPLEMENTATION_PLAN.md")
            _git(root, "commit", "-m", "change plan")
            new_head = _git(root, "rev-parse", "HEAD")
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "preflight"):
                admission.execute(_request(root, mapping_root, new_head, mode="BOOTSTRAP", preflight_digest=dry_run["preflight_digest"]))
            self.assertFalse(registry_root.exists())
            self.assertFalse(mapping_root.exists())

    def test_request_mapping_root_must_match_configured_canonical_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            canonical_mapping_root = tmp_path / "canonical-mappings"
            untrusted_mapping_root = tmp_path / "other-mappings"
            admission = ProjectOnboardingAdmission(
                OnboardingRegistry(registry_root),
                canonical_mapping_root=canonical_mapping_root,
            )
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "mapping root"):
                admission.execute(
                    _request(root, untrusted_mapping_root, head, mode="DRY_RUN")
                )
            self.assertFalse(canonical_mapping_root.exists())
            self.assertFalse(untrusted_mapping_root.exists())


if __name__ == "__main__":
    unittest.main()
