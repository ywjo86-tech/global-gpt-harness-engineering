"""Immutable Full Plan authority core with controlled runtime binding overlay."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json

AUTHORITY_SCHEMA = "orchestration.production-run-authority.v1"
OVERLAY_SCHEMA = "orchestration.production-run-runtime-bindings.v1"
RUNTIME_GATE_FIELDS = frozenset({
    "manual_action_package_paths_by_lv",
    "manual_action_authorization_paths_by_lv",
})


class RunAuthorityError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _runtime_source_digest(root: Path) -> str:
    runtime = root / "runtime"
    if not runtime.is_dir() or runtime.is_symlink():
        return ""
    digest = hashlib.sha256()
    for path in sorted(runtime.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big")); digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big")); digest.update(data)
    return digest.hexdigest()


def executor_runtime_identity(harness_root: str | Path) -> dict[str, str]:
    root = Path(harness_root).resolve()
    common = _git(root, "rev-parse", "--git-common-dir")
    common_path = ""
    if common:
        candidate = Path(common)
        common_path = str(candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve())
    return {
        "schema_version": "orchestration.executor-runtime-identity.v1",
        "root": str(root),
        "head": _git(root, "rev-parse", "HEAD"),
        "branch": _git(root, "branch", "--show-current"),
        "git_common_dir": common_path,
        "runtime_source_sha256": _runtime_source_digest(root),
    }


def extract_runtime_bindings(job: Mapping[str, Any]) -> dict[str, dict[str, dict[str, str]]]:
    bindings: dict[str, dict[str, dict[str, str]]] = {}
    for gate in job.get("gates", []):
        if not isinstance(gate, Mapping) or not isinstance(gate.get("gate_id"), str):
            continue
        gate_bindings: dict[str, dict[str, str]] = {}
        for field in RUNTIME_GATE_FIELDS:
            value = gate.get(field)
            if value:
                gate_bindings[field] = dict(value)
        if gate_bindings:
            bindings[str(gate["gate_id"])] = gate_bindings
    return bindings


def authority_core(job: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(job))
    value.pop("authority_core_sha256", None)
    value.pop("authority_schema_version", None)
    gates = []
    for raw in value.get("gates", []):
        gate = dict(raw)
        for field in RUNTIME_GATE_FIELDS:
            gate.pop(field, None)
        gates.append(gate)
    value["gates"] = gates
    return value


def seal_authority_core(job: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(job))
    if "executor_runtime_identity" not in value:
        value["executor_runtime_identity"] = executor_runtime_identity(str(value.get("runtime_code_root") or value["harness_root"]))
    core = authority_core(value)
    core["authority_schema_version"] = AUTHORITY_SCHEMA
    digest_input = dict(core)
    digest_input.pop("authority_schema_version", None)
    core["authority_core_sha256"] = _digest(digest_input)
    return core


def validate_authority_core(job: Mapping[str, Any]) -> str:
    if job.get("authority_schema_version") != AUTHORITY_SCHEMA:
        raise RunAuthorityError("RUN_AUTHORITY_SCHEMA_MISSING")
    expected = job.get("authority_core_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise RunAuthorityError("RUN_AUTHORITY_DIGEST_MISSING")
    core = authority_core(job)
    actual = _digest(core)
    if actual != expected:
        raise RunAuthorityError("RUN_AUTHORITY_DRIFT")
    return expected


def runtime_binding_overlay_path(job: Mapping[str, Any]) -> Path:
    root = Path(str(job["harness_root"])).resolve()
    return (root / "_workspace" / "production-full-plan-jobs" / str(job["project_id"])
            / f"{job['run_id']}.runtime-bindings.json")


def _load_overlay(job: Mapping[str, Any]) -> dict[str, Any] | None:
    path = runtime_binding_overlay_path(job)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RunAuthorityError("RUNTIME_BINDING_OVERLAY_UNSAFE")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunAuthorityError("RUNTIME_BINDING_OVERLAY_CORRUPT") from exc
    if not isinstance(value, dict) or value.get("schema_version") != OVERLAY_SCHEMA:
        raise RunAuthorityError("RUNTIME_BINDING_OVERLAY_SCHEMA_MISMATCH")
    expected = value.get("overlay_sha256")
    unsigned = {k: v for k, v in value.items() if k != "overlay_sha256"}
    if expected != _digest(unsigned):
        raise RunAuthorityError("RUNTIME_BINDING_OVERLAY_DRIFT")
    if value.get("authority_core_sha256") != validate_authority_core(job):
        raise RunAuthorityError("RUNTIME_BINDING_AUTHORITY_MISMATCH")
    return value


def merge_runtime_bindings(job: Mapping[str, Any]) -> dict[str, Any]:
    validate_authority_core(job)
    merged = copy.deepcopy(dict(job))
    overlay = _load_overlay(job)
    if overlay is None:
        return merged
    by_gate = dict(overlay.get("bindings_by_gate") or {})
    gates = []
    for raw in merged.get("gates", []):
        gate = dict(raw)
        bindings = by_gate.get(str(gate.get("gate_id")), {})
        for field in RUNTIME_GATE_FIELDS:
            if field in bindings:
                gate[field] = dict(bindings[field])
        gates.append(gate)
    merged["gates"] = gates
    return merged


def bind_manual_action_paths(
    job: Mapping[str, Any], *, gate_id: str, lv_id: str,
    action_path: str, authorization_path: str,
) -> Path:
    authority_sha = validate_authority_core(job)
    existing = _load_overlay(job)
    sequence = int(existing.get("sequence", 0)) + 1 if existing else 1
    previous = str(existing.get("overlay_sha256", "")) if existing else ""
    by_gate = copy.deepcopy(dict(existing.get("bindings_by_gate") or {})) if existing else {}
    gate = dict(by_gate.get(gate_id) or {})
    packages = dict(gate.get("manual_action_package_paths_by_lv") or {})
    auths = dict(gate.get("manual_action_authorization_paths_by_lv") or {})
    old_package = packages.get(lv_id)
    old_auth = auths.get(lv_id)
    if old_package not in {None, action_path} or old_auth not in {None, authorization_path}:
        raise RunAuthorityError("RUNTIME_BINDING_CONFLICT")
    if old_package == action_path and old_auth == authorization_path:
        return runtime_binding_overlay_path(job)
    packages[lv_id] = action_path
    auths[lv_id] = authorization_path
    gate["manual_action_package_paths_by_lv"] = packages
    gate["manual_action_authorization_paths_by_lv"] = auths
    by_gate[gate_id] = gate
    payload = {
        "schema_version": OVERLAY_SCHEMA,
        "project_id": str(job["project_id"]),
        "run_id": str(job["run_id"]),
        "authority_core_sha256": authority_sha,
        "sequence": sequence,
        "previous_overlay_sha256": previous,
        "bindings_by_gate": by_gate,
    }
    payload["overlay_sha256"] = _digest(payload)
    path = runtime_binding_overlay_path(job)
    atomic_write_json(path, payload)
    return path


def validate_executor_runtime(job: Mapping[str, Any]) -> tuple[bool, str]:
    expected = job.get("executor_runtime_identity")
    if not isinstance(expected, Mapping):
        return False, "EXECUTOR_RUNTIME_IDENTITY_MISSING"
    current = executor_runtime_identity(str(job.get("runtime_code_root") or job["harness_root"]))
    if str(expected.get("root", "")) != current["root"]:
        return False, "EXECUTOR_RUNTIME_ROOT_DRIFT"
    expected_head = str(expected.get("head", ""))
    if expected_head and current["head"] != expected_head:
        return False, "EXECUTOR_GENERATION_DRIFT"
    expected_common = str(expected.get("git_common_dir", ""))
    if expected_common and current["git_common_dir"] != expected_common:
        return False, "EXECUTOR_GIT_IDENTITY_DRIFT"
    expected_runtime = str(expected.get("runtime_source_sha256", ""))
    if expected_runtime and current["runtime_source_sha256"] != expected_runtime:
        return False, "EXECUTOR_RUNTIME_SOURCE_DRIFT"
    return True, "PASS"
