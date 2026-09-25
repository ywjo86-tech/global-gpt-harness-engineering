from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .project_onboarding import OnboardingRegistry, ProjectOnboardingError


class ProjectOnboardingRemoteError(ValueError):
    pass


_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REQUEST_SCHEMA = "orchestration.project-onboarding-request.v1"
_RESULT_SCHEMA = "orchestration.project-onboarding-result.v1"
_REQUEST_FIELDS = {
    "schema_version",
    "alias",
    "project_root",
    "mapping_root",
    "expected_branch",
    "expected_head",
    "mode",
    "preflight_digest",
}
_MODES = {"DRY_RUN", "BOOTSTRAP"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ProjectOnboardingRequest:
    schema_version: str
    alias: str
    project_root: str
    mapping_root: str
    expected_branch: str
    expected_head: str
    mode: str
    preflight_digest: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ProjectOnboardingRequest":
        if set(raw) != _REQUEST_FIELDS:
            raise ProjectOnboardingRemoteError("project onboarding request fields mismatch")
        if str(raw.get("schema_version") or "") != _REQUEST_SCHEMA:
            raise ProjectOnboardingRemoteError("project onboarding request schema mismatch")
        alias = str(raw.get("alias") or "")
        if not _SAFE_ALIAS.fullmatch(alias):
            raise ProjectOnboardingRemoteError("project onboarding alias is unsafe")
        project_root = str(raw.get("project_root") or "")
        mapping_root = str(raw.get("mapping_root") or "")
        if not Path(project_root).is_absolute() or not Path(mapping_root).is_absolute():
            raise ProjectOnboardingRemoteError("project onboarding paths must be absolute")
        expected_branch = str(raw.get("expected_branch") or "")
        if not expected_branch or len(expected_branch) > 200 or ".." in expected_branch:
            raise ProjectOnboardingRemoteError("expected branch is invalid")
        expected_head = str(raw.get("expected_head") or "")
        if not _GIT_OID.fullmatch(expected_head):
            raise ProjectOnboardingRemoteError("expected HEAD must be a lowercase Git object id")
        mode = str(raw.get("mode") or "")
        if mode not in _MODES:
            raise ProjectOnboardingRemoteError("project onboarding mode is unsupported")
        preflight_raw = raw.get("preflight_digest")
        preflight_digest = None if preflight_raw is None else str(preflight_raw)
        if mode == "DRY_RUN":
            if preflight_digest is not None:
                raise ProjectOnboardingRemoteError("DRY_RUN must not carry a preflight digest")
        elif preflight_digest is None or not _SHA256.fullmatch(preflight_digest):
            raise ProjectOnboardingRemoteError("BOOTSTRAP requires a valid preflight digest")
        return cls(
            schema_version=_REQUEST_SCHEMA,
            alias=alias,
            project_root=project_root,
            mapping_root=mapping_root,
            expected_branch=expected_branch,
            expected_head=expected_head,
            mode=mode,
            preflight_digest=preflight_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "alias": self.alias,
            "project_root": self.project_root,
            "mapping_root": self.mapping_root,
            "expected_branch": self.expected_branch,
            "expected_head": self.expected_head,
            "mode": self.mode,
            "preflight_digest": self.preflight_digest,
        }

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
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
    effect authority. It only verifies an exact clean Git binding and delegates
    canonical contract creation to :class:`OnboardingRegistry`.
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
        if not _GIT_OID.fullmatch(request.expected_head):
            raise ProjectOnboardingRemoteError("expected HEAD must be a lowercase Git object id")

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
                request.project_root, request.alias, mapping_root=request.mapping_root
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
