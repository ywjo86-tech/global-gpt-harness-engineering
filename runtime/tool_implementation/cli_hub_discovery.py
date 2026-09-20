"""Bounded, read-only CLI-Hub discovery with no control authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .manifest import ToolImplementationError

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_SHELL_META = re.compile(r"[`$;|&<>\n\r\x00]")
_MAX_TIMEOUT = 60
_DEFAULT_OUTPUT_LIMIT = 256 * 1024


@dataclass(frozen=True, slots=True)
class CliHubDiscoveryResult:
    status: str
    returncode: int | None
    payload: Any
    stdout: str
    stderr: str
    argv: tuple[str, ...]
    control_authority: str = "NONE"


def _artifact_sha(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_text(value: str, label: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length or _SHELL_META.search(value):
        raise ToolImplementationError(f"unsafe CLI-Hub {label}")
    return value


def _validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    values = tuple(argv)
    if not values:
        raise ToolImplementationError("CLI-Hub discovery command is empty")
    if any(not isinstance(item, str) for item in values):
        raise ToolImplementationError("CLI-Hub discovery arguments must be strings")
    for item in values:
        _safe_text(item, "argument", max_length=512)

    command = values[0]
    if command == "list":
        allowed = {"--json"}
        for item in values[1:]:
            if item in allowed:
                continue
            if item.startswith("--category="):
                _safe_text(item.split("=", 1)[1], "category")
                continue
            if item.startswith("--source=") and item.split("=", 1)[1] in {"harness", "public", "npm", "all"}:
                continue
            raise ToolImplementationError("unsupported CLI-Hub list argument")
        return values
    if command in {"search", "can"}:
        positional = [item for item in values[1:] if not item.startswith("--")]
        flags = [item for item in values[1:] if item.startswith("--")]
        if len(positional) != 1 or any(item != "--json" for item in flags):
            raise ToolImplementationError(f"unsupported CLI-Hub {command} arguments")
        _safe_text(positional[0], command)
        return values
    if command == "info":
        if len(values) != 2 or not _SAFE_ID.fullmatch(values[1]):
            raise ToolImplementationError("unsupported CLI-Hub info arguments")
        return values
    if command != "matrix" or len(values) < 2:
        raise ToolImplementationError("CLI-Hub side-effecting or unsupported command blocked")

    subcommand = values[1]
    rest = values[2:]
    if subcommand == "list":
        if any(item != "--json" for item in rest):
            raise ToolImplementationError("unsupported CLI-Hub matrix list arguments")
        return values
    if subcommand == "search":
        positional = [item for item in rest if not item.startswith("--")]
        flags = [item for item in rest if item.startswith("--")]
        if len(positional) != 1 or any(item != "--json" for item in flags):
            raise ToolImplementationError("unsupported CLI-Hub matrix search arguments")
        _safe_text(positional[0], "matrix search")
        return values
    if subcommand == "preflight":
        if not rest or not _SAFE_ID.fullmatch(rest[0]):
            raise ToolImplementationError("CLI-Hub matrix preflight requires a safe matrix name")
        for item in rest[1:]:
            if item in {"--offline", "--summary", "--json"}:
                continue
            if item.startswith("--capability=") or item.startswith("--recipe="):
                if not _SAFE_ID.fullmatch(item.split("=", 1)[1]):
                    raise ToolImplementationError("unsafe CLI-Hub matrix selector")
                continue
            raise ToolImplementationError("unsupported CLI-Hub matrix preflight argument")
        return values
    raise ToolImplementationError("CLI-Hub side-effecting or unsupported matrix command blocked")


def _isolated_env(cwd: Path) -> dict[str, str]:
    home = cwd / ".gch-cli-hub-home"
    xdg = cwd / ".gch-cli-hub-xdg"
    home.mkdir(mode=0o700, exist_ok=True)
    xdg.mkdir(mode=0o700, exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_CACHE_HOME": str(xdg / "cache"),
        "XDG_DATA_HOME": str(xdg / "data"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CLI_HUB_NO_ANALYTICS": "1",
    }


class CliHubDiscoveryAdapter:
    """Informational CLI-Hub adapter; mutation/install/launch verbs do not exist here."""

    def __init__(
        self,
        executable: str | Path,
        *,
        artifact_sha256: str,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        timeout: int = 20,
        max_output_bytes: int = _DEFAULT_OUTPUT_LIMIT,
    ) -> None:
        self.executable = Path(executable).expanduser().absolute()
        if not _SHA256.fullmatch(str(artifact_sha256)):
            raise ToolImplementationError("CLI-Hub artifact digest is invalid")
        if not isinstance(timeout, int) or timeout <= 0 or timeout > _MAX_TIMEOUT:
            raise ToolImplementationError("CLI-Hub timeout is outside the bounded policy")
        if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
            raise ToolImplementationError("CLI-Hub output limit is invalid")
        self.artifact_sha256 = str(artifact_sha256)
        self.runner = runner
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    def discover(self, argv: Sequence[str], *, cwd: str | Path) -> CliHubDiscoveryResult:
        args = _validate_argv(argv)
        root = Path(cwd).resolve()
        if not root.is_dir() or root.is_symlink():
            raise ToolImplementationError("CLI-Hub working directory is unsafe")
        command = (str(self.executable), *args)
        actual = _artifact_sha(self.executable)
        if actual is None or not os.access(self.executable, os.X_OK):
            return CliHubDiscoveryResult("UNAVAILABLE", None, None, "", "executable unavailable", command)
        if actual != self.artifact_sha256:
            return CliHubDiscoveryResult("ARTIFACT_MISMATCH", None, None, "", "artifact digest mismatch", command)
        try:
            completed = self.runner(
                list(command), cwd=root, env=_isolated_env(root), shell=False,
                capture_output=True, timeout=self.timeout, check=False,
            )
        except OSError as exc:
            return CliHubDiscoveryResult("UNAVAILABLE", None, None, "", str(exc), command)
        except subprocess.TimeoutExpired as exc:
            return CliHubDiscoveryResult("TIMEOUT", None, None, "", str(exc), command)
        stdout_raw = bytes(completed.stdout or b"")
        stderr_raw = bytes(completed.stderr or b"")
        overflow = len(stdout_raw) > self.max_output_bytes or len(stderr_raw) > self.max_output_bytes
        stdout = stdout_raw[: self.max_output_bytes].decode("utf-8", errors="replace")
        stderr = stderr_raw[: self.max_output_bytes].decode("utf-8", errors="replace")
        payload: Any = None
        if stdout.strip():
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = {"text": stdout}
        if overflow:
            status = "OUTPUT_LIMIT_EXCEEDED"
        elif completed.returncode == 0:
            status = "PASS"
        elif completed.returncode == 3 and args[:2] == ("matrix", "preflight"):
            status = "PARTIAL"
        else:
            status = "FAIL"
        return CliHubDiscoveryResult(status, int(completed.returncode), payload, stdout, stderr, command)
