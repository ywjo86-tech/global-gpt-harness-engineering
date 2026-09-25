from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.project_onboarding_remote import (
    ProjectOnboardingAdmission,
    ProjectOnboardingRemoteError,
    ProjectOnboardingRequest,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


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


def test_dry_run_is_read_only_and_returns_bound_preflight_digest(tmp_path: Path) -> None:
    root, head = _project(tmp_path)
    registry_root = tmp_path / "registry"
    mapping_root = tmp_path / "mappings"
    admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))

    result = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))

    assert result["schema_version"] == "orchestration.project-onboarding-result.v1"
    assert result["status"] == "REGISTRATION_READY"
    assert result["mutation_performed"] is False
    assert result["binding"]["branch"] == "m6-successor"
    assert result["binding"]["head"] == head
    assert result["binding"]["clean"] is True
    assert len(result["preflight_digest"]) == 64
    assert not registry_root.exists()
    assert not mapping_root.exists()


def test_bootstrap_requires_exact_prior_preflight_digest(tmp_path: Path) -> None:
    root, head = _project(tmp_path)
    registry_root = tmp_path / "registry"
    mapping_root = tmp_path / "mappings"
    admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))

    with pytest.raises(ProjectOnboardingRemoteError, match="preflight"):
        admission.execute(_request(root, mapping_root, head, mode="BOOTSTRAP"))

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

    assert result["status"] == "BOOTSTRAPPED"
    assert result["mutation_performed"] is True
    entry = json.loads((registry_root / "ai-commerce-intelligence.json").read_text(encoding="utf-8"))
    assert entry["project_root"] == str(root)
    assert (mapping_root / f"{root.name}.json").is_file()


def test_branch_or_head_drift_fails_closed_before_mutation(tmp_path: Path) -> None:
    root, head = _project(tmp_path)
    registry_root = tmp_path / "registry"
    mapping_root = tmp_path / "mappings"
    admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))

    with pytest.raises(ProjectOnboardingRemoteError, match="branch"):
        admission.execute(
            ProjectOnboardingRequest(
                schema_version="orchestration.project-onboarding-request.v1",
                alias="ai-commerce-intelligence",
                project_root=str(root),
                mapping_root=str(mapping_root),
                expected_branch="wrong-branch",
                expected_head=head,
                mode="DRY_RUN",
            )
        )

    with pytest.raises(ProjectOnboardingRemoteError, match="HEAD"):
        admission.execute(
            ProjectOnboardingRequest(
                schema_version="orchestration.project-onboarding-request.v1",
                alias="ai-commerce-intelligence",
                project_root=str(root),
                mapping_root=str(mapping_root),
                expected_branch="m6-successor",
                expected_head="0" * 40,
                mode="DRY_RUN",
            )
        )

    assert not registry_root.exists()
    assert not mapping_root.exists()


def test_dirty_worktree_fails_closed(tmp_path: Path) -> None:
    root, head = _project(tmp_path)
    (root / "local.txt").write_text("uncommitted\n", encoding="utf-8")
    registry_root = tmp_path / "registry"
    mapping_root = tmp_path / "mappings"
    admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))

    with pytest.raises(ProjectOnboardingRemoteError, match="clean"):
        admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))

    assert not registry_root.exists()
    assert not mapping_root.exists()


def test_preflight_digest_is_invalidated_by_head_change(tmp_path: Path) -> None:
    root, head = _project(tmp_path)
    registry_root = tmp_path / "registry"
    mapping_root = tmp_path / "mappings"
    admission = ProjectOnboardingAdmission(OnboardingRegistry(registry_root))
    dry_run = admission.execute(_request(root, mapping_root, head, mode="DRY_RUN"))

    (root / "IMPLEMENTATION_PLAN.md").write_text("# Plan\n\nM6 changed.\n", encoding="utf-8")
    _git(root, "add", "IMPLEMENTATION_PLAN.md")
    _git(root, "commit", "-m", "change plan")
    new_head = _git(root, "rev-parse", "HEAD")

    with pytest.raises(ProjectOnboardingRemoteError, match="preflight"):
        admission.execute(
            _request(
                root,
                mapping_root,
                new_head,
                mode="BOOTSTRAP",
                preflight_digest=dry_run["preflight_digest"],
            )
        )

    assert not registry_root.exists()
    assert not mapping_root.exists()
