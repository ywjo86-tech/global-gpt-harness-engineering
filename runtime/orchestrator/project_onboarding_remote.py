from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project_onboarding import OnboardingRegistry, ProjectOnboardingError


class ProjectOnboardingRemoteError(ValueError):
    pass


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST_SCHEMA = "orchestration.project-onboarding-request.v1"
_RESULT_SCHEMA = "orchestration.project-onboarding-result.v1"
_MODES = {"DRY_RUN", "BOOTSTRAP"}


@dataclass(frozen=True)
class ProjectOnboardingRequest:
    schema_version: str
    alias: str
    project_root: str
    mapping_root: str
    expected_branch: str
    expected_head: str
    mode: str
    preflight_digest: str | None = None


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProjectOnboardingRemoteError("project git binding is unavailable") from exc


def _safe_absolute_dir_target(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ProjectOnboardingRemoteError(f"{label} must be absolute")
    if path.exists() and (not path.is_dir() or path.is_symlink()):
        raise ProjectOnboardingRemoteError(f"{label} is unsafe")
    return path.resolve()


class ProjectOnboardingAdmission:
    """Narrow create-once recovery admission for an unregistered project.

    This object does not grant execution, activation, provider, completion, or
    effect authority.  It only verifies an exact clean Git binding and delegates
    the canonical contract creation to :class:`OnboardingRegistry`.
    """

    def __init__(self, registry: OnboardingRegistry):
        self.registry = registry

    def _preflight(self, request: ProjectOnboardingRequest) -> tuple[dict[str, Any], str]:
        if request.schema_version != _REQUEST_SCHEMA:
            raise ProjectOnboardingRemoteError("project onboarding request schema mismatch")
        if request.mode not in _MODES:
            raise ProjectOnboardingRemoteError("project onboarding mode is unsupported")
        if not request.expected_branch:
            raise ProjectOnboardingRemoteError("expected branch is required")
        if not _SHA256.fullmatch(request.expected_head):
            raise ProjectOnboardingRemoteError("expected HEAD must be a lowercase SHA-256-like Git hex binding")

        root = Path(request.project_root)
        if not root.is_absolute() or not root.is_dir() or root != root.resolve():
            raise ProjectOnboardingRemoteError("project root must be absolute, existing, and resolved")
        mapping_root = _safe_absolute_dir_target(request.mapping_root, "mapping root")

        branch = _git(root, "branch", "--show-current")
        if branch != request.expected_branch:
            raise ProjectOnboardingRemoteError("project branch drift")
        head = _git(root, "rev-parse", "HEAD")
        if head != request.expected_head:
            raise ProjectOnboardingRemoteError("project HEAD drift")
        clean = not bool(_git(root, "status", "--porcelain"))
        if not clean:
            raise ProjectOnboardingRemoteError("project repository must be clean")

        try:
            inspection = self.registry.inspect(root, request.alias)
        except ProjectOnboardingError as exc:
            raise ProjectOnboardingRemoteError(str(exc)) from exc

        binding = {
            "alias": request.alias,
            "project_root": str(root),
            "mapping_root": str(mapping_root),
            "branch": branch,
            "head": head,
            "clean": True,
            "inspection": inspection,
        }
        digest = hashlib.sha256(_canonical(binding)).hexdigest()
        return binding, digest

    def execute(self, request: ProjectOnboardingRequest) -> dict[str, Any]:
        binding, preflight_digest = self._preflight(request)
        inspection = binding["inspection"]

        if request.mode == "DRY_RUN":
            return {
                "schema_version": _RESULT_SCHEMA,
                "status": inspection["status"],
                "mutation_performed": False,
                "binding": {key: value for key, value in binding.items() if key != "inspection"},
                "preflight_digest": preflight_digest,
                "inspection": inspection,
            }

        if request.preflight_digest is None or not _SHA256.fullmatch(request.preflight_digest):
            raise ProjectOnboardingRemoteError("exact dry-run preflight digest is required")
        if request.preflight_digest != preflight_digest:
            raise ProjectOnboardingRemoteError("preflight binding changed; run DRY_RUN again")
        if inspection["status"] not in {"REGISTRATION_READY", "COMPATIBLE"}:
            raise ProjectOnboardingRemoteError("preflight is not eligible for bootstrap")

        try:
            report = self.registry.bootstrap(
                request.project_root,
                request.alias,
                mapping_root=request.mapping_root,
            )
        except ProjectOnboardingError as exc:
            raise ProjectOnboardingRemoteError(str(exc)) from exc

        return {
            "schema_version": _RESULT_SCHEMA,
            "status": report["status"],
            "mutation_performed": bool(report.get("mutation_performed", False)),
            "binding": {key: value for key, value in binding.items() if key != "inspection"},
            "preflight_digest": preflight_digest,
            "bootstrap": report,
        }
