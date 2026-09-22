"""Bounded read-only host diagnostic operations."""
from __future__ import annotations

import errno
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, Callable, Mapping

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

_GIT_COMMANDS = frozenset({
    ("status", "--porcelain=v2", "--branch", "--untracked-files=all"),
    ("rev-parse", "--verify", "HEAD"),
    ("rev-parse", "--git-dir"),
    ("rev-parse", "--git-common-dir"),
    ("diff", "--no-ext-diff", "--no-textconv", "--stat", "--"),
    ("diff", "--no-ext-diff", "--no-textconv", "--name-status", "--"),
    ("diff", "--cached", "--no-ext-diff", "--no-textconv", "--name-status", "--"),
    ("diff", "--check", "--"),
    ("ls-files", "--stage"),
})


def _git_environment() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "LC_ALL": "C",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_CONFIG_COUNT": "4",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.untrackedCache",
        "GIT_CONFIG_VALUE_1": "false",
        "GIT_CONFIG_KEY_2": "credential.helper",
        "GIT_CONFIG_VALUE_2": "",
        "GIT_CONFIG_KEY_3": "diff.external",
        "GIT_CONFIG_VALUE_3": "",
    }


def _run_git(
    root: Path,
    args: tuple[str, ...] | list[str],
    timeout_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    command = tuple(args)
    if command not in _GIT_COMMANDS:
        raise DiagnosticSecurityError("unregistered Git diagnostic command")
    try:
        return runner(
            ["git", "-C", str(root.resolve()), *command],
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=_git_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise DiagnosticUnavailableError("Git diagnostic timed out") from exc


def _bounded_completed(
    result: subprocess.CompletedProcess[str],
    policy: DiagnosticPolicy,
    label: str,
) -> str:
    stdout = str(result.stdout or "")
    stderr = str(result.stderr or "")
    if len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")) > policy.max_bytes:
        raise DiagnosticUnavailableError(f"{label} output exceeds configured cap")
    return stdout


def collect_repo_snapshot(
    request: ReadOnlyDiagnosticRequestV1,
    policy: DiagnosticPolicy,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if request.operation != "repo.snapshot":
        raise DiagnosticError("wrong operation for repository snapshot")
    root = _root_for(request, policy).resolve()

    def run(
        args: tuple[str, ...],
        label: str,
        *,
        allow_nonzero: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        completed = _run_git(root, args, policy.timeout_seconds, runner)
        _bounded_completed(completed, policy, label)
        if completed.returncode != 0 and not allow_nonzero:
            raise DiagnosticUnavailableError(f"{label} failed")
        return completed

    status_before = _bounded_completed(
        run(("status", "--porcelain=v2", "--branch", "--untracked-files=all"), "git status"),
        policy,
        "git status",
    )
    head = _bounded_completed(
        run(("rev-parse", "--verify", "HEAD"), "git head"), policy, "git head"
    ).strip()
    git_dir = _bounded_completed(
        run(("rev-parse", "--git-dir"), "git dir"), policy, "git dir"
    ).strip()
    git_common_dir = _bounded_completed(
        run(("rev-parse", "--git-common-dir"), "git common dir"),
        policy,
        "git common dir",
    ).strip()
    diff_stat = _bounded_completed(
        run(("diff", "--no-ext-diff", "--no-textconv", "--stat", "--"), "git diff stat"),
        policy,
        "git diff stat",
    )
    worktree_name_status = _bounded_completed(
        run(
            ("diff", "--no-ext-diff", "--no-textconv", "--name-status", "--"),
            "git diff names",
        ),
        policy,
        "git diff names",
    )
    cached_name_status = _bounded_completed(
        run(
            ("diff", "--cached", "--no-ext-diff", "--no-textconv", "--name-status", "--"),
            "git cached names",
        ),
        policy,
        "git cached names",
    )
    diff_check_result = run(("diff", "--check", "--"), "git diff check", allow_nonzero=True)
    diff_check = _bounded_completed(diff_check_result, policy, "git diff check")
    index = _bounded_completed(
        run(("ls-files", "--stage"), "git index"), policy, "git index"
    )
    status_after = _bounded_completed(
        run(("status", "--porcelain=v2", "--branch", "--untracked-files=all"), "git status"),
        policy,
        "git status",
    )
    submodules = sorted(
        {
            line.split("\t", 1)[-1]
            for line in index.splitlines()
            if line.startswith("160000 ") and "\t" in line
        }
    )
    return {
        "head": head,
        "git_dir": git_dir,
        "git_common_dir": git_common_dir,
        "status_porcelain_v2": status_after,
        "diff_stat": diff_stat,
        "worktree_name_status": worktree_name_status,
        "cached_name_status": cached_name_status,
        "diff_check": diff_check,
        "diff_check_exit_code": int(diff_check_result.returncode),
        "submodule_paths": submodules,
        "stale": status_before != status_after,
        "truncated": False,
        "redaction_applied": False,
    }
