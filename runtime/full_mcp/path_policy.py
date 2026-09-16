from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import Sequence


class PathPolicyError(ValueError):
    pass


_SENSITIVE_NAMES = {
    ".git", ".ssh", ".gnupg", ".aws", ".npmrc", ".pypirc",
    "credential", "credentials", "credentials.json", "token", "tokens",
    "secret", "secrets", "id_rsa", "id_ed25519",
}
_SENSITIVE_PREFIXES = ("credential", "credentials", "token", "tokens", "secret", "secrets")


def _normalize_relative(value: str, *, allow_root: bool = True) -> str:
    if not isinstance(value, str) or not value or any(ord(ch) < 32 for ch in value):
        raise PathPolicyError("path is empty or contains control characters")
    if "\\" in value:
        raise PathPolicyError("path must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise PathPolicyError("path must be workspace-relative without traversal")
    normalized = path.as_posix()
    if normalized == "." and not allow_root:
        raise PathPolicyError("workspace root is not a valid target")
    return normalized
def _scope_tuple(values: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise PathPolicyError(f"{field} must be a sequence")
    result = tuple(_normalize_relative(item) for item in values)
    if not result or len(result) != len(set(result)):
        raise PathPolicyError(f"{field} is empty or duplicated")
    return result


def _within_scope(relative: str, scopes: Sequence[str]) -> bool:
    target = PurePosixPath(relative)
    for raw in scopes:
        scope = PurePosixPath(raw)
        if raw == "." or target == scope:
            return True
        try:
            target.relative_to(scope)
            return True
        except ValueError:
            pass
    return False


def _is_sensitive(relative: str) -> bool:
    for part in PurePosixPath(relative).parts:
        lowered = part.lower()
        if lowered in _SENSITIVE_NAMES or lowered.startswith(".env"):
            return True
        if any(lowered.startswith(prefix + suffix)
               for prefix in _SENSITIVE_PREFIXES for suffix in (".", "_", "-")):
            return True
    return False


class WorkspacePathPolicy:
    def __init__(
        self, workspace_root: str | Path, *,
        read_scopes: Sequence[str], mutable_scopes: Sequence[str],
        read_only_exceptions: Sequence[str] = (),
    ) -> None:
        root = Path(workspace_root)
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise PathPolicyError("workspace root must be an existing non-symlink absolute directory")
        resolved_root = root.resolve(strict=True)
        if root != resolved_root:
            raise PathPolicyError("workspace root must already be canonical and contain no symlinked components")
        self.workspace_root = resolved_root
        self.read_scopes = _scope_tuple(read_scopes, "read_scopes")
        self.mutable_scopes = _scope_tuple(mutable_scopes, "mutable_scopes")
        self.read_only_exceptions = tuple(
            _normalize_relative(item, allow_root=False) for item in read_only_exceptions
        )
        if len(self.read_only_exceptions) != len(set(self.read_only_exceptions)):
            raise PathPolicyError("read_only_exceptions contains duplicates")

    def _guard_symlinks(self, relative: str) -> Path:
        candidate = self.workspace_root
        parts = () if relative == "." else PurePosixPath(relative).parts
        for index, part in enumerate(parts):
            candidate = candidate / part
            try:
                metadata = os.lstat(candidate)
            except FileNotFoundError:
                break
            except OSError as exc:
                raise PathPolicyError("path metadata inspection failed") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise PathPolicyError("symlink traversal is forbidden")
            if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                raise PathPolicyError("non-directory path component blocks traversal")
        return self.workspace_root if relative == "." else self.workspace_root.joinpath(*parts)

    def resolve_read(self, target: str) -> Path:
        relative = _normalize_relative(target)
        if not _within_scope(relative, self.read_scopes):
            raise PathPolicyError("read target is outside approved read scope")
        if _is_sensitive(relative) and relative not in self.read_only_exceptions:
            raise PathPolicyError("sensitive path requires explicit read-only exception")
        return self._guard_symlinks(relative)

    def resolve_mutable(self, target: str) -> Path:
        relative = _normalize_relative(target, allow_root=False)
        if not _within_scope(relative, self.mutable_scopes):
            raise PathPolicyError("mutable target is outside approved owned scope")
        if _is_sensitive(relative):
            raise PathPolicyError("sensitive path mutation is forbidden")
        return self._guard_symlinks(relative)

    def classify(self, target: str) -> str:
        relative = _normalize_relative(target)
        readable = _within_scope(relative, self.read_scopes)
        mutable = relative != "." and _within_scope(relative, self.mutable_scopes)
        if mutable and not _is_sensitive(relative):
            return "MUTABLE"
        if readable and (not _is_sensitive(relative) or relative in self.read_only_exceptions):
            return "READ_ONLY"
        return "BLOCKED"
