"""Bounded read-only host diagnostic operations."""
from __future__ import annotations

import errno
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from .read_only_host_diagnostic_contract import DiagnosticPolicy, ReadOnlyDiagnosticRequestV1

_SENSITIVE_EXACT = frozenset({".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_VALUE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|token|credential|secret)\s*[:=]\s*([^\s,;}]+)")


class DiagnosticError(ValueError):
    pass


class DiagnosticSecurityError(DiagnosticError):
    pass


class DiagnosticUnavailableError(DiagnosticError):
    pass


def _root_for(request: ReadOnlyDiagnosticRequestV1, policy: DiagnosticPolicy) -> Path:
    root = policy.roots.get(request.root_id)
    if root is None:
        raise DiagnosticSecurityError("registered root is not allowed")
    return Path(root)


def _path_parts(relative: str) -> tuple[str, ...]:
    if not relative or "\\" in relative:
        raise DiagnosticSecurityError("unsafe relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
        raise DiagnosticSecurityError("unsafe relative path")
    return pure.parts


def _reject_sensitive(relative: str) -> None:
    name = PurePosixPath(relative).name.lower()
    if name in _SENSITIVE_EXACT or name.endswith(_SENSITIVE_SUFFIXES):
        raise DiagnosticSecurityError("sensitive path is blocked")


def _open_regular_beneath(root: Path, relative: str) -> int:
    parts = _path_parts(relative)
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    opened: list[int] = []
    try:
        current = os.open(root, flags_dir)
        opened.append(current)
        for component in parts[:-1]:
            try:
                current = os.open(component, flags_dir, dir_fd=current)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise DiagnosticSecurityError("symlink or non-directory path component blocked") from exc
                raise DiagnosticUnavailableError("path component unavailable") from exc
            opened.append(current)
        try:
            fd = os.open(parts[-1], flags_file, dir_fd=current)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise DiagnosticSecurityError("symlink target blocked") from exc
            if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
                raise DiagnosticUnavailableError("path unavailable") from exc
            raise DiagnosticSecurityError("path open blocked") from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise DiagnosticSecurityError("target is not a regular file")
        return fd
    finally:
        for opened_fd in reversed(opened):
            try:
                os.close(opened_fd)
            except OSError:
                pass


def _redact_text(text: str) -> tuple[str, bool]:
    redacted, count = _SECRET_VALUE.subn(lambda m: f"{m.group(1)}=[REDACTED]", text)
    return redacted, bool(count)


def read_project_file_range(request: ReadOnlyDiagnosticRequestV1, policy: DiagnosticPolicy) -> dict[str, Any]:
    if request.operation != "project.file_range":
        raise DiagnosticError("wrong operation for file range")
    _reject_sensitive(request.relative_path)
    fd = _open_regular_beneath(_root_for(request, policy), request.relative_path)
    try:
        # Bound the bytes read from the host before decoding or redaction.
        raw = os.read(fd, policy.max_bytes + 1)
    finally:
        os.close(fd)
    if b"\x00" in raw:
        raise DiagnosticSecurityError("binary file is blocked")
    try:
        text = raw[: policy.max_bytes].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DiagnosticSecurityError("binary or non-UTF-8 file is blocked") from exc
    redacted, redaction_applied = _redact_text(text)
    all_lines = redacted.splitlines()
    start = request.start_line - 1
    requested_count = request.line_count
    count = min(requested_count, policy.max_lines)
    selected = all_lines[start : start + count]
    # Keep encoded output within the configured cap even after redaction.
    bounded: list[str] = []
    used = 0
    byte_truncated = False
    for line in selected:
        encoded = line.encode("utf-8")
        separator = 1 if bounded else 0
        if used + separator + len(encoded) > policy.max_bytes:
            byte_truncated = True
            break
        bounded.append(line)
        used += separator + len(encoded)
    truncated = (
        len(raw) > policy.max_bytes
        or requested_count > policy.max_lines
        or byte_truncated
        or start + len(bounded) < min(len(all_lines), start + requested_count)
    )
    return {
        "canonical_relative_path": request.relative_path,
        "start_line": request.start_line,
        "lines": bounded,
        "redaction_applied": redaction_applied,
        "truncated": truncated,
    }


def read_path_metadata(request: ReadOnlyDiagnosticRequestV1, policy: DiagnosticPolicy) -> dict[str, Any]:
    if request.operation != "path.metadata":
        raise DiagnosticError("wrong operation for path metadata")
    _reject_sensitive(request.relative_path)
    fd = _open_regular_beneath(_root_for(request, policy), request.relative_path)
    try:
        info = os.fstat(fd)
    finally:
        os.close(fd)
    return {
        "exists": True,
        "type": "regular",
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "mode_class": oct(stat.S_IMODE(info.st_mode)),
        "canonical_relative_path": request.relative_path,
    }
