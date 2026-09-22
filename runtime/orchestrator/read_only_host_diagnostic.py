from __future__ import annotations

import errno
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from .read_only_host_diagnostic_contract import DiagnosticPolicy, ReadOnlyDiagnosticRequestV1

_SENSITIVE_EXACT = frozenset({".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_VALUE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|token|credential|secret)\s*[:=]\s*([^\s,;}]+)")


class DiagnosticSecurityError(ValueError):
    pass


class DiagnosticExecutionError(ValueError):
    pass


def _validated_parts(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise DiagnosticSecurityError("unsafe relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or relative.startswith("/") or ".." in pure.parts or "." in pure.parts:
        raise DiagnosticSecurityError("path traversal is blocked")
    if pure.as_posix() != relative:
        raise DiagnosticSecurityError("non-canonical relative path")
    return pure.parts


def _reject_sensitive_path(relative: str) -> None:
    for component in _validated_parts(relative):
        lowered = component.lower()
        if lowered in _SENSITIVE_EXACT or lowered.endswith(_SENSITIVE_SUFFIXES):
            raise DiagnosticSecurityError("sensitive path is blocked")


def _open_beneath(root: Path, relative: str, *, regular_only: bool) -> int:
    parts = _validated_parts(relative)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    root_fd = os.open(root, os.O_RDONLY | directory)
    current_fd = root_fd
    try:
        for component in parts[:-1]:
            try:
                next_fd = os.open(component, os.O_RDONLY | directory | nofollow, dir_fd=current_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise DiagnosticSecurityError("symlink or non-directory path component blocked") from exc
                raise
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        try:
            final_fd = os.open(
                parts[-1],
                os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                dir_fd=current_fd,
            )
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise DiagnosticSecurityError("symlink target blocked") from exc
            raise
        info = os.fstat(final_fd)
        if regular_only and not stat.S_ISREG(info.st_mode):
            os.close(final_fd)
            raise DiagnosticSecurityError("target must be a regular file")
        if not regular_only and not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            os.close(final_fd)
            raise DiagnosticSecurityError("target must be a regular file or directory")
        return final_fd
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _open_regular_beneath(root: Path, relative: str) -> int:
    return _open_beneath(root, relative, regular_only=True)


def _redact_text(text: str) -> tuple[str, bool]:
    redacted, count = _SECRET_VALUE.subn(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return redacted, bool(count)


def _bounded_utf8_prefix(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def read_project_file_range(request: ReadOnlyDiagnosticRequestV1, policy: DiagnosticPolicy) -> dict[str, Any]:
    if request.operation != "project.file_range":
        raise DiagnosticExecutionError("wrong operation for file range")
    _reject_sensitive_path(request.relative_path)
    root = policy.root(request.root_id)
    fd = _open_regular_beneath(root, request.relative_path)
    try:
        selected: list[str] = []
        target_count = min(request.line_count, policy.max_lines)
        start_index = request.start_line - 1
        binary = False
        decode_error = False
        with os.fdopen(os.dup(fd), "rb") as handle:
            for index, raw_line in enumerate(handle):
                if b"\x00" in raw_line:
                    binary = True
                    break
                if index < start_index:
                    continue
                if len(selected) >= target_count:
                    break
                try:
                    selected.append(raw_line.decode("utf-8"))
                except UnicodeDecodeError:
                    decode_error = True
                    break
        if binary or decode_error:
            raise DiagnosticSecurityError("binary or non-UTF-8 file is blocked")
        text = "".join(selected)
        text, redaction_applied = _redact_text(text)
        byte_truncated = len(text.encode("utf-8")) > policy.max_bytes
        if byte_truncated:
            text = _bounded_utf8_prefix(text, policy.max_bytes)
        range_truncated = request.line_count > policy.max_lines
        truncated = byte_truncated or range_truncated
        return {
            "canonical_relative_path": PurePosixPath(request.relative_path).as_posix(),
            "start_line": request.start_line,
            "lines_returned": len(selected),
            "text": text,
            "redaction_applied": redaction_applied,
            "truncated": truncated,
        }
    finally:
        os.close(fd)


def read_path_metadata(request: ReadOnlyDiagnosticRequestV1, policy: DiagnosticPolicy) -> dict[str, Any]:
    if request.operation != "path.metadata":
        raise DiagnosticExecutionError("wrong operation for metadata")
    _reject_sensitive_path(request.relative_path)
    root = policy.root(request.root_id)
    relative = PurePosixPath(request.relative_path).as_posix()
    try:
        fd = _open_beneath(root, request.relative_path, regular_only=False)
    except FileNotFoundError:
        return {
            "exists": False,
            "type": "missing",
            "size": 0,
            "mtime_ns": 0,
            "mode_class": "missing",
            "canonical_relative_path": relative,
        }
    try:
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode):
            kind = "file"
            mode_class = "regular"
        elif stat.S_ISDIR(info.st_mode):
            kind = "directory"
            mode_class = "directory"
        else:
            raise DiagnosticSecurityError("unsafe special file")
        return {
            "exists": True,
            "type": kind,
            "size": int(info.st_size),
            "mtime_ns": int(info.st_mtime_ns),
            "mode_class": mode_class,
            "canonical_relative_path": relative,
        }
    finally:
        os.close(fd)
