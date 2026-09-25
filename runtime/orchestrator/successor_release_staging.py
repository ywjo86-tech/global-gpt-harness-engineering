"""Governed P2 successor release staging contracts."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

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
_REF_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
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
    """Fail-closed validation or staging error with bounded failure phase."""

    def __init__(self, message: str, *, outcome: str = "FAILED_BEFORE_MUTATION") -> None:
        super().__init__(message)
        self.outcome = outcome


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


def _run_git(root: Path, args: tuple[str, ...], *, allow_false: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise SuccessorReleaseStageError("bounded successor git operation failed") from exc
    if result.returncode != 0 and not (allow_false and result.returncode == 1):
        raise SuccessorReleaseStageError("bounded successor git operation failed")
    return result


def _fetch_head_path(root: Path) -> Path:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git / "FETCH_HEAD"
    if dot_git.is_file():
        line = dot_git.read_text(encoding="utf-8").strip()
        prefix = "gitdir: "
        if not line.startswith(prefix):
            raise SuccessorReleaseStageError(
                "invalid gitdir indirection", outcome="FAILED_AFTER_FETCH"
            )
        git_dir = Path(line[len(prefix) :])
        if not git_dir.is_absolute():
            git_dir = (root / git_dir).resolve()
        return git_dir / "FETCH_HEAD"
    raise SuccessorReleaseStageError(
        "successor git metadata unavailable", outcome="FAILED_AFTER_FETCH"
    )


class SuccessorReleaseFullMcpPort(Protocol):
    """Narrow Git-only port; intentionally exposes no raw argv or shell API."""

    def status(self, root: Path) -> str: ...

    def branch(self, root: Path) -> str: ...

    def head(self, root: Path) -> str: ...

    def ls_remote(self, root: Path, target_ref: str) -> list[str]: ...

    def object_exists(self, root: Path, sha: str) -> bool: ...

    def is_ancestor(self, root: Path, ancestor: str, descendant: str) -> bool: ...

    def fetch_target(self, root: Path, target_ref: str, temporary_ref: str) -> str: ...

    def fast_forward_current(self, root: Path, target_head: str) -> str: ...

    def delete_temporary_ref(self, root: Path, temporary_ref: str) -> None: ...


class _BoundedGitFullMcp:
    """Local adapter whose public surface maps one-to-one to fixed Git shapes."""

    def status(self, root: Path) -> str:
        return _run_git(root, ("status", "--porcelain")).stdout.strip()

    def branch(self, root: Path) -> str:
        return _run_git(root, ("symbolic-ref", "--short", "HEAD")).stdout.strip()

    def head(self, root: Path) -> str:
        return _run_git(root, ("rev-parse", "HEAD")).stdout.strip()

    def ls_remote(self, root: Path, target_ref: str) -> list[str]:
        result = _run_git(root, ("ls-remote", "--refs", "origin", target_ref))
        matches: list[str] = []
        for raw_line in result.stdout.splitlines():
            parts = raw_line.split()
            if len(parts) == 2 and parts[1] == target_ref and _SHA1.fullmatch(parts[0]):
                matches.append(parts[0])
        return matches

    def object_exists(self, root: Path, sha: str) -> bool:
        result = _run_git(root, ("cat-file", "-e", f"{sha}^{{commit}}"), allow_false=True)
        return result.returncode == 0

    def is_ancestor(self, root: Path, ancestor: str, descendant: str) -> bool:
        result = _run_git(
            root,
            ("merge-base", "--is-ancestor", ancestor, descendant),
            allow_false=True,
        )
        return result.returncode == 0

    def fetch_target(self, root: Path, target_ref: str, temporary_ref: str) -> str:
        try:
            _run_git(
                root,
                ("fetch", "--no-tags", "origin", f"{target_ref}:{temporary_ref}"),
            )
        except SuccessorReleaseStageError as exc:
            raise SuccessorReleaseStageError(
                "bounded target fetch failed", outcome="FAILED_AFTER_FETCH"
            ) from exc
        fetch_head = _fetch_head_path(root)
        try:
            lines = [line for line in fetch_head.read_text(encoding="utf-8").splitlines() if line]
        except OSError as exc:
            raise SuccessorReleaseStageError(
                "FETCH_HEAD evidence unavailable", outcome="FAILED_AFTER_FETCH"
            ) from exc
        fetched = [line.split()[0] for line in lines if line.split() and _SHA1.fullmatch(line.split()[0])]
        if len(fetched) != 1:
            raise SuccessorReleaseStageError(
                "bounded fetch produced ambiguous evidence", outcome="FAILED_AFTER_FETCH"
            )
        return fetched[0]

    def fast_forward_current(self, root: Path, target_head: str) -> str:
        try:
            _run_git(root, ("merge", "--ff-only", target_head))
        except SuccessorReleaseStageError as exc:
            raise SuccessorReleaseStageError(
                "successor fast-forward failed", outcome="FAILED_AFTER_FETCH"
            ) from exc
        return self.head(root)

    def delete_temporary_ref(self, root: Path, temporary_ref: str) -> None:
        try:
            _run_git(root, ("update-ref", "-d", temporary_ref))
        except SuccessorReleaseStageError as exc:
            raise SuccessorReleaseStageError(
                "temporary successor stage ref cleanup failed",
                outcome="FAILED_AFTER_FETCH",
            ) from exc


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


@dataclass(frozen=True, slots=True)
class _PreflightBinding:
    stage_intent_digest: str
    preflight_digest: str
    canonical_root: str
    observed_branch: str
    observed_head: str
    remote_target_head: str
    ancestry_state: str


class SuccessorReleaseStager:
    """Own the bounded P2 successor transaction without activation authority."""

    def __init__(
        self,
        registry: OnboardingRegistry,
        *,
        full_mcp: SuccessorReleaseFullMcpPort | None = None,
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
        self.full_mcp: SuccessorReleaseFullMcpPort = full_mcp or _BoundedGitFullMcp()
        self.lifecycle_identity_provider = lifecycle_identity_provider
        self.receipt_store = receipt_store
        self.lock_root = lock_root
        self.stage_artifacts = stage_artifacts
        self.service_state_probe = service_state_probe
        self.stage_callback = stage_callback
        self.user_config_root = user_config_root
        self.user_unit_root = user_unit_root
        self._preflights: dict[str, _PreflightBinding] = {}

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
    ) -> tuple[str, str]:
        root = workspace.canonical_root
        if self.full_mcp.status(root):
            raise SuccessorReleaseStageError("successor worktree/index must be clean")
        branch = self.full_mcp.branch(root)
        if branch != request.expected_branch:
            raise SuccessorReleaseStageError("successor branch drift")
        head = self.full_mcp.head(root)
        if head != request.expected_head:
            raise SuccessorReleaseStageError("successor HEAD drift")
        return branch, head

    def _remote_target(self, root: Path, request: SuccessorReleaseStageRequest) -> str:
        matches = self.full_mcp.ls_remote(root, request.target_ref)
        if len(matches) != 1:
            raise SuccessorReleaseStageError("remote target ref is missing or ambiguous")
        observed = matches[0]
        if observed != request.target_head:
            raise SuccessorReleaseStageError("remote target ref does not match approved target")
        return observed

    def _temporary_ref(self, request: SuccessorReleaseStageRequest) -> str:
        if not _REF_COMPONENT.fullmatch(request.request_id):
            raise SuccessorReleaseStageError("request ID is unsafe for temporary Git ref")
        return f"refs/ocp/successor-stage/{request.request_id}"

    def _execute_dry_run(
        self,
        workspace: SuccessorWorkspaceIdentity,
        request: SuccessorReleaseStageRequest,
        branch: str,
        head: str,
    ) -> dict[str, Any]:
        root = workspace.canonical_root
        remote_target = self._remote_target(root, request)
        if self.full_mcp.object_exists(root, request.target_head):
            if not self.full_mcp.is_ancestor(root, request.expected_head, request.target_head):
                raise SuccessorReleaseStageError("approved target is not fast-forward reachable")
            ancestry_state = "PROVEN_FAST_FORWARD"
        else:
            ancestry_state = "PENDING_FETCH_PROOF"

        evidence = {
            "stage_intent_digest": request.stage_intent_digest,
            "canonical_root": str(root),
            "observed_branch": branch,
            "observed_head": head,
            "remote_target_head": remote_target,
            "ancestry_state": ancestry_state,
            "approval_policy_ref": request.approval_policy_ref,
            "approval_policy_digest": request.approval_policy_digest,
        }
        preflight_digest = hashlib.sha256(_canonical(evidence)).hexdigest()
        self._preflights[request.request_id] = _PreflightBinding(
            stage_intent_digest=request.stage_intent_digest,
            preflight_digest=preflight_digest,
            canonical_root=str(root),
            observed_branch=branch,
            observed_head=head,
            remote_target_head=remote_target,
            ancestry_state=ancestry_state,
        )
        return {
            "status": "STAGE_READY",
            "mutation_performed": False,
            "target_head": request.target_head,
            "remote_target_head": remote_target,
            "ancestry_state": ancestry_state,
            "preflight_digest": preflight_digest,
            "stage_intent_digest": request.stage_intent_digest,
            "phase_request_digest": request.phase_request_digest,
        }

    def _stage_binding(self, request: SuccessorReleaseStageRequest) -> _PreflightBinding:
        binding = self._preflights.get(request.request_id)
        if binding is None:
            raise SuccessorReleaseStageError("STAGE requires a prior DRY_RUN preflight")
        if binding.stage_intent_digest != request.stage_intent_digest:
            raise SuccessorReleaseStageError("STAGE intent does not match DRY_RUN")
        if binding.preflight_digest != request.preflight_digest:
            raise SuccessorReleaseStageError("STAGE preflight digest mismatch")
        return binding

    def _execute_stage(
        self,
        workspace: SuccessorWorkspaceIdentity,
        request: SuccessorReleaseStageRequest,
        binding: _PreflightBinding,
    ) -> dict[str, Any]:
        root = workspace.canonical_root
        if str(root) != binding.canonical_root:
            raise SuccessorReleaseStageError("successor canonical root drift")
        remote_target = self._remote_target(root, request)
        if remote_target != binding.remote_target_head:
            raise SuccessorReleaseStageError("remote target ref drifted since DRY_RUN")

        temporary_ref = self._temporary_ref(request)
        fetched = False
        try:
            try:
                fetched_head = self.full_mcp.fetch_target(
                    root, request.target_ref, temporary_ref
                )
                fetched = True
            except SuccessorReleaseStageError as exc:
                if exc.outcome == "FAILED_AFTER_FETCH":
                    raise
                raise SuccessorReleaseStageError(
                    "bounded successor fetch failed", outcome="FAILED_AFTER_FETCH"
                ) from exc
            except Exception as exc:
                raise SuccessorReleaseStageError(
                    "bounded successor fetch failed", outcome="FAILED_AFTER_FETCH"
                ) from exc

            if fetched_head != request.target_head:
                raise SuccessorReleaseStageError(
                    "fetched SHA does not match approved target",
                    outcome="FAILED_AFTER_FETCH",
                )
            if not self.full_mcp.object_exists(root, request.target_head):
                raise SuccessorReleaseStageError(
                    "fetched target object is unavailable", outcome="FAILED_AFTER_FETCH"
                )
            if not self.full_mcp.is_ancestor(
                root, request.expected_head, request.target_head
            ):
                raise SuccessorReleaseStageError(
                    "approved target is not fast-forward reachable",
                    outcome="FAILED_AFTER_FETCH",
                )

            advanced_head = self.full_mcp.fast_forward_current(root, request.target_head)
            if advanced_head != request.target_head:
                raise SuccessorReleaseStageError(
                    "successor HEAD did not reach approved target",
                    outcome="FAILED_AFTER_GIT_ADVANCE",
                )
            raise SuccessorReleaseStageError(
                "successor artifact staging is not implemented yet",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            )
        finally:
            if fetched:
                self.full_mcp.delete_temporary_ref(root, temporary_ref)

    def execute(self, request: SuccessorReleaseStageRequest) -> dict[str, Any]:
        workspace = self._resolve_workspace(request)
        self._validate_isolation(workspace)
        branch, head = self._validate_local_git(workspace, request)
        if request.mode == "DRY_RUN":
            return self._execute_dry_run(workspace, request, branch, head)
        binding = self._stage_binding(request)
        return self._execute_stage(workspace, request, binding)
