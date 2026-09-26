"""Governed P2 successor release staging contracts."""
from __future__ import annotations

import hashlib
import json
import os
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
SUCCESSOR_RELEASE_STAGE_RECEIPT_SCHEMA = "orchestration.successor-release-stage-receipt.v1"
SUCCESSOR_PROFILE = "lifecycle-v2-p2"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_REF = re.compile(r"refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
_BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
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


def _file_sha256(path: Path, *, outcome: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise SuccessorReleaseStageError(
            "staging artifact must be a regular non-symlink file", outcome=outcome
        )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SuccessorReleaseStageError(
            "staging artifact hash is unavailable", outcome=outcome
        ) from exc


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _branch_name(value: object) -> str:
    text = str(value or "")
    parts = text.split("/")
    if (
        not _BRANCH_NAME.fullmatch(text)
        or ".." in text
        or "//" in text
        or text.endswith(("/", "."))
        or any(
            not part
            or part.startswith(".")
            or part.endswith((".lock", "."))
            for part in parts
        )
    ):
        raise SuccessorReleaseStageError("invalid expected branch")
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


def _run_git(
    root: Path,
    args: tuple[str, ...],
    *,
    allow_false: bool = False,
) -> subprocess.CompletedProcess[str]:
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
        result = _run_git(
            root,
            ("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"),
            allow_false=True,
        )
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
            lines = [
                line
                for line in fetch_head.read_text(encoding="utf-8").splitlines()
                if line
            ]
        except OSError as exc:
            raise SuccessorReleaseStageError(
                "FETCH_HEAD evidence unavailable", outcome="FAILED_AFTER_FETCH"
            ) from exc
        fetched = [
            line.split()[0]
            for line in lines
            if line.split() and _SHA1.fullmatch(line.split()[0])
        ]
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
            expected_branch=_branch_name(raw.get("expected_branch")),
            expected_head=_sha1(raw.get("expected_head"), "expected head"),
            target_ref=_target_ref(raw.get("target_ref")),
            target_head=_sha1(raw.get("target_head"), "target head"),
            successor_profile=SUCCESSOR_PROFILE,
            approval_policy_ref=_safe_id(
                raw.get("approval_policy_ref"), "approval policy ref"
            ),
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


class SuccessorStageLock:
    """Exclusive lock for one canonical successor workspace and alias."""

    def __init__(self, lock_root: Path, alias: str, canonical_root: Path) -> None:
        self.lock_root = Path(lock_root)
        self.alias = alias
        self.canonical_root = Path(canonical_root)
        key = hashlib.sha256(
            f"{self.canonical_root}\0{self.alias}".encode("utf-8")
        ).hexdigest()
        self.path = self.lock_root / f"{key}.lock"
        self._acquired = False

    def __enter__(self) -> "SuccessorStageLock":
        if not self.lock_root.is_absolute():
            raise SuccessorReleaseStageError("successor stage lock root must be absolute")
        self.lock_root.mkdir(parents=True, exist_ok=True)
        if self.lock_root.is_symlink() or not self.lock_root.is_dir():
            raise SuccessorReleaseStageError("successor stage lock root is unsafe")
        if self.lock_root.resolve(strict=True) != self.lock_root:
            raise SuccessorReleaseStageError("successor stage lock root is not canonical")
        try:
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError as exc:
            raise SuccessorReleaseStageError("successor stage lock is already held") from exc
        except OSError as exc:
            raise SuccessorReleaseStageError("successor stage lock acquisition failed") from exc
        try:
            payload = _canonical(
                {
                    "alias": self.alias,
                    "canonical_root": str(self.canonical_root),
                }
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                self.path.unlink(missing_ok=True)
            finally:
                raise
        self._acquired = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._acquired:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as unlink_exc:
                if exc is None:
                    raise SuccessorReleaseStageError(
                        "successor stage lock release failed"
                    ) from unlink_exc
            finally:
                self._acquired = False
        return False


class SuccessorReleaseReceiptStore:
    """Create-once canonical JSON store keyed by phase request digest."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if not self.root.is_absolute():
            raise SuccessorReleaseStageError("successor receipt root must be absolute")

    def _ensure_root(self) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SuccessorReleaseStageError("successor receipt root is unavailable") from exc
        if self.root.is_symlink() or not self.root.is_dir():
            raise SuccessorReleaseStageError("successor receipt root is unsafe")
        try:
            canonical = self.root.resolve(strict=True)
        except OSError as exc:
            raise SuccessorReleaseStageError("successor receipt root is unavailable") from exc
        if canonical != self.root:
            raise SuccessorReleaseStageError("successor receipt root is not canonical")
        return canonical

    def _path(self, phase_request_digest: str) -> Path:
        digest = _sha256(phase_request_digest, "phase request digest")
        return self._ensure_root() / f"{digest}.json"

    def read_phase(self, phase_request_digest: str) -> dict[str, Any] | None:
        path = self._path(phase_request_digest)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise SuccessorReleaseStageError("successor receipt file is unsafe")
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorReleaseStageError("successor receipt is unreadable") from exc
        if not isinstance(value, dict):
            raise SuccessorReleaseStageError("successor receipt is invalid")
        if value.get("phase_request_digest") != phase_request_digest:
            raise SuccessorReleaseStageError("successor receipt digest binding mismatch")
        if raw != _canonical(value):
            raise SuccessorReleaseStageError("successor receipt is not canonical JSON")
        return value

    def append(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(receipt)
        digest = _sha256(value.get("phase_request_digest"), "phase request digest")
        path = self._path(digest)
        payload = _canonical(value)
        existing = self.read_phase(digest)
        if existing is not None:
            if _canonical(existing) != payload:
                raise SuccessorReleaseStageError("successor receipt digest already sealed")
            return existing
        try:
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError:
            existing = self.read_phase(digest)
            if existing is not None and _canonical(existing) == payload:
                return existing
            raise SuccessorReleaseStageError("successor receipt digest already sealed")
        except OSError as exc:
            raise SuccessorReleaseStageError("successor receipt creation failed") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                path.unlink(missing_ok=True)
            finally:
                raise
        return value

    def find_preflight(
        self,
        *,
        request_id: str,
        stage_intent_digest: str,
        preflight_digest: str,
    ) -> dict[str, Any] | None:
        root = self._ensure_root()
        for path in sorted(root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if (
                value.get("mode") == "DRY_RUN"
                and value.get("request_id") == request_id
                and value.get("stage_intent_digest") == stage_intent_digest
                and value.get("preflight_digest") == preflight_digest
                and value.get("status") == "STAGE_READY"
            ):
                return value
        return None


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

    def _read_replay(self, request: SuccessorReleaseStageRequest) -> dict[str, Any] | None:
        store = self.receipt_store
        if store is None or not hasattr(store, "read_phase"):
            return None
        replay = store.read_phase(request.phase_request_digest)
        if replay is None:
            return None
        if not isinstance(replay, Mapping):
            raise SuccessorReleaseStageError("stored successor phase receipt is invalid")
        return dict(replay)

    def _append_receipt(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        store = self.receipt_store
        if store is None:
            return dict(receipt)
        if not hasattr(store, "append"):
            raise SuccessorReleaseStageError("successor receipt store is invalid")
        stored = store.append(receipt)
        if not isinstance(stored, Mapping):
            raise SuccessorReleaseStageError("stored successor receipt is invalid")
        return dict(stored)

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

    def _lifecycle_snapshot(
        self, *, outcome: str = "FAILED_BEFORE_MUTATION"
    ) -> dict[str, str | None]:
        if self.lifecycle_identity_provider is None:
            raise SuccessorReleaseStageError(
                "lifecycle identity provider is required", outcome=outcome
            )
        lifecycle = self.lifecycle_identity_provider()
        try:
            serving_root = Path(lifecycle.serving_root).resolve(strict=True)
            predecessor_root = (
                Path(lifecycle.predecessor_root).resolve(strict=True)
                if lifecycle.predecessor_root is not None
                else None
            )
        except OSError as exc:
            raise SuccessorReleaseStageError(
                "protected lifecycle root is unavailable", outcome=outcome
            ) from exc
        return {
            "serving_root": str(serving_root),
            "predecessor_root": str(predecessor_root) if predecessor_root is not None else None,
        }

    def _validate_isolation(
        self,
        workspace: SuccessorWorkspaceIdentity,
        *,
        outcome: str = "FAILED_BEFORE_MUTATION",
    ) -> None:
        lifecycle = self._lifecycle_snapshot(outcome=outcome)
        serving_root = Path(str(lifecycle["serving_root"]))
        predecessor_raw = lifecycle["predecessor_root"]
        predecessor_root = Path(predecessor_raw) if predecessor_raw is not None else None
        if workspace.canonical_root == serving_root:
            raise SuccessorReleaseStageError(
                "successor root equals serving root", outcome=outcome
            )
        if predecessor_root is not None and workspace.canonical_root == predecessor_root:
            raise SuccessorReleaseStageError(
                "successor root equals predecessor root", outcome=outcome
            )

    def _validate_local_git(
        self,
        workspace: SuccessorWorkspaceIdentity,
        request: SuccessorReleaseStageRequest,
        *,
        expected_head: str | None = None,
        outcome: str = "FAILED_BEFORE_MUTATION",
    ) -> tuple[str, str]:
        root = workspace.canonical_root
        if self.full_mcp.status(root):
            raise SuccessorReleaseStageError(
                "successor worktree/index must be clean", outcome=outcome
            )
        branch = self.full_mcp.branch(root)
        if branch != request.expected_branch:
            raise SuccessorReleaseStageError("successor branch drift", outcome=outcome)
        head = self.full_mcp.head(root)
        required_head = request.expected_head if expected_head is None else expected_head
        if head != required_head:
            raise SuccessorReleaseStageError("successor HEAD drift", outcome=outcome)
        return branch, head

    def _remote_target(
        self,
        root: Path,
        request: SuccessorReleaseStageRequest,
        *,
        outcome: str = "FAILED_BEFORE_MUTATION",
    ) -> str:
        matches = self.full_mcp.ls_remote(root, request.target_ref)
        if len(matches) != 1:
            raise SuccessorReleaseStageError(
                "remote target ref is missing or ambiguous", outcome=outcome
            )
        observed = matches[0]
        if observed != request.target_head:
            raise SuccessorReleaseStageError(
                "remote target ref does not match approved target", outcome=outcome
            )
        return observed

    def _temporary_ref(self, request: SuccessorReleaseStageRequest) -> str:
        if not _REF_COMPONENT.fullmatch(request.request_id):
            raise SuccessorReleaseStageError("request ID is unsafe for temporary Git ref")
        return f"refs/ocp/successor-stage/{request.request_id}"

    def _effective_lock_root(self) -> Path:
        if self.lock_root is not None:
            return Path(self.lock_root)
        return self.registry.root.parent / "successor-stage-locks"

    def _artifact_roots(self, *, outcome: str) -> tuple[Path, Path]:
        if self.user_config_root is None or self.user_unit_root is None:
            raise SuccessorReleaseStageError(
                "successor artifact roots are required", outcome=outcome
            )
        roots: list[Path] = []
        for raw, label in (
            (self.user_config_root, "user config root"),
            (self.user_unit_root, "user unit root"),
        ):
            path = Path(raw)
            if not path.is_absolute() or path.is_symlink() or not path.is_dir():
                raise SuccessorReleaseStageError(f"{label} is unsafe", outcome=outcome)
            try:
                canonical = path.resolve(strict=True)
            except OSError as exc:
                raise SuccessorReleaseStageError(
                    f"{label} is unavailable", outcome=outcome
                ) from exc
            if canonical != path:
                raise SuccessorReleaseStageError(
                    f"{label} is not canonical", outcome=outcome
                )
            roots.append(canonical)
        return roots[0], roots[1]

    def _serving_artifact_hashes(self, *, outcome: str) -> dict[str, str]:
        config_root, unit_root = self._artifact_roots(outcome=outcome)
        paths = {
            "env": config_root / "ocpv2.env",
            "service": unit_root / "ocpv2.service",
            "timer": unit_root / "ocpv2.timer",
        }
        return {
            name: _file_sha256(path, outcome=outcome)
            for name, path in paths.items()
        }

    def _stage_successor_artifacts(
        self,
        root: Path,
        request: SuccessorReleaseStageRequest,
    ) -> dict[str, str]:
        config_root, unit_root = self._artifact_roots(
            outcome="FAILED_AFTER_GIT_ADVANCE"
        )
        callback = self.stage_artifacts if callable(self.stage_artifacts) else self.stage_callback
        if not callable(callback):
            raise SuccessorReleaseStageError(
                "successor artifact staging callback is unavailable",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            )
        try:
            raw = callback(root, request.successor_profile, config_root, unit_root)
        except SuccessorReleaseStageError:
            raise
        except Exception as exc:
            raise SuccessorReleaseStageError(
                "successor artifact staging failed",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            ) from exc
        if not isinstance(raw, Mapping) or set(raw) != {
            "env_path",
            "service_path",
            "timer_path",
        }:
            raise SuccessorReleaseStageError(
                "successor artifact staging result is invalid",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            )
        expected = {
            "env_path": config_root / f"ocpv2-{request.successor_profile}.env",
            "service_path": unit_root / f"ocpv2-{request.successor_profile}.service",
            "timer_path": unit_root / f"ocpv2-{request.successor_profile}.timer",
        }
        hashes: dict[str, str] = {}
        for key, expected_path in expected.items():
            actual = Path(str(raw[key]))
            if actual != expected_path:
                raise SuccessorReleaseStageError(
                    "successor artifact path escaped fixed profile destinations",
                    outcome="FAILED_AFTER_GIT_ADVANCE",
                )
            hashes[key.removesuffix("_path")] = _file_sha256(
                actual, outcome="FAILED_AFTER_GIT_ADVANCE"
            )
        return hashes

    def _successor_service_state(self, profile: str) -> dict[str, bool]:
        if self.service_state_probe is None:
            return {
                "service_active": False,
                "service_enabled": False,
                "timer_active": False,
                "timer_enabled": False,
                "polling_enabled": False,
            }
        probe = self.service_state_probe
        try:
            if hasattr(probe, "observe") and callable(probe.observe):
                raw = probe.observe(profile)
            elif callable(probe):
                raw = probe(profile)
            else:
                raise TypeError("service state probe is not callable")
        except Exception as exc:
            raise SuccessorReleaseStageError(
                "successor service state observation failed",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            ) from exc
        required = {
            "service_active",
            "service_enabled",
            "timer_active",
            "timer_enabled",
            "polling_enabled",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise SuccessorReleaseStageError(
                "successor service state observation is invalid",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            )
        state = {name: bool(raw[name]) for name in required}
        if any(state.values()):
            raise SuccessorReleaseStageError(
                "successor service/timer/polling must remain inert",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            )
        return state

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
            if not self.full_mcp.is_ancestor(
                root, request.expected_head, request.target_head
            ):
                raise SuccessorReleaseStageError(
                    "approved target is not fast-forward reachable"
                )
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
        if binding is None and self.receipt_store is not None and hasattr(
            self.receipt_store, "find_preflight"
        ):
            raw = self.receipt_store.find_preflight(
                request_id=request.request_id,
                stage_intent_digest=request.stage_intent_digest,
                preflight_digest=str(request.preflight_digest),
            )
            if raw is not None:
                try:
                    binding = _PreflightBinding(
                        stage_intent_digest=str(raw["stage_intent_digest"]),
                        preflight_digest=str(raw["preflight_digest"]),
                        canonical_root=str(raw["canonical_root"]),
                        observed_branch=str(raw["observed_branch"]),
                        observed_head=str(raw["observed_head"]),
                        remote_target_head=str(raw["remote_target_head"]),
                        ancestry_state=str(raw["ancestry_state"]),
                    )
                except KeyError as exc:
                    raise SuccessorReleaseStageError(
                        "stored DRY_RUN preflight is incomplete"
                    ) from exc
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

        lock = SuccessorStageLock(
            self._effective_lock_root(), workspace.alias, workspace.canonical_root
        )
        with lock:
            self._validate_isolation(workspace)
            self._validate_local_git(workspace, request)
            remote_target = self._remote_target(root, request)
            if remote_target != binding.remote_target_head:
                raise SuccessorReleaseStageError("remote target ref drifted since DRY_RUN")

            serving_hashes_before: dict[str, str] | None = None
            if self.user_config_root is not None or self.user_unit_root is not None:
                serving_hashes_before = self._serving_artifact_hashes(
                    outcome="FAILED_BEFORE_MUTATION"
                )

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

                self._validate_isolation(workspace, outcome="FAILED_AFTER_FETCH")
                self._validate_local_git(
                    workspace,
                    request,
                    expected_head=request.expected_head,
                    outcome="FAILED_AFTER_FETCH",
                )

                if not self.full_mcp.object_exists(root, request.target_head):
                    raise SuccessorReleaseStageError(
                        "fetched target object is unavailable",
                        outcome="FAILED_AFTER_FETCH",
                    )
                if not self.full_mcp.is_ancestor(
                    root, request.expected_head, request.target_head
                ):
                    raise SuccessorReleaseStageError(
                        "approved target is not fast-forward reachable",
                        outcome="FAILED_AFTER_FETCH",
                    )

                advanced_head = self.full_mcp.fast_forward_current(
                    root, request.target_head
                )
                if advanced_head != request.target_head:
                    raise SuccessorReleaseStageError(
                        "successor HEAD did not reach approved target",
                        outcome="FAILED_AFTER_GIT_ADVANCE",
                    )

                self._validate_isolation(
                    workspace, outcome="FAILED_AFTER_GIT_ADVANCE"
                )
                self._validate_local_git(
                    workspace,
                    request,
                    expected_head=request.target_head,
                    outcome="FAILED_AFTER_GIT_ADVANCE",
                )

                if serving_hashes_before is None:
                    raise SuccessorReleaseStageError(
                        "successor artifact roots are required",
                        outcome="FAILED_AFTER_GIT_ADVANCE",
                    )

                serving_pre_stage = self._serving_artifact_hashes(
                    outcome="FAILED_AFTER_GIT_ADVANCE"
                )
                if serving_pre_stage != serving_hashes_before:
                    raise SuccessorReleaseStageError(
                        "serving artifact drift before successor staging",
                        outcome="FAILED_AFTER_GIT_ADVANCE",
                    )

                successor_hashes = self._stage_successor_artifacts(root, request)

                self._validate_isolation(
                    workspace, outcome="FAILED_AFTER_GIT_ADVANCE"
                )
                self._validate_local_git(
                    workspace,
                    request,
                    expected_head=request.target_head,
                    outcome="FAILED_AFTER_GIT_ADVANCE",
                )
                serving_hashes_after = self._serving_artifact_hashes(
                    outcome="FAILED_AFTER_GIT_ADVANCE"
                )
                if serving_hashes_after != serving_hashes_before:
                    raise SuccessorReleaseStageError(
                        "serving artifacts changed during successor staging",
                        outcome="FAILED_AFTER_GIT_ADVANCE",
                    )

                service_state = self._successor_service_state(
                    request.successor_profile
                )

                self._validate_isolation(
                    workspace, outcome="FAILED_AFTER_GIT_ADVANCE"
                )
                self._validate_local_git(
                    workspace,
                    request,
                    expected_head=request.target_head,
                    outcome="FAILED_AFTER_GIT_ADVANCE",
                )
                final_serving_hashes = self._serving_artifact_hashes(
                    outcome="FAILED_AFTER_GIT_ADVANCE"
                )
                if final_serving_hashes != serving_hashes_before:
                    raise SuccessorReleaseStageError(
                        "serving artifacts drifted before final receipt",
                        outcome="FAILED_AFTER_GIT_ADVANCE",
                    )

                return {
                    "status": "STAGED",
                    "mutation_performed": True,
                    "service_manager_invoked": False,
                    "polling_enabled": service_state["polling_enabled"],
                    "target_head": request.target_head,
                    "post_head": request.target_head,
                    "fetched_sha": fetched_head,
                    "preflight_digest": request.preflight_digest,
                    "stage_intent_digest": request.stage_intent_digest,
                    "phase_request_digest": request.phase_request_digest,
                    "successor_artifact_hashes": successor_hashes,
                    "serving_artifact_hashes_before": serving_hashes_before,
                    "serving_artifact_hashes_after": final_serving_hashes,
                    "service_state": service_state,
                }
            finally:
                if fetched:
                    self.full_mcp.delete_temporary_ref(root, temporary_ref)

    def _dry_run_receipt(
        self,
        workspace: SuccessorWorkspaceIdentity,
        request: SuccessorReleaseStageRequest,
        result: Mapping[str, Any],
        branch: str,
        head: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": SUCCESSOR_RELEASE_STAGE_RECEIPT_SCHEMA,
            "receipt_schema": SUCCESSOR_RELEASE_STAGE_RECEIPT_SCHEMA,
            "request_id": request.request_id,
            "mode": request.mode,
            "stage_intent_digest": request.stage_intent_digest,
            "phase_request_digest": request.phase_request_digest,
            "preflight_digest": result["preflight_digest"],
            "project_alias": request.project_alias,
            "canonical_root": str(workspace.canonical_root),
            "canonical_successor_root": str(workspace.canonical_root),
            "project_id": workspace.project_id,
            "approval_policy_ref": request.approval_policy_ref,
            "approval_policy_digest": request.approval_policy_digest,
            "expected_branch": request.expected_branch,
            "expected_head": request.expected_head,
            "observed_branch": branch,
            "observed_head": head,
            "pre_head": head,
            "target_ref": request.target_ref,
            "target_head": request.target_head,
            "remote_target_head": result["remote_target_head"],
            "ancestry_state": result["ancestry_state"],
            "outcome": "STAGE_READY",
            "status": "STAGE_READY",
            "mutation_performed": False,
            "service_manager_invoked": False,
            "polling_enabled": False,
        }

    def _stage_receipt(
        self,
        workspace: SuccessorWorkspaceIdentity,
        request: SuccessorReleaseStageRequest,
        binding: _PreflightBinding,
        result: Mapping[str, Any],
        runtime_before: Mapping[str, Any],
        runtime_after: Mapping[str, Any],
    ) -> dict[str, Any]:
        state = dict(result["service_state"])
        guards = {
            "registered_successor": "PASS",
            "canonical_isolation": "PASS",
            "clean_exact_branch_head": "PASS",
            "remote_target_binding": "PASS",
            "bounded_fetch": "PASS",
            "fast_forward_only": "PASS",
            "serving_preservation": "PASS",
            "successor_inert": "PASS",
        }
        receipt = {
            "schema_version": SUCCESSOR_RELEASE_STAGE_RECEIPT_SCHEMA,
            "receipt_schema": SUCCESSOR_RELEASE_STAGE_RECEIPT_SCHEMA,
            "request_id": request.request_id,
            "mode": request.mode,
            "stage_intent_digest": request.stage_intent_digest,
            "phase_request_digest": request.phase_request_digest,
            "preflight_digest": request.preflight_digest,
            "project_alias": request.project_alias,
            "canonical_root": str(workspace.canonical_root),
            "canonical_successor_root": str(workspace.canonical_root),
            "project_id": workspace.project_id,
            "approval_policy_ref": request.approval_policy_ref,
            "approval_policy_digest": request.approval_policy_digest,
            "expected_branch": request.expected_branch,
            "expected_head": request.expected_head,
            "pre_head": request.expected_head,
            "target_ref": request.target_ref,
            "target_head": request.target_head,
            "remote_target_head": binding.remote_target_head,
            "fetched_sha": result["fetched_sha"],
            "ancestor_result": True,
            "ancestor_fast_forward": True,
            "fast_forward_result": True,
            "branch_fast_forward": True,
            "fetch_result": "FETCHED",
            "branch_result": "FAST_FORWARDED",
            "post_head": result["post_head"],
            "successor_artifact_hashes": result["successor_artifact_hashes"],
            "serving_artifact_hashes_before": result["serving_artifact_hashes_before"],
            "serving_artifact_hashes_after": result["serving_artifact_hashes_after"],
            "serving_runtime_identity_before": dict(runtime_before),
            "serving_runtime_identity_after": dict(runtime_after),
            "service_state": state,
            "service_active": state["service_active"],
            "service_enabled": state["service_enabled"],
            "timer_active": state["timer_active"],
            "timer_enabled": state["timer_enabled"],
            "polling_enabled": state["polling_enabled"],
            "guard_results": guards,
            "guard_outcomes": guards,
            "mutation_performed": bool(result["mutation_performed"]),
            "service_manager_invoked": bool(result["service_manager_invoked"]),
            "outcome": "STAGED",
            "status": "STAGED",
        }
        return receipt

    def execute(self, request: SuccessorReleaseStageRequest) -> dict[str, Any]:
        replay = self._read_replay(request)
        if replay is not None:
            return replay

        workspace = self._resolve_workspace(request)
        self._validate_isolation(workspace)
        branch, head = self._validate_local_git(workspace, request)
        if request.mode == "DRY_RUN":
            result = self._execute_dry_run(workspace, request, branch, head)
            receipt = self._dry_run_receipt(workspace, request, result, branch, head)
            return self._append_receipt(receipt)

        binding = self._stage_binding(request)
        runtime_before = self._lifecycle_snapshot()
        result = self._execute_stage(workspace, request, binding)
        runtime_after = self._lifecycle_snapshot(outcome="FAILED_AFTER_GIT_ADVANCE")
        if runtime_after != runtime_before:
            raise SuccessorReleaseStageError(
                "serving runtime identity changed during successor staging",
                outcome="FAILED_AFTER_GIT_ADVANCE",
            )
        receipt = self._stage_receipt(
            workspace,
            request,
            binding,
            result,
            runtime_before,
            runtime_after,
        )
        return self._append_receipt(receipt)
