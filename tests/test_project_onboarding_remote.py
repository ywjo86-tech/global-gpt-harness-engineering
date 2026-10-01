from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry, build_alias_entry
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


def _admission(registry_root: Path, mapping_root: Path) -> ProjectOnboardingAdmission:
    return ProjectOnboardingAdmission(
        OnboardingRegistry(registry_root),
        canonical_mapping_root=mapping_root,
    )


class ProjectOnboardingRemoteTests(unittest.TestCase):
    def test_dry_run_is_read_only_and_returns_bound_preflight_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = _admission(registry_root, mapping_root)
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
            admission = _admission(registry_root, mapping_root)
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "preflight"):
                admission.execute(_request(root, mapping_root, head, mode="BOOTSTRAP"))
            dry_run = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            result = admission.execute(_request(root, mapping_root, head, mode="BOOTSTRAP", preflight_digest=dry_run["preflight_digest"]))
            self.assertEqual(result["status"], "BOOTSTRAPPED")
            self.assertTrue(result["mutation_performed"])
            entry = json.loads((registry_root / "ai-commerce-intelligence.json").read_text(encoding="utf-8"))
            self.assertEqual(entry["project_root"], str(root))
            self.assertTrue((mapping_root / f"{root.name}.json").is_file())

    def test_bootstrap_handles_ignored_required_contract_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, _ = _project(tmp_path)
            (root / ".gitignore").write_text("logs/\n", encoding="utf-8")
            _git(root, "add", ".gitignore")
            _git(root, "commit", "-m", "ignore logs")
            head = _git(root, "rev-parse", "HEAD")
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = _admission(registry_root, mapping_root)
            dry_run = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))

            result = admission.execute(
                _request(
                    root,
                    mapping_root,
                    head,
                    mode="BOOTSTRAP",
                    preflight_digest=dry_run["preflight_digest"],
                )
            )

            self.assertEqual(result["status"], "BOOTSTRAPPED")
            self.assertTrue((root / "logs" / "app.log").is_file())
            self.assertTrue((mapping_root / f"{root.name}.json").is_file())

    def test_branch_or_head_drift_fails_closed_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = _admission(registry_root, mapping_root)
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
            admission = _admission(registry_root, mapping_root)
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
            admission = _admission(registry_root, mapping_root)
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
            admission = _admission(registry_root, canonical_mapping_root)
            with self.assertRaisesRegex(ProjectOnboardingRemoteError, "mapping root"):
                admission.execute(
                    _request(root, untrusted_mapping_root, head, mode="DRY_RUN")
                )
            self.assertFalse(canonical_mapping_root.exists())
            self.assertFalse(untrusted_mapping_root.exists())

    def test_runtime_alias_registry_derives_configured_mapping_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            mapping_root = tmp_path / "mappings"
            registry_root = mapping_root / "aliases"
            admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
            result = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            self.assertEqual(result["binding"]["mapping_root"], str(mapping_root.resolve()))
            self.assertFalse(mapping_root.exists())

    def test_existing_registered_canonical_plan_wins_over_additional_plan_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, head = _project(tmp_path)
            registry_root = tmp_path / "registry"
            mapping_root = tmp_path / "mappings"
            admission = _admission(registry_root, mapping_root)
            dry_run = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))
            admission.execute(_request(root, mapping_root, head, mode="BOOTSTRAP", preflight_digest=dry_run["preflight_digest"]))
            (root / "docs").mkdir(exist_ok=True)
            (root / "docs" / "DEVELOPMENT_PLAN.txt").write_text("# Alternate plan\n", encoding="utf-8")
            _git(root, "add", "docs/DEVELOPMENT_PLAN.txt")
            _git(root, "commit", "-m", "add alternate plan")
            head = _git(root, "rev-parse", "HEAD")

            result = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))

            self.assertEqual(result["status"], "COMPATIBLE")
            self.assertEqual(result["inspection"]["entry"]["canonical_plan"], "IMPLEMENTATION_PLAN.md")

    def test_new_registration_with_two_plan_candidates_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path=Path(temp)
            root, head=_project(tmp_path)
            (root/"docs").mkdir(); (root/"docs/DEVELOPMENT_PLAN.txt").write_text("# Alternate plan\n",encoding="utf-8")
            _git(root,"add","docs/DEVELOPMENT_PLAN.txt"); _git(root,"commit","-m","add ambiguous plan")
            head=_git(root,"rev-parse","HEAD")
            registry_root=tmp_path/"registry"; mapping_root=tmp_path/"mappings"
            admission=_admission(registry_root,mapping_root)
            with self.assertRaisesRegex(ProjectOnboardingRemoteError,"ambiguous"):
                admission.execute(_request(root,mapping_root,head,mode="DRY_RUN"))
            self.assertFalse(registry_root.exists()); self.assertFalse(mapping_root.exists())

    def test_target_inspect_isolated_from_other_project_plan_digest_damage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            root, _ = _project(tmp_path, name="healthy-project")
            damaged, _ = _project(tmp_path, name="damaged-project")
            registry_root = tmp_path / "registry"
            registry_root.mkdir()
            healthy = build_alias_entry(root, "healthy")
            broken = build_alias_entry(damaged, "damaged")
            broken["canonical_plan_sha256"] = "0" * 64
            (registry_root / "healthy.json").write_text(json.dumps(healthy, sort_keys=True), encoding="utf-8")
            (registry_root / "damaged.json").write_text(json.dumps(broken, sort_keys=True), encoding="utf-8")

            result = OnboardingRegistry(registry_root).inspect(root, "healthy")

            self.assertEqual(result["status"], "COMPATIBLE")
            self.assertEqual(result["entry"]["alias"], "healthy")
            with self.assertRaisesRegex(Exception, "canonical plan SHA drift"):
                OnboardingRegistry(registry_root).inspect(damaged, "damaged")
            with self.assertRaisesRegex(Exception, "canonical plan SHA drift"):
                OnboardingRegistry(registry_root).entries()


if __name__ == "__main__":
    unittest.main()
