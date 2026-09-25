"""Governed P2 successor release staging contracts."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .project_onboarding import (
    OnboardingRegistry,
    ProjectOnboardingError,
    validate_alias_entry,
)

SUCCESSOR_RELEASE_STAGE_SCHEMA = "orchestration.successor-release-stage-request.v1"
SUCCESSOR_PROFILE = "lifecycle-v2-p2"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_REF = re.compile(r"refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
_FIELDS = {
    "request_id",
    "schema_version",
    "project_alias",
    "expected_branch",
    "expected_head",
    "target_ref",
    "target_head",
    "successor_profile",
    "approval_policy_ref",
    "approval_policy_digest",
    "mode",
    "preflight_digest",
}


class SuccessorReleaseStageError(ValueError):
    """Fail-closed validation or staging error."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _sha1(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA1.fullmatch(text):
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _sha256(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _target_ref(value: object) -> str:
    text = str(value or "")
    if (
        not _TARGET_REF.fullmatch(text)
        or ".." in text
        or "//" in text
        or text.endswith(("/", "."))
    ):
        raise SuccessorReleaseStageError("invalid target ref")
    return text


def _git_read(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SuccessorReleaseStageError("successor git observation failed") from exc
    return result.stdout.strip()


@dataclass(frozen=True, slots=True)
class SuccessorReleaseStageRequest:
    request_id: str
    schema_version: str
    project_alias: str
    expected_branch: str
    expected_head: str
    target_ref: str
    target_head: str
    successor_profile: str
    approval_policy_ref: str
    approval_policy_digest: str
    mode: str
    preflight_digest: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SuccessorReleaseStageRequest":
        if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
            raise SuccessorReleaseStageError("successor stage request fields mismatch")
        if raw.get("schema_version") != SUCCESSOR_RELEASE_STAGE_SCHEMA:
            raise SuccessorReleaseStageError("unsupported successor stage request schema")

        mode = str(raw.get("mode") or "")
        if mode not in {"DRY_RUN", "STAGE"}:
            raise SuccessorReleaseStageError("invalid successor stage mode")

        profile = str(raw.get("successor_profile") or "")
        if profile != SUCCESSOR_PROFILE:
            raise SuccessorReleaseStageError("unsupported successor profile")

        preflight_raw = raw.get("preflight_digest")
        if mode == "DRY_RUN":
            if preflight_raw is not None:
                raise SuccessorReleaseStageError("DRY_RUN preflight digest must be absent")
            preflight_digest = None
        else:
            preflight_digest = _sha256(preflight_raw, "preflight digest")

        return cls(
            request_id=_safe_id(raw.get("request_id"), "request ID"),
            schema_version=SUCCESSOR_RELEASE_STAGE_SCHEMA,
            project_alias=_safe_id(raw.get("project_alias"), "project alias"),
            expected_branch=_safe_id(raw.get("expected_branch"), "expected branch"),
            expected_head=_sha1(raw.get("expected_head"), "expected head"),
            target_ref=_target_ref(raw.get("target_ref")),
            target_head=_sha1(raw.get("target_head"), "target head"),
            successor_profile=SUCCESSOR_PROFILE,
            approval_policy_ref=_safe_id(raw.get("approval_policy_ref"), "approval policy ref"),
            approval_policy_digest=_sha256(
                raw.get("approval_policy_digest"), "approval policy digest"
            ),
            mode=mode,
            preflight_digest=preflight_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "project_alias": self.project_alias,
            "expected_branch": self.expected_branch,
            "expected_head": self.expected_head,
            "target_ref": self.target_ref,
            "target_head": self.target_head,
            "successor_profile": self.successor_profile,
            "approval_policy_ref": self.approval_policy_ref,
            "approval_policy_digest": self.approval_policy_digest,
            "mode": self.mode,
            "preflight_digest": self.preflight_digest,
        }

    def intent_mapping(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("mode")
        value.pop("preflight_digest")
        return value

    @property
    def stage_intent_digest(self) -> str:
        return hashlib.sha256(_canonical(self.intent_mapping())).hexdigest()

    @property
    def phase_request_digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SuccessorLifecycleIdentity:
    serving_root: Path
    predecessor_root: Path | None


@dataclass(frozen=True, slots=True)
class SuccessorWorkspaceIdentity:
    alias: str
    canonical_root: Path
    project_id: str


class SuccessorReleaseStager:
    """Own the bounded P2 successor transaction; mutation is added in later tasks."""

    def __init__(
        self,
        registry: OnboardingRegistry,
        *,
        full_mcp: object | None = None,
        lifecycle_identity_provider: Callable[[], SuccessorLifecycleIdentity] | None = None,
        receipt_store: object | None = None,
        lock_root: Path | None = None,
        stage_artifacts: object | None = None,
        service_state_probe: object | None = None,
        stage_callback: object | None = None,
        user_config_root: Path | None = None,
        user_unit_root: Path | None = None,
    ) -> None:
        self.registry = registry
        self.full_mcp = full_mcp
        self.lifecycle_identity_provider = lifecycle_identity_provider
        self.receipt_store = receipt_store
        self.lock_root = lock_root
        self.stage_artifacts = stage_artifacts
        self.service_state_probe = service_state_probe
        self.stage_callback = stage_callback
        self.user_config_root = user_config_root
        self.user_unit_root = user_unit_root

    def _resolve_workspace(
        self, request: SuccessorReleaseStageRequest
    ) -> SuccessorWorkspaceIdentity:
        try:
            matches = [
                entry
                for entry in self.registry.entries()
                if entry.get("alias") == request.project_alias
            ]
            if len(matches) != 1:
                raise SuccessorReleaseStageError(
                    "successor alias must resolve to exactly one registry entry"
                )
            entry = matches[0]
            validate_alias_entry(entry)
        except ProjectOnboardingError as exc:
            raise SuccessorReleaseStageError("successor registry binding is invalid") from exc

        root = Path(entry["project_root"])
        try:
            canonical_root = root.resolve(strict=True)
        except OSError as exc:
            raise SuccessorReleaseStageError("successor project root is unavailable") from exc
        if root != canonical_root:
            raise SuccessorReleaseStageError("successor project root is not canonical")
        return SuccessorWorkspaceIdentity(
            alias=request.project_alias,
            canonical_root=canonical_root,
            project_id=str(entry["project_id"]),
        )

    def _validate_isolation(self, workspace: SuccessorWorkspaceIdentity) -> None:
        if self.lifecycle_identity_provider is None:
            raise SuccessorReleaseStageError("lifecycle identity provider is required")
        lifecycle = self.lifecycle_identity_provider()
        try:
            serving_root = Path(lifecycle.serving_root).resolve(strict=True)
            predecessor_root = (
                Path(lifecycle.predecessor_root).resolve(strict=True)
                if lifecycle.predecessor_root is not None
                else None
            )
        except OSError as exc:
            raise SuccessorReleaseStageError("protected lifecycle root is unavailable") from exc
        if workspace.canonical_root == serving_root:
            raise SuccessorReleaseStageError("successor root equals serving root")
        if predecessor_root is not None and workspace.canonical_root == predecessor_root:
            raise SuccessorReleaseStageError("successor root equals predecessor root")

    def _validate_local_git(
        self,
        workspace: SuccessorWorkspaceIdentity,
        request: SuccessorReleaseStageRequest,
    ) -> None:
        root = workspace.canonical_root
        if _git_read(root, "status", "--porcelain"):
            raise SuccessorReleaseStageError("successor worktree/index must be clean")
        if _git_read(root, "symbolic-ref", "--short", "HEAD") != request.expected_branch:
            raise SuccessorReleaseStageError("successor branch drift")
        if _git_read(root, "rev-parse", "HEAD") != request.expected_head:
            raise SuccessorReleaseStageError("successor HEAD drift")

    def execute(self, request: SuccessorReleaseStageRequest) -> dict[str, Any]:
        workspace = self._resolve_workspace(request)
        self._validate_isolation(workspace)
        self._validate_local_git(workspace, request)
        raise SuccessorReleaseStageError("successor release transaction is not implemented yet")
