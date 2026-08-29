from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence

from .lv_execution_package import canonical_json_bytes


class FixedRunnerError(ValueError):
    pass


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_FORBIDDEN_META = re.compile(r"[;&|`$<>\n\r\x00]")
_FORBIDDEN_WORDS = {
    "push", "reset", "rebase", "clean", "checkout", "rm", "sudo", "apparmor_parser",
    "curl", "wget", "ssh", "scp", "pip", "pip3", "npm", "apt", "apt-get", "dnf", "yum",
    "systemctl", "service", "mount", "umount", "chown", "chmod", "docker", "podman",
}
_PAYLOAD_FIELDS = {
    "schema_version", "requirements_sha256", "registry_sha256", "project_id", "gate_id", "lv_id",
    "run_id", "branch", "head", "owned_files", "command_id", "input_sha256",
}


@dataclass(frozen=True)
class RegisteredCommand:
    command_id: str
    argv: tuple[str, ...]
    lifecycle_stage: str
    # Typed values may be substituted only for explicitly registered names.
    parameter_names: tuple[str, ...] = ()


# The registry is code-owned. A manifest can select an ID, never supply argv.
COMMAND_REGISTRY: Mapping[str, RegisteredCommand] = {
    "lv.package": RegisteredCommand("lv.package", ("python3", "-m", "runtime.orchestrator.cli", "lv-package"), "PACKAGE"),
    "lv.preflight": RegisteredCommand("lv.preflight", ("python3", "-m", "runtime.orchestrator.cli", "lv-preflight"), "PREFLIGHT"),
    "lv.worker": RegisteredCommand(
        "lv.worker",
        ("python3", "-m", "runtime.orchestrator.worker_runner", "--request-file", "{request_file}", "--result-file", "{result_file}"),
        "WORKER",
        ("request_file", "result_file"),
    ),
    "lv.review": RegisteredCommand("lv.review", ("python3", "-m", "runtime.orchestrator.cli", "lv-review"), "REVIEW"),
    "lv.remediation": RegisteredCommand("lv.remediation", ("python3", "-m", "runtime.orchestrator.cli", "lv-remediation-review"), "REMEDIATION"),
    "lv.checkpoint": RegisteredCommand("lv.checkpoint", ("python3", "-m", "runtime.orchestrator.cli", "status"), "CHECKPOINT"),
    "lv.exit": RegisteredCommand("lv.exit", ("python3", "-m", "runtime.orchestrator.cli", "gate"), "EXIT"),
    "lv.handoff": RegisteredCommand("lv.handoff", ("python3", "-m", "runtime.orchestrator.cli", "status"), "HANDOFF"),
}


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def registry_sha256(registry: Mapping[str, RegisteredCommand] = COMMAND_REGISTRY) -> str:
    return _hash({key: {"argv": list(item.argv), "stage": item.lifecycle_stage,
                        "parameter_names": list(item.parameter_names)} for key, item in sorted(registry.items())})


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise FixedRunnerError(f"unsafe {label}")
    return value


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or _FORBIDDEN_META.search(value) or "\\" in value:
        raise FixedRunnerError("unsafe owned file")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise FixedRunnerError("unsafe owned file")
    return value


def _validate_command(command: RegisteredCommand) -> None:
    if not command.argv or any(not isinstance(arg, str) or not arg or _FORBIDDEN_META.search(arg) for arg in command.argv):
        raise FixedRunnerError("registry contains unsafe argv")
    lowered = {Path(arg).name.lower() for arg in command.argv}
    if lowered & _FORBIDDEN_WORDS:
        raise FixedRunnerError("registry contains a forbidden action")
    if len(set(command.parameter_names)) != len(command.parameter_names):
        raise FixedRunnerError("registry contains duplicate parameter names")
    for name in command.parameter_names:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise FixedRunnerError("registry contains unsafe parameter name")
    placeholders = {match.group(1) for arg in command.argv for match in [re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", arg)] if match}
    if placeholders != set(command.parameter_names):
        raise FixedRunnerError("registry parameter template mismatch")


def seal_action_manifest(*, requirements_sha256: str, project_id: str, gate_id: str, lv_id: str,
                         run_id: str, branch: str, head: str, owned_files: Sequence[str],
                         command_id: str, input_sha256: str,
                         parameters: Mapping[str, str] | None = None,
                         registry: Mapping[str, RegisteredCommand] = COMMAND_REGISTRY) -> dict[str, object]:
    command = registry.get(command_id)
    if command is None:
        raise FixedRunnerError("unregistered command ID")
    _validate_command(command)
    if not _SHA256.fullmatch(requirements_sha256) or not _SHA256.fullmatch(input_sha256):
        raise FixedRunnerError("invalid SHA-256 binding")
    if not _HEAD.fullmatch(head):
        raise FixedRunnerError("invalid HEAD binding")
    payload: dict[str, object] = {
        "schema_version": "orchestration.fixed-action.v1",
        "requirements_sha256": requirements_sha256,
        "registry_sha256": registry_sha256(registry),
        "project_id": _safe_id(project_id, "project ID"),
        "gate_id": _safe_id(gate_id, "Gate ID"),
        "lv_id": _safe_id(lv_id, "LV ID"),
        "run_id": _safe_id(run_id, "run ID"),
        "branch": _safe_id(branch, "branch"),
        "head": head,
        "owned_files": [_safe_relative(item) for item in owned_files],
        "command_id": command_id,
        "input_sha256": input_sha256,
    }
    if len(set(payload["owned_files"])) != len(payload["owned_files"]):
        raise FixedRunnerError("duplicate owned file")
    supplied = {} if parameters is None else dict(parameters)
    unknown = set(supplied) - set(command.parameter_names)
    missing = set(command.parameter_names) - set(supplied)
    if unknown:
        raise FixedRunnerError("unknown command parameter")
    if missing:
        raise FixedRunnerError("missing command parameter")
    for name, value in supplied.items():
        if not isinstance(value, str) or not value or _FORBIDDEN_META.search(value):
            raise FixedRunnerError("unsafe command parameter")
        if name.endswith("_file"):
            candidate = Path(value)
            if not candidate.is_absolute() or ".." in candidate.parts:
                raise FixedRunnerError("unsafe command parameter path")
        else:
            _safe_id(value, f"command parameter {name}")
    if supplied:
        payload["parameters"] = supplied
    return {"payload": payload, "manifest_sha256": _hash(payload)}


def validate_action_manifest(manifest: Mapping[str, object], *, expected_project_id: str,
                             expected_requirements_sha256: str,
                             registry: Mapping[str, RegisteredCommand] = COMMAND_REGISTRY) -> RegisteredCommand:
    if set(manifest) != {"payload", "manifest_sha256"} or not isinstance(manifest.get("payload"), dict):
        raise FixedRunnerError("invalid action manifest envelope")
    payload = manifest["payload"]
    assert isinstance(payload, dict)
    if not set(payload).issubset(_PAYLOAD_FIELDS | {"parameters"}) or not _PAYLOAD_FIELDS.issubset(payload) or payload.get("schema_version") != "orchestration.fixed-action.v1":
        raise FixedRunnerError("invalid action manifest fields")
    if manifest["manifest_sha256"] != _hash(payload):
        raise FixedRunnerError("action manifest drift")
    if payload.get("requirements_sha256") != expected_requirements_sha256:
        raise FixedRunnerError("requirements SHA drift")
    if payload.get("project_id") != expected_project_id:
        raise FixedRunnerError("cross-project action manifest")
    if payload.get("registry_sha256") != registry_sha256(registry):
        raise FixedRunnerError("runner registry drift")
    command_id = payload.get("command_id")
    if not isinstance(command_id, str) or command_id not in registry:
        raise FixedRunnerError("unregistered command ID")
    command = registry[command_id]
    _validate_command(command)
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict) or set(parameters) != set(command.parameter_names):
        raise FixedRunnerError("invalid command parameters")
    for name, value in parameters.items():
        if not isinstance(value, str) or not value or _FORBIDDEN_META.search(value):
            raise FixedRunnerError("unsafe command parameter")
        if name.endswith("_file") and (not Path(value).is_absolute() or ".." in Path(value).parts):
            raise FixedRunnerError("unsafe command parameter path")
    # Re-validate every untrusted field even though the envelope hash matches.
    for field in ("project_id", "gate_id", "lv_id", "run_id", "branch"):
        _safe_id(payload.get(field), field)  # type: ignore[arg-type]
    if not _HEAD.fullmatch(str(payload.get("head", ""))) or not _SHA256.fullmatch(str(payload.get("input_sha256", ""))):
        raise FixedRunnerError("invalid action binding")
    owned = payload.get("owned_files")
    if not isinstance(owned, list) or any(not isinstance(item, str) for item in owned):
        raise FixedRunnerError("invalid owned-file binding")
    for item in owned:
        _safe_relative(item)
    return command


def _append_audit(path: Path, entry: Mapping[str, object]) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise FixedRunnerError("unsafe audit log")
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json_bytes(dict(entry)) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def run_sealed_action(manifest: Mapping[str, object], *, expected_project_id: str,
                      expected_requirements_sha256: str, audit_path: str | Path,
                      executor: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
                      registry: Mapping[str, RegisteredCommand] = COMMAND_REGISTRY,
                      execution_root: str | Path | None = None) -> dict[str, object]:
    command = validate_action_manifest(manifest, expected_project_id=expected_project_id,
                                       expected_requirements_sha256=expected_requirements_sha256,
                                       registry=registry)
    payload = manifest["payload"]
    assert isinstance(payload, dict)
    parameters = payload.get("parameters", {})
    if execution_root is not None:
        root = Path(execution_root).resolve()
        if not root.is_dir():
            raise FixedRunnerError("execution root is not a directory")
        for name, value in parameters.items():
            if not name.endswith("_file"):
                continue
            candidate = Path(value)
            if not candidate.is_absolute() or candidate.parent.resolve() != candidate.parent:
                raise FixedRunnerError("unsafe command parameter path")
            if not candidate.is_relative_to(root):
                raise FixedRunnerError("command parameter escapes execution root")
            if candidate.is_symlink():
                raise FixedRunnerError("command parameter may not be a symlink")
    argv = [parameters.get(arg[1:-1], arg) if isinstance(arg, str) and arg.startswith("{") and arg.endswith("}") else arg for arg in command.argv]
    completed = executor(argv, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    stdout = bytes(completed.stdout or b"")
    stderr = bytes(completed.stderr or b"")
    artifact_sha = hashlib.sha256(stdout + b"\0" + stderr).hexdigest()
    audit = {
        "schema_version": "orchestration.fixed-run.audit.v1",
        "command_id": command.command_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "input_sha256": payload["input_sha256"],
        "exit_code": int(completed.returncode),
        "artifact_sha256": artifact_sha,
        "project_id": payload["project_id"],
        "gate_id": payload["gate_id"],
        "lv_id": payload["lv_id"],
        "run_id": payload["run_id"],
    }
    audit["audit_entry_sha256"] = _hash(audit)
    _append_audit(Path(audit_path), audit)
    return {"command_id": command.command_id, "exit_code": int(completed.returncode), "artifact_sha256": artifact_sha}
