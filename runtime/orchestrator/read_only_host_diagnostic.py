from __future__ import annotations

import errno
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .read_only_host_diagnostic_contract import (
    MAX_POLICY_BYTES,
    DiagnosticPolicy,
    ReadOnlyDiagnosticRequestV1,
)

_SENSITIVE_EXACT = frozenset({".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_VALUE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|token|credential|secret)\s*[:=]\s*([^\s,;}]+)")

_GIT_BASE_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
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
        return {
            "canonical_relative_path": PurePosixPath(request.relative_path).as_posix(),
            "start_line": request.start_line,
            "lines_returned": len(selected),
            "text": text,
            "redaction_applied": redaction_applied,
            "truncated": byte_truncated or range_truncated,
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
            kind, mode_class = "file", "regular"
        elif stat.S_ISDIR(info.st_mode):
            kind, mode_class = "directory", "directory"
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


def _run_git(root: Path, args: tuple[str, ...], timeout_seconds: int, runner=subprocess.run):
    if tuple(args) not in _GIT_COMMANDS:
        raise DiagnosticSecurityError("unregistered Git diagnostic command")
    return runner(
        ["git", "-C", str(root), *args],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env={**os.environ, **_GIT_BASE_ENV},
    )


def _bounded_command_text(text: str, limit: int) -> tuple[str, bool]:
    value = str(text or "")
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _parse_porcelain_v2_status(text: str) -> dict[str, Any]:
    branch = ""
    detached = False
    head = ""
    upstream = ""
    ahead = behind = 0
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in text.splitlines():
        if line.startswith("# branch.oid "):
            head = line[len("# branch.oid "):].strip()
        elif line.startswith("# branch.head "):
            branch = line[len("# branch.head "):].strip()
            if branch == "(detached)":
                detached, branch = True, ""
        elif line.startswith("# branch.upstream "):
            upstream = line[len("# branch.upstream "):].strip()
        elif line.startswith("# branch.ab "):
            fields = line.split()
            if len(fields) == 4:
                ahead = int(fields[2].lstrip("+"))
                behind = int(fields[3].lstrip("-"))
        elif line.startswith("? "):
            untracked.append(line[2:])
        elif line.startswith(("1 ", "2 ", "u ")):
            fields = line.split(" ", 2)
            if len(fields) < 3:
                continue
            xy = fields[1]
            fixed = 7 if line.startswith("1 ") else 8 if line.startswith("2 ") else 9
            parts = fields[2].split(" ", fixed)
            path = parts[-1].split("\t", 1)[0] if parts else ""
            if path and len(xy) >= 1 and xy[0] != ".":
                staged.append(path)
            if path and len(xy) >= 2 and xy[1] != ".":
                unstaged.append(path)
    return {
        "branch": branch,
        "detached": detached,
        "head": head if head != "(initial)" else "",
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "staged_paths": sorted(set(staged)),
        "unstaged_paths": sorted(set(unstaged)),
        "untracked_paths": sorted(set(untracked)),
    }


def _parse_name_status(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            paths.append(fields[-1])
    return sorted(set(paths))


def collect_repo_snapshot(
    request: ReadOnlyDiagnosticRequestV1,
    policy: DiagnosticPolicy,
    *,
    runner=subprocess.run,
) -> dict[str, Any]:
    if request.operation != "repo.snapshot":
        raise DiagnosticExecutionError("wrong operation for repository snapshot")
    root = policy.root(request.root_id)

    def call(args: tuple[str, ...], label: str) -> str:
        completed = _run_git(root, args, policy.timeout_seconds, runner)
        stdout, stdout_truncated = _bounded_command_text(getattr(completed, "stdout", ""), MAX_POLICY_BYTES)
        _stderr, stderr_truncated = _bounded_command_text(getattr(completed, "stderr", ""), MAX_POLICY_BYTES)
        if stdout_truncated or stderr_truncated:
            raise DiagnosticExecutionError(f"Git {label} output exceeds diagnostic limit")
        if int(getattr(completed, "returncode", 1)) != 0:
            raise DiagnosticExecutionError(f"Git {label} failed")
        return stdout

    status_args = ("status", "--porcelain=v2", "--branch", "--untracked-files=all")
    before = call(status_args, "status")
    status = _parse_porcelain_v2_status(before)
    verified_head = call(("rev-parse", "--verify", "HEAD"), "HEAD").strip()
    git_dir = call(("rev-parse", "--git-dir"), "git-dir").strip()
    git_common_dir = call(("rev-parse", "--git-common-dir"), "git-common-dir").strip()
    diff_stat = call(("diff", "--no-ext-diff", "--no-textconv", "--stat", "--"), "diff-stat")
    unstaged_names = call(("diff", "--no-ext-diff", "--no-textconv", "--name-status", "--"), "diff-name-status")
    staged_names = call(("diff", "--cached", "--no-ext-diff", "--no-textconv", "--name-status", "--"), "cached-name-status")
    diff_check = call(("diff", "--check", "--"), "diff-check")
    ls_stage = call(("ls-files", "--stage"), "ls-files")
    after = call(status_args, "status")

    stale = before != after
    if not stale:
        status = _parse_porcelain_v2_status(after)
    status["head"] = verified_head or status["head"]
    status["git_dir"] = git_dir
    status["git_common_dir"] = git_common_dir
    status["linked_worktree"] = git_dir != git_common_dir
    status["submodule_present"] = any(line.startswith("160000 ") for line in ls_stage.splitlines())
    status["diff_stat"] = diff_stat
    status["diff_check"] = diff_check
    status["unstaged_paths"] = _parse_name_status(unstaged_names) or status["unstaged_paths"]
    status["staged_paths"] = _parse_name_status(staged_names) or status["staged_paths"]
    status["stale"] = stale
    status["truncated"] = False
    return status
