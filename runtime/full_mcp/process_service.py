from __future__ import annotations

import hashlib
import os
import signal
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from .path_policy import PathPolicyError, WorkspacePathPolicy

MAX_OUTPUT_BYTES = 1024 * 1024
MAX_STDIN_BYTES = 1024 * 1024
_BLOCKED_SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "fish", "csh", "tcsh", "powershell", "pwsh", "cmd", "cmd.exe"}


class ProcessServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


class ShellPolicy:
    def __init__(self, *, env_allowlist: Sequence[str] = (), allowed_executables: Sequence[str] | None = None,
                 max_output_bytes: int = MAX_OUTPUT_BYTES, max_stdin_bytes: int = MAX_STDIN_BYTES) -> None:
        if isinstance(env_allowlist, (str, bytes)) or len(set(env_allowlist)) != len(tuple(env_allowlist)):
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "env allowlist is invalid")
        if allowed_executables is not None and isinstance(allowed_executables, (str, bytes)):
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "executable allowlist is invalid")
        if not isinstance(max_output_bytes, int) or max_output_bytes < 1 or not isinstance(max_stdin_bytes, int) or max_stdin_bytes < 1:
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "process bounds are invalid")
        self.env_allowlist = tuple(env_allowlist)
        self.allowed_executables = None if allowed_executables is None else frozenset(allowed_executables)
        self.max_output_bytes = max_output_bytes; self.max_stdin_bytes = max_stdin_bytes

    def validate_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "argv must be a non-empty list")
        values = tuple(argv)
        if any(not isinstance(v, str) or not v or "\x00" in v for v in values):
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "argv contains an invalid item")
        executable = Path(values[0]).name.lower()
        if executable in _BLOCKED_SHELLS:
            raise ProcessServiceError("COMMAND_NOT_ALLOWED", "shell wrappers are forbidden")
        if self.allowed_executables is not None and values[0] not in self.allowed_executables and Path(values[0]).name not in self.allowed_executables:
            raise ProcessServiceError("COMMAND_NOT_ALLOWED", "executable is not approved")
        return values

    def build_env(self, env: Mapping[str, str]) -> dict[str, str]:
        if not isinstance(env, Mapping):
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "env must be an object")
        safe: dict[str, str] = {}
        for key, value in env.items():
            if key not in self.env_allowlist or not isinstance(key, str) or not isinstance(value, str) or "\x00" in key + value:
                raise ProcessServiceError("COMMAND_NOT_ALLOWED", "environment override is not approved")
            safe[key] = value
        return safe


class ProcessService:
    def __init__(self, path_policy: WorkspacePathPolicy, *, shell_policy: ShellPolicy | None = None) -> None:
        self.path_policy = path_policy; self.shell_policy = shell_policy or ShellPolicy()

    def execute(self, *, argv: Sequence[str], cwd: str, timeout_seconds: int,
                stdin: str | None = None, env: Mapping[str, str] | None = None) -> dict[str, object]:
        args = self.shell_policy.validate_argv(argv)
        if not isinstance(cwd, str) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 1800:
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "cwd/timeout is invalid")
        if stdin is not None and not isinstance(stdin, str):
            raise ProcessServiceError("INPUT_SCHEMA_INVALID", "stdin must be text or null")
        stdin_bytes = b"" if stdin is None else stdin.encode("utf-8")
        if len(stdin_bytes) > self.shell_policy.max_stdin_bytes:
            raise ProcessServiceError("OUTPUT_LIMIT_EXCEEDED", "stdin exceeds approved bound")
        try:
            workdir = self.path_policy.resolve_read(cwd)
        except PathPolicyError as exc:
            raise ProcessServiceError("PATH_POLICY_VIOLATION", "cwd is outside approved workspace") from exc
        if not workdir.is_dir() or workdir.is_symlink():
            raise ProcessServiceError("PATH_POLICY_VIOLATION", "cwd must be a safe directory")
        safe_env = self.shell_policy.build_env({} if env is None else env)
        try:
            proc = subprocess.Popen(args, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    shell=False, env=safe_env, start_new_session=True)
        except (OSError, ValueError) as exc:
            raise ProcessServiceError("PROCESS_SPAWN_FAILED", "process could not be started") from exc
        timed_out = False
        try:
            stdout_b, stderr_b = proc.communicate(input=stdin_bytes if stdin is not None else None, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try:
                stdout_b, stderr_b = proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                stdout_b, stderr_b = proc.communicate()
        if len(stdout_b) > self.shell_policy.max_output_bytes or len(stderr_b) > self.shell_policy.max_output_bytes:
            raise ProcessServiceError("OUTPUT_LIMIT_EXCEEDED", "process output exceeds approved bound")
        try:
            stdout = stdout_b.decode("utf-8"); stderr = stderr_b.decode("utf-8")
        except UnicodeError as exc:
            raise ProcessServiceError("SECRET_OUTPUT_BLOCKED", "process output is not valid UTF-8") from exc
        return {"exit_code": int(proc.returncode), "stdout": stdout, "stderr": stderr,
                "timed_out": timed_out, "cancelled": False,
                "stdout_sha256": hashlib.sha256(stdout_b).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr_b).hexdigest()}
