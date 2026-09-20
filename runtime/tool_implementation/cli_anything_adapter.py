"""Bounded execution adapter for already-generated CLI implementations.

This module is an implementation layer only. It has no authority to register
operations, select providers, approve scope, declare completion, or notify users.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .manifest import ToolImplementationError, ToolImplementationManifest, validate_manifest

_MAX_TIMEOUT = 60
_DEFAULT_OUTPUT_LIMIT = 256 * 1024

@dataclass(frozen=True, slots=True)
class QualificationResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    argv: tuple[str, ...]
    control_authority: str = "NONE"


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ToolImplementationError("CLI relative path is unsafe")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != value:
        raise ToolImplementationError("CLI relative path is unsafe")
    return candidate.as_posix()


def _validated_arguments(manifest: ToolImplementationManifest, arguments: Mapping[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    if not isinstance(arguments, Mapping):
        raise ToolImplementationError("CLI arguments must be an object")
    properties = manifest.input_schema.get("properties", {})
    required = tuple(manifest.input_schema.get("required", ()))
    if any(key not in arguments for key in required) or any(key not in properties for key in arguments):
        raise ToolImplementationError("CLI arguments violate the closed manifest schema")
    result: dict[str, Any] = {}
    for key, value in arguments.items():
        spec = properties[key]
        if not isinstance(spec, Mapping):
            raise ToolImplementationError("CLI property schema is invalid")
        expected = spec.get("type")
        if expected == "string":
            if not isinstance(value, str) or "\x00" in value:
                raise ToolImplementationError("CLI string argument is invalid")
            result[key] = _safe_relative_path(value) if spec.get("x-cli-kind") == "relative_path" else value
        elif expected == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ToolImplementationError("CLI integer argument is invalid")
            result[key] = value
        elif expected == "boolean":
            if not isinstance(value, bool):
                raise ToolImplementationError("CLI boolean argument is invalid")
            result[key] = value
        else:
            raise ToolImplementationError("unsupported bounded CLI argument type")
    return result


def build_cli_argv(manifest: ToolImplementationManifest, arguments: Mapping[str, Any]) -> list[str]:
    values = _validated_arguments(manifest, arguments)
    subcommand = values.pop("subcommand", None)
    if not isinstance(subcommand, str) or subcommand not in tuple(manifest.allowed_subcommands):
        raise ToolImplementationError("subcommand is not allowlisted")
    argv = [manifest.allowed_argv0, subcommand]
    for key in sorted(values):
        value = values[key]
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            if value:
                argv.append(flag)
        else:
            argv.append(f"{flag}={value}")
    return argv


def _artifact_sha(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _isolated_env(cwd: Path) -> dict[str, str]:
    home = cwd / ".gch-cli-home"
    xdg = cwd / ".gch-cli-xdg"
    home.mkdir(mode=0o700, exist_ok=True); xdg.mkdir(mode=0o700, exist_ok=True)
    return {
        "HOME": str(home), "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_CACHE_HOME": str(xdg / "cache"), "XDG_DATA_HOME": str(xdg / "data"),
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    }


def dry_run(manifest: ToolImplementationManifest, arguments: Mapping[str, Any], *, cwd: Path) -> QualificationResult:
    root = Path(cwd).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ToolImplementationError("CLI working directory is unsafe")
    return QualificationResult("DRY_RUN", None, "", "", tuple(build_cli_argv(manifest, arguments)))


def run_preflight(manifest: ToolImplementationManifest, arguments: Mapping[str, Any], *, cwd: Path,
                  timeout: int = 20, max_output_bytes: int = _DEFAULT_OUTPUT_LIMIT) -> QualificationResult:
    root = Path(cwd).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ToolImplementationError("CLI working directory is unsafe")
    argv = build_cli_argv(manifest, arguments)
    executable = Path(manifest.allowed_argv0)
    actual = _artifact_sha(executable)
    if actual is None or not os.access(executable, os.X_OK):
        return QualificationResult("UNAVAILABLE", None, "", "executable unavailable", tuple(argv))
    if actual != manifest.generated_artifact_sha256:
        return QualificationResult("ARTIFACT_MISMATCH", None, "", "artifact digest mismatch", tuple(argv))
    if not isinstance(timeout, int) or timeout <= 0 or timeout > _MAX_TIMEOUT:
        raise ToolImplementationError("CLI timeout is outside the bounded policy")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise ToolImplementationError("CLI output limit is invalid")
    try:
        completed = subprocess.run(argv, cwd=root, env=_isolated_env(root), shell=False,
                                   capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return QualificationResult("UNAVAILABLE" if isinstance(exc, OSError) else "TIMEOUT", None, "", str(exc), tuple(argv))
    stdout_raw = bytes(completed.stdout); stderr_raw = bytes(completed.stderr)
    overflow = len(stdout_raw) > max_output_bytes or len(stderr_raw) > max_output_bytes
    stdout = stdout_raw[:max_output_bytes].decode("utf-8", errors="replace")
    stderr = stderr_raw[:max_output_bytes].decode("utf-8", errors="replace")
    status = "OUTPUT_LIMIT_EXCEEDED" if overflow else ("PASS" if completed.returncode == 0 else "FAIL")
    return QualificationResult(status, completed.returncode, stdout, stderr, tuple(argv))
