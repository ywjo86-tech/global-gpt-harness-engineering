from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import signal
import stat
from dataclasses import dataclass
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_VENV_READ_ONLY = "PROJECT_VENV_READ_ONLY"
IMMUTABLE_EXTERNAL_INTERPRETER = "IMMUTABLE_EXTERNAL_INTERPRETER"

@dataclass(frozen=True)
class InterpreterPolicy:
    policy_id: str
    project_id: str
    interpreter: str
    allowed_root: str
    executable_sha256: str
    required_capabilities: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()

def validate_interpreter_policy(policy: dict[str, Any], *, project_id: str, registry_sha256: str | None = None) -> InterpreterPolicy:
    required = {"schema_version", "policy_id", "project_id", "interpreter", "allowed_root", "executable_sha256", "required_capabilities", "permissions", "registry_sha256"}
    if set(policy) != required or policy.get("schema_version") != "orchestration.interpreter-policy.v1":
        raise LVReviewError("interpreter policy schema mismatch")
    if policy.get("project_id") != project_id or (registry_sha256 is not None and policy.get("registry_sha256") != registry_sha256):
        raise LVReviewError("interpreter policy binding mismatch")
    if policy.get("policy_id") not in {PROJECT_VENV_READ_ONLY, IMMUTABLE_EXTERNAL_INTERPRETER}:
        raise LVReviewError("unknown interpreter policy")
    if not isinstance(policy.get("required_capabilities"), list) or not isinstance(policy.get("permissions"), list):
        raise LVReviewError("interpreter policy capabilities are invalid")
    path = Path(str(policy["interpreter"])).resolve()
    allowed = Path(str(policy["allowed_root"])).resolve()
    if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK) or allowed not in path.parents and path != allowed:
        raise LVReviewError("interpreter policy executable is unsafe")
    if policy["policy_id"] == IMMUTABLE_EXTERNAL_INTERPRETER and Path(project_id).resolve() in path.parents:
        raise LVReviewError("external interpreter is inside project root")
    if _sha256(path.read_bytes()) != policy["executable_sha256"]:
        raise LVReviewError("interpreter policy fingerprint drift")
    return InterpreterPolicy(policy["policy_id"], project_id, str(path), str(allowed), policy["executable_sha256"], tuple(policy["required_capabilities"]), tuple(policy["permissions"]))

from .contract_adapter import evaluate_canonical_state, load_project_mapping
from .lv_execution_package import (
    LVExecutionPackageError,
    _index_fingerprint,
    _ledger_binding,
    _safe_run_id,
    _tracked_content_fingerprint,
    canonical_json_bytes,
    validate_worker_result,
)


REVIEW_SCHEMA_VERSION = "orchestration.lv_reviewer.report.v1"
REVIEW_STATUS_SCHEMA_VERSION = "orchestration.lv_reviewer.status.v1"
PREFLIGHT_EVIDENCE_SCHEMA_VERSION = "orchestration.lv_preflight.evidence.v1"
PREFLIGHT_STATUS_SCHEMA_VERSION = "orchestration.lv_preflight.status.v1"
MAX_RESULT_BYTES = 1024 * 1024
RESULT_PREFIX = "harness-lv-worker-result-"
RESULT_SUFFIX = ".json"
RESULT_STATUSES = {"completed", "partial", "failed", "blocked", "aborted"}
_FORBIDDEN_CHANGE_CODES = {"R", "C", "T", "U"}
LEGACY_REVIEW_CONTRACTS: dict[str, dict[str, str]] = {
    "wallet-g1-lv3-1-20260826-01": {
        "reviewer.report.json": "9c7033236bcb88db5ecd49d1ca1ea3a19a08748e1aa8b38c8697ffba522dfd01",
        "reviewer.report.sha256": "092b40b7242c5c1968baa6f1c55ad0624d3f8351df23dde7d4396099a089d366",
        "review.status": "3c147ff4634afb59cd4513d57aba6a710f565e0db1763782171b1cfb44f3873d",
        "worker.result.json": "d27f1e0fe59862a9616703f0abc35c683d2ccdad70ed7c51ec8e12d51788989b",
        "worker.result.sha256": "3d484a559b2e6961e6da1c1f196e9c1dc1d3261e6ca88c3d4d4349fc5a81b32b",
    }
}
PRIOR_ATTEMPT_CONTRACTS: dict[str, dict[int, dict[str, str]]] = {
    "wallet-g1-lv3-1-20260826-01": {
        2: {
            "reviewer.report.json": "3f274fdf877c9a1bfa3eb853a40f0859a188a1d824e814b1aac3eb4ef80ee5fd",
            "reviewer.report.sha256": "9b8df887dd0c368b3f944eccb554777a6fd5da323506d862585093cbb68100b7",
            "review.status": "d9f33cad41c6bd29c9e93501c79831efbb94c33b88cb3934132f225f3489cc07",
            "worker.result.json": "d27f1e0fe59862a9616703f0abc35c683d2ccdad70ed7c51ec8e12d51788989b",
            "worker.result.sha256": "3d484a559b2e6961e6da1c1f196e9c1dc1d3261e6ca88c3d4d4349fc5a81b32b",
        }
    }
}
REVIEW_REPORT_FIELDS = {
    "schema_version", "run_id", "project", "gate", "lv", "reviewed_at", "verdict", "hard_stop",
    "review_attempt", "worker_attempt", "package_manifest_sha256", "preflight_evidence_sha256",
    "worker_result_sha256", "baseline_wallet_head", "current_wallet_head", "canonical_plan", "owned_files",
    "actual_changed_files", "actual_created_files", "actual_modified_files", "actual_deleted_files",
    "review_only_reexecution", "reran_worker", "prior_review_lineage", "independent_checks",
    "interpreter_before", "interpreter_after", "git_evidence", "violations", "blockers", "reasons",
    "owned_content_evidence",
}
LEGACY_REVIEW_REPORT_FIELDS = REVIEW_REPORT_FIELDS - {"owned_content_evidence"}
REVIEW_STATUS_FIELDS = {
    "schema_version", "run_id", "review_attempt", "worker_attempt", "verdict", "hard_stop",
    "reviewer_report_sha256", "package_manifest_sha256", "preflight_evidence_sha256",
    "worker_result_sha256", "review_only_reexecution", "reran_worker",
}


class LVReviewError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _harness_root() -> Path:
    return Path(os.environ.get("HARNESS_RUNTIME_ROOT", str(Path(__file__).resolve().parents[2]))).resolve()


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode:
        raise LVReviewError(f"git command failed: {' '.join(args)}")
    return completed.stdout


def _canonical_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LVReviewError(f"invalid JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise LVReviewError(f"JSON object required: {path.name}")
    return payload


def _project_root_for(project_id: str) -> Path:
    _safe_run_id(project_id)
    root = (_harness_root().parent / project_id).resolve()
    expected_parent = _harness_root().parent.resolve()
    if root.parent != expected_parent or root.name != project_id or not root.is_dir():
        raise LVReviewError("mapped project root is invalid")
    return root


def _package_root(run_id: str) -> Path:
    _safe_run_id(run_id)
    return _harness_root() / "_workspace" / "orchestration-runs" / run_id


def _result_path(run_id: str) -> Path:
    _safe_run_id(run_id)
    return Path("/tmp") / f"{RESULT_PREFIX}{run_id}{RESULT_SUFFIX}"


def parse_review_attempt(value: object) -> int:
    if isinstance(value, bool):
        raise LVReviewError("review attempt must be a canonical positive integer")
    if isinstance(value, int):
        attempt = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        attempt = int(value)
    else:
        raise LVReviewError("review attempt must be a canonical positive integer")
    if attempt <= 0:
        raise LVReviewError("review attempt must be a canonical positive integer")
    return attempt


def _results_root(run_id: str, review_attempt: int) -> Path:
    _safe_run_id(run_id)
    attempt = parse_review_attempt(review_attempt)
    return _harness_root() / "_workspace" / "orchestration-results" / run_id / f"attempt-{attempt:02d}"


def _preflight_root(run_id: str) -> Path:
    _safe_run_id(run_id)
    return _harness_root() / "_workspace" / "orchestration-preflights" / run_id


def _assert_package(package_root: Path, run_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    expected = {
        "package.manifest.json",
        "package.manifest.sha256",
        "package.input.json",
        "worker_prompt.md",
        "source_snapshot.json",
        "package.status",
    }
    if not package_root.is_dir() or package_root.is_symlink():
        raise LVReviewError("sealed package directory is missing or unsafe")
    entries = list(package_root.iterdir())
    names = {entry.name for entry in entries}
    # Registered worker execution materializes request/result beside the
    # immutable six-file package.  They are separately schema-bound below and
    # are not part of the package manifest itself.
    allowed = expected | {"worker.request.json", "worker.result.json", "executor.process.json", "worker_handoff.md", "handoff_report.md", "preflight"}
    if not expected.issubset(names) or not names.issubset(allowed) or not all((entry.is_dir() and entry.name == "preflight") or (entry.is_file() and not entry.is_symlink()) for entry in entries):
        raise LVReviewError(f"sealed package must contain exactly six regular files: {sorted(names)}")
    manifest_path = package_root / "package.manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = _sha256(manifest_bytes)
    if (package_root / "package.manifest.sha256").read_text(encoding="ascii").strip() != manifest_hash:
        raise LVReviewError("manifest sidecar hash mismatch")
    manifest = _canonical_json(manifest_path)
    # The sealed on-disk manifest intentionally excludes this derived field;
    # bind the in-memory validator context to the canonical file bytes.
    manifest["manifest_sha256"] = manifest_hash
    status = _canonical_json(package_root / "package.status")
    if status != {"manifest_sha256": manifest_hash, "package_status": "sealed"}:
        raise LVReviewError("package status is not sealed or is not bound to manifest")
    if manifest.get("run_id") != run_id or manifest.get("package_status") != "sealed":
        raise LVReviewError("package identity/status mismatch")
    package_input = _canonical_json(package_root / "package.input.json")
    for field in ("run_id", "project_id", "gate_id", "lv_id", "execution_mode", "execution_authorization_required"):
        if field in manifest and package_input.get(field) != manifest.get(field):
            raise LVReviewError(f"package input contract mismatch: {field}")
    if package_input.get("execution_mode") != "manual" or package_input.get("execution_authorization_required") is not True or "execution_authorized" in package_input:
        raise LVReviewError("package input authorization contract is invalid")
    for field, filename in (
        ("package_input_sha256", "package.input.json"),
        ("source_snapshot_sha256", "source_snapshot.json"),
        ("worker_prompt_sha256", "worker_prompt.md"),
    ):
        if manifest.get(field) != _sha256((package_root / filename).read_bytes()):
            raise LVReviewError(f"package hash mismatch: {field}")
    source = _canonical_json(package_root / "source_snapshot.json")
    return manifest, package_root / "package.manifest.json", source


def _capture_git_evidence(root: Path) -> dict[str, Any]:
    config = _git(root, "config", "--local", "--list", "--null")
    try:
        remote_raw = _git(root, "config", "--local", "--get-regexp", r"^remote\..*\.url$")
        remote = b"\0".join(sorted(line for line in remote_raw.splitlines() if line))
    except (LVReviewError, LVExecutionPackageError):
        remote = b""
    submodules = _git(root, "submodule", "status", "--recursive")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    try:
        worktree_fingerprint = _tracked_content_fingerprint(root)
    except (LVReviewError, LVExecutionPackageError):
        worktree_fingerprint = "unavailable:" + _sha256(status)
    return {
        "head": _git(root, "rev-parse", "HEAD").decode("ascii").strip(),
        "tree": _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip(),
        "index_fingerprint": _index_fingerprint(root),
        "worktree_fingerprint": worktree_fingerprint,
        "branch": _git(root, "branch", "--show-current").decode("utf-8").strip(),
        "local_config_fingerprint": _sha256(config),
        "remote_fingerprint": _sha256(remote),
        "submodule_fingerprint": _sha256(submodules),
        "status_fingerprint": _sha256(status),
        "status_clean": not bool(status),
    }


def _python_version(interpreter: Path) -> str:
    completed = subprocess.run(
        [str(interpreter), "-c", "import platform; print(platform.python_version())"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise LVReviewError("Wallet Python interpreter version check failed")
    version = completed.stdout.decode("ascii", errors="strict").strip()
    if not version:
        raise LVReviewError("Wallet Python interpreter version is empty")
    return version


def _namespace_binding(*, proc_root: Path = Path("/proc")) -> tuple[str, int]:
    try:
        raw_map = (proc_root / "self" / "uid_map").read_text(encoding="ascii")
        overflow = int((proc_root / "sys" / "kernel" / "overflowuid").read_text(encoding="ascii").strip())
    except (OSError, UnicodeError, ValueError) as exc:
        raise LVReviewError("user namespace mapping is unavailable") from exc
    rows = []
    for line in raw_map.splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise LVReviewError("user namespace mapping is invalid")
        try:
            start, parent, count = (int(value) for value in fields)
        except ValueError as exc:
            raise LVReviewError("user namespace mapping is invalid") from exc
        if count <= 0:
            raise LVReviewError("user namespace mapping is invalid")
        rows.append((start, parent, count))
    uid = os.getuid()
    if not rows or not any(start <= uid < start + count for start, _, count in rows):
        raise LVReviewError("current UID is not covered by user namespace mapping")
    normalized = "overflowuid=" + str(overflow) + "\n" + "\n".join(
        f"{start} {parent} {count}" for start, parent, count in rows
    )
    return _sha256(normalized.encode("ascii")), overflow


def _mount_binding(path: Path, *, proc_root: Path = Path("/proc")) -> tuple[str, bool]:
    try:
        lines = (proc_root / "self" / "mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LVReviewError("mount information is unavailable") from exc
    candidates: list[tuple[int, str, str, str, str]] = []
    resolved = path.resolve(strict=True)
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        if len(fields) < 6:
            continue
        mount_point = fields[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
        mount_path = Path(mount_point)
        try:
            resolved.relative_to(mount_path)
        except ValueError:
            continue
        right_fields = right.split()
        if len(right_fields) < 2:
            continue
        candidates.append((len(mount_path.parts), mount_point, fields[5], right_fields[0], right_fields[1]))
    if not candidates:
        raise LVReviewError("mount information is ambiguous")
    _, mount_point, mount_options, fs_type, source = max(candidates)
    normalized = f"mount={mount_point}\noptions={mount_options}\nfs={fs_type}\nsource={source}"
    return _sha256(normalized.encode("utf-8")), "ro" in mount_options.split(",")


def _validate_target_binding(
    resolved: Path,
    target_stat: os.stat_result,
    allowed_roots: tuple[Path, ...],
    *,
    proc_root: Path,
    allow_immutable_mount: bool = False,
) -> tuple[str, str, str]:
    if not stat.S_ISREG(target_stat.st_mode) or not os.access(resolved, os.X_OK):
        raise LVReviewError("Wallet interpreter target is not an executable regular file")
    if target_stat.st_mode & 0o022:
        raise LVReviewError("Wallet interpreter target ownership or permissions are unsafe")
    containing_root = max((allowed for allowed in allowed_roots if resolved == allowed or allowed in resolved.parents), key=lambda item: len(item.parts))
    ancestor = resolved.parent
    while True:
        ancestor_stat = ancestor.stat()
        if ancestor_stat.st_mode & 0o022:
            raise LVReviewError("Wallet interpreter ancestor permissions are unsafe")
        if ancestor == containing_root:
            break
        if containing_root not in ancestor.parents:
            raise LVReviewError("Wallet interpreter ancestor path is unsafe")
        ancestor = ancestor.parent
    namespace_fingerprint, overflow_uid = _namespace_binding(proc_root=proc_root)
    mount_fingerprint, mount_read_only = _mount_binding(resolved, proc_root=proc_root)
    if not mount_read_only and not allow_immutable_mount:
        raise LVReviewError("Wallet interpreter mount is not read-only")
    if target_stat.st_uid in {0, os.getuid()}:
        owner_mode = "direct-owner"
    elif target_stat.st_uid == overflow_uid:
        owner_mode = "sandbox-overflow-readonly"
    else:
        raise LVReviewError("Wallet interpreter target ownership is not trusted")
    return owner_mode, namespace_fingerprint, mount_fingerprint


def _validate_interpreter(
    root: Path,
    interpreter: Path,
    *,
    allowed_system_roots: tuple[Path, ...] = (Path("/usr/bin"), Path("/usr/local/bin")),
    proc_root: Path = Path("/proc"),
) -> dict[str, str | bool]:
    """Validate only the mapped venv interpreter, including safe symlink chains."""
    expected = root / ".venv" / "bin" / "python"
    if interpreter != expected:
        raise LVReviewError("Wallet interpreter path is not the fixed venv path")
    if not interpreter.is_symlink() and not interpreter.is_file():
        raise LVReviewError("Wallet .venv/bin/python is unavailable")
    try:
        resolved = interpreter.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LVReviewError("Wallet interpreter symlink chain is invalid") from exc
    allowed_roots = tuple(path.resolve() for path in allowed_system_roots)
    if not any(resolved == allowed or allowed in resolved.parents for allowed in allowed_roots):
        raise LVReviewError("Wallet interpreter target is outside allowed system paths")
    try:
        target_stat = resolved.stat()
    except OSError as exc:
        raise LVReviewError("Wallet interpreter target is unavailable") from exc
    containing_root = max((allowed for allowed in allowed_roots if resolved == allowed or allowed in resolved.parents), key=lambda item: len(item.parts))
    owner_mode, namespace_fingerprint, mount_fingerprint = _validate_target_binding(
        resolved, target_stat, (containing_root,), proc_root=proc_root, allow_immutable_mount=True
    )
    probe = subprocess.run(
        [str(interpreter), "-I", "-B", "-c", (
            "import json,sys; "
            "print(json.dumps({'version':sys.version_info[0],"
            "'prefix':sys.prefix,'base_prefix':sys.base_prefix,'executable':sys.executable}))"
        )],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        timeout=30,
    )
    if probe.returncode != 0 or len(probe.stdout) > 16384:
        raise LVReviewError("Wallet venv interpreter probe failed")
    try:
        info = json.loads(probe.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LVReviewError("Wallet venv interpreter probe was malformed") from exc
    expected_prefix = str((root / ".venv").resolve())
    if (
        info.get("version") != 3
        or info.get("prefix") != expected_prefix
        or info.get("base_prefix") == info.get("prefix")
        or info.get("executable") != str(interpreter)
    ):
        raise LVReviewError("Wallet interpreter is not an isolated Python venv")
    return {
        "python_version": f"{info['version']}",
        "python_executable_sha256": _sha256(resolved.read_bytes()),
        "python_prefix_fingerprint": _sha256(expected_prefix.encode("utf-8")),
        "python_base_prefix_fingerprint": _sha256(str(info["base_prefix"]).encode("utf-8")),
        "python_venv_verified": True,
        "python_owner_validation_mode": owner_mode,
        "python_namespace_fingerprint": namespace_fingerprint,
        "python_mount_fingerprint": mount_fingerprint,
        "python_mount_mode": "read-only" if _mount_binding(resolved, proc_root=proc_root)[1] else "sha-sealed-immutable",
    }

def _validate_external_interpreter(interpreter: Path) -> dict[str, str | bool]:
    resolved = interpreter.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink() or not os.access(resolved, os.X_OK):
        raise LVReviewError("external interpreter is not an executable regular file")
    if resolved.stat().st_mode & 0o022:
        raise LVReviewError("external interpreter permissions are unsafe")
    return {"python_version": "3", "python_executable_sha256": _sha256(resolved.read_bytes()),
            "python_venv_verified": False, "python_owner_validation_mode": "external",
            "python_namespace_fingerprint": "external", "python_mount_fingerprint": "external"}


def _assert_canonical_binding(root: Path, manifest: dict[str, Any]) -> None:
    mapping = load_project_mapping(root)
    if mapping is None:
        raise LVReviewError("project contract mapping is required")
    state = evaluate_canonical_state(mapping)
    ledger = _ledger_binding(root, mapping, state)
    transition = manifest.get("production_transition")
    if isinstance(transition, dict) and state.get("state") == "GATE1_RESUME_READY":
        required = {"schema_version", "project_id", "gate_id", "lv_id", "run_id", "approval_event_id", "plan_sha256", "branch", "baseline_head", "current_head", "predecessor_completion_digest", "owned_file_scope", "completion_conditions", "transition_type", "created_at", "record_hash"}
        if set(transition) != required or transition.get("transition_type") != "SYSTEM_TRANSITION":
            raise LVReviewError("canonical binding mismatch: production transition")
        unsigned = {key: value for key, value in transition.items() if key != "record_hash"}
        if _sha256(canonical_json_bytes(unsigned)) != transition.get("record_hash"):
            raise LVReviewError("canonical binding mismatch: production transition hash")
        if transition.get("project_id") != mapping.project_id or transition.get("gate_id") != manifest.get("gate_id") or transition.get("lv_id") != manifest.get("lv_id") or transition.get("run_id") != manifest.get("run_id"):
            raise LVReviewError("canonical binding mismatch: production transition identity")
        state = dict(state)
        state.update({"state": "GATE1_ACTIVE", "gate_id": transition["gate_id"], "active_scope": [transition["lv_id"]], "approval_id": transition["approval_event_id"], "approval_record_hash": manifest.get("approval_record_hash"), "checkpoint_commit": transition["current_head"], "owned_files": transition["owned_file_scope"]})
    if not isinstance(state.get("state"), str) or not state["state"].endswith("_ACTIVE"):
        raise LVReviewError("canonical binding mismatch: gate_state")
    active_scope = state.get("active_scope")
    if (
        not isinstance(active_scope, list)
        or len(active_scope) != 1
        or not isinstance(active_scope[0], str)
        or not active_scope[0]
    ):
        raise LVReviewError("canonical binding mismatch: active_scope")
    owned_files = state.get("owned_files")
    if (
        not isinstance(owned_files, list)
        or not owned_files
        or any(not isinstance(item, str) or not item for item in owned_files)
        or len(set(owned_files)) != len(owned_files)
    ):
        raise LVReviewError("canonical binding mismatch: owned_files")
    mapped_approval = mapping.transition_approval_id or (mapping.gate_approval_ids or {}).get(state.get("gate_id"))
    # Generic first-Gate activation stores the sealed approval in canonical
    # state; legacy Wallet mappings may still expose transition_approval_id.
    if state.get("approval_id") != mapped_approval and not (mapped_approval is None and state.get("approval_id")):
        raise LVReviewError("canonical binding mismatch: approval_id")
    checks = {
        "project_id": mapping.project_id,
        "gate_id": state.get("gate_id"),
        "lv_id": active_scope[0],
        "canonical_plan_path": state.get("canonical_plan"),
        "canonical_plan_sha256": state.get("plan_sha256"),
        "approval_id": state.get("approval_id"),
        "approval_record_hash": state.get("approval_record_hash"),
        "checkpoint_commit": state.get("checkpoint_commit"),
        "gate_ledger_commit": ledger["commit"],
        "gate_ledger_blob_oid": ledger["blob_oid"],
        "gate_ledger_sha256": ledger["sha256"],
        "active_scope": active_scope,
        "owned_files": owned_files,
    }
    for field, expected in checks.items():
        if manifest.get(field) != expected:
            raise LVReviewError(f"canonical binding mismatch: {field}")
    if manifest.get("execution_authorization_required") is not True:
        raise LVReviewError("execution authorization requirement is invalid")
    runtime = manifest.get("runtime_sandbox_approval_state")
    if runtime != {
        "source": "external_codex_runtime",
        "state": "not_requested",
        "business_approval_reused": False,
        "verified_by_harness": False,
    }:
        raise LVReviewError("runtime approval state is invalid")


def _assert_source_snapshot(
    root: Path,
    manifest: dict[str, Any],
    source: dict[str, Any],
    *,
    require_clean: bool,
) -> None:
    current = {
        "source_head": _git(root, "rev-parse", "HEAD").decode("ascii").strip(),
        "source_tree": _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip(),
        "source_index_fingerprint": _index_fingerprint(root),
        "source_worktree_fingerprint": _tracked_content_fingerprint(root),
    }
    identity_fields = () if not require_clean else ("source_head", "source_tree", "source_index_fingerprint")
    for field in identity_fields:
        value = current[field]
        if manifest.get(field) != value or source.get(field) != value:
            raise LVReviewError(f"source snapshot mismatch: {field}")
    if require_clean:
        if _git(root, "status", "--porcelain=v1").strip():
            raise LVReviewError("Wallet worktree is dirty")
        if _git(root, "ls-files", "--others", "--exclude-standard", "-z").strip(b"\0"):
            raise LVReviewError("Wallet has untracked files")
        if manifest.get("source_worktree_fingerprint") != current["source_worktree_fingerprint"] or source.get("source_worktree_fingerprint") != current["source_worktree_fingerprint"]:
            raise LVReviewError("source snapshot mismatch: source_worktree_fingerprint")


def _preflight(
    run_id: str,
    *,
    package_root: Path | None = None,
    result_path: Path | None = None,
    results_root: Path | None = None,
    interpreter: Path | None = None,
    allow_worker_changes: bool = False,
    check_result_absent: bool = True,
    review_attempt: int = 1,
) -> dict[str, Any]:
    _safe_run_id(run_id)
    package_root = package_root or _package_root(run_id)
    manifest, manifest_path, source = _assert_package(package_root, run_id)
    root = _project_root_for(str(manifest.get("project_id", "")))
    _assert_canonical_binding(root, manifest)
    _assert_source_snapshot(root, manifest, source, require_clean=not allow_worker_changes)
    result_path = result_path or _result_path(run_id)
    if check_result_absent and (result_path.exists() or result_path.is_symlink()):
        raise LVReviewError("worker result already exists")
    review_attempt = parse_review_attempt(review_attempt)
    results_root = results_root or _results_root(run_id, review_attempt)
    if results_root.exists() or results_root.is_symlink():
        raise LVReviewError(f"review attempt-{review_attempt:02d} already exists")
    policy_id = manifest.get("interpreter_policy_id") or "PROJECT_VENV_READ_ONLY"
    if policy_id not in {"PROJECT_VENV_READ_ONLY", "IMMUTABLE_EXTERNAL_INTERPRETER"}:
        raise LVReviewError("unknown or missing interpreter policy")
    interpreter = interpreter or (Path("/usr/bin/python3") if policy_id == "IMMUTABLE_EXTERNAL_INTERPRETER" else root / ".venv" / "bin" / "python")
    expected_interpreter = root / ".venv" / "bin" / "python"
    interpreter_fingerprint = _validate_external_interpreter(interpreter) if policy_id == "IMMUTABLE_EXTERNAL_INTERPRETER" else _validate_interpreter(root, interpreter)
    git_before = _capture_git_evidence(root)
    if not git_before["branch"]:
        raise LVReviewError("detached HEAD is not allowed for preflight")
    return {
        "run_id": run_id,
        "review_attempt": review_attempt,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "source": source,
        "project_root": root,
        "package_root": package_root,
        "result_path": result_path,
        "results_root": results_root,
        "interpreter": interpreter,
        "interpreter_fingerprint": interpreter_fingerprint,
        "git_before": git_before,
    }


def _seal_preflight_evidence(context: dict[str, Any]) -> dict[str, Any]:
    final_root = context.get("preflight_root") or _preflight_root(context["run_id"])
    if final_root.exists() or final_root.is_symlink():
        raise LVReviewError("preflight evidence already exists")
    parent = final_root.parent
    if parent.exists() and parent.is_symlink():
        raise LVReviewError("preflight evidence parent is a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    manifest = context["manifest"]
    git = context["git_before"]
    evidence = {
        "schema_version": PREFLIGHT_EVIDENCE_SCHEMA_VERSION,
        "run_id": context["run_id"],
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "preflight_evidence_sha256": context.get("preflight_evidence_sha256", ""),
        "preflight_evidence_match": bool(context.get("preflight_evidence")),
        "project_id": manifest["project_id"],
        "gate_id": manifest["gate_id"],
        "lv_id": manifest["lv_id"],
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_head": manifest["source_head"],
        "source_tree": manifest["source_tree"],
        "source_index_fingerprint": manifest["source_index_fingerprint"],
        "source_worktree_fingerprint": manifest["source_worktree_fingerprint"],
        "source_worktree_state": "clean",
        "branch_name": git["branch"],
        "local_git_config_sha256": git["local_config_fingerprint"],
        "remote_config_sha256": git["remote_fingerprint"],
        "submodule_status_sha256": git["submodule_fingerprint"],
        "canonical_plan_sha256": manifest["canonical_plan_sha256"],
        "gate_ledger_commit": manifest["gate_ledger_commit"],
        "gate_ledger_blob_oid": manifest["gate_ledger_blob_oid"],
        "gate_ledger_sha256": manifest["gate_ledger_sha256"],
        "owned_files": list(manifest["owned_files"]),
        "result_path_expected": str(context["result_path"]),
        "result_path_absent": True,
        "review_attempt_absent": True,
        "python_interpreter_reference": ".venv/bin/python",
        **context["interpreter_fingerprint"],
        "runtime_authorization": "not_granted_by_preflight",
        "business_approval_reused": False,
    }
    evidence_bytes = canonical_json_bytes(evidence)
    evidence_hash = _sha256(evidence_bytes)
    status = {
        "schema_version": PREFLIGHT_STATUS_SCHEMA_VERSION,
        "status": "READY",
        "hard_stop": True,
        "package_manifest_sha256": evidence["package_manifest_sha256"],
        "preflight_evidence_sha256": evidence_hash,
        "runtime_authorization": "not_granted_by_preflight",
    }
    temp_root = Path(tempfile.mkdtemp(prefix=f".{context['run_id']}.", dir=str(parent)))
    files = {
        "preflight.evidence.json": evidence_bytes,
        "preflight.evidence.sha256": (evidence_hash + "\n").encode("ascii"),
        "preflight.status": canonical_json_bytes(status),
    }
    for name, data in files.items():
        (temp_root / name).write_bytes(data)
    if {path.name for path in temp_root.iterdir()} != set(files):
        raise LVReviewError("preflight evidence sealing set mismatch")
    os.replace(temp_root, final_root)
    return {"preflight_root": str(final_root), "preflight_evidence_sha256": evidence_hash, "status": status}


def preflight_run(run_id: str, *, package_root: Path | None = None, result_path: Path | None = None) -> dict[str, Any]:
    try:
        context = _preflight(run_id, package_root=package_root, result_path=result_path, review_attempt=1)
    except (LVReviewError, LVExecutionPackageError) as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc)}
    try:
        sealed = _seal_preflight_evidence(context)
    except LVReviewError as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc)}
    return {
        "status": "READY",
        "run_id": run_id,
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "runtime_authorization": "not_granted_by_preflight",
        **sealed,
    }

def publish_gate_preflight_attestation(run_id: str, *, package_root: Path, source_root: Path,
                                       result_path: Path) -> dict[str, Any]:
    """Publish a derived LV-review attestation for an immutable Gate preflight."""
    source_file = source_root / "preflight.evidence.json"
    sidecar = source_root / "preflight.evidence.sha256"
    if not source_file.is_file() or source_file.is_symlink() or not sidecar.is_file() or sidecar.is_symlink():
        return {"status":"REJECTED","error_code":"EVIDENCE_NOT_FOUND"}
    source_bytes = source_file.read_bytes(); source_sha = _sha256(source_bytes)
    if sidecar.read_text(encoding="ascii").strip() != source_sha:
        return {"status":"REJECTED","error_code":"EVIDENCE_SOURCE_SHA_MISMATCH"}
    source = _canonical_json(source_file)
    try:
        manifest = _canonical_json(package_root / "package.manifest.json")
        context = _preflight(run_id, package_root=package_root, result_path=result_path,
                             allow_worker_changes=True, check_result_absent=False, review_attempt=1)
    except (LVReviewError, LVExecutionPackageError):
        return {"status":"REJECTED","error_code":"EVIDENCE_REQUIRED_FIELD_MISSING"}
    expected = {"run_id":run_id, "project_id":manifest.get("project_id"), "gate_id":manifest.get("gate_id"),
                "lv_id":manifest.get("lv_id"), "package_manifest_sha256":_sha256((package_root/"package.manifest.json").read_bytes())}
    if any(source.get(k) != v for k,v in expected.items() if k in source):
        return {"status":"REJECTED","error_code":"EVIDENCE_IDENTITY_MISMATCH"}
    evidence = {
        "schema_version": PREFLIGHT_EVIDENCE_SCHEMA_VERSION, "run_id": run_id,
        "package_manifest_sha256": expected["package_manifest_sha256"],
        "preflight_evidence_sha256":"", "preflight_evidence_match":True,
        "project_id":manifest["project_id"], "gate_id":manifest["gate_id"], "lv_id":manifest["lv_id"],
        "captured_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_head":manifest["source_head"], "source_tree":manifest["source_tree"],
        "source_index_fingerprint":manifest["source_index_fingerprint"], "source_worktree_fingerprint":manifest["source_worktree_fingerprint"],
        "source_worktree_state":"clean", "branch_name":context["git_before"]["branch"],
        "local_git_config_sha256":context["git_before"]["local_config_fingerprint"], "remote_config_sha256":context["git_before"]["remote_fingerprint"],
        "submodule_status_sha256":context["git_before"]["submodule_fingerprint"], "canonical_plan_sha256":manifest["canonical_plan_sha256"],
        "gate_ledger_commit":manifest["gate_ledger_commit"], "gate_ledger_blob_oid":manifest["gate_ledger_blob_oid"],
        "gate_ledger_sha256":manifest["gate_ledger_sha256"], "owned_files":manifest["owned_files"],
        "result_path_expected":str(result_path), "result_path_absent":True, "review_attempt_absent":True,
        "python_interpreter_reference":".venv/bin/python", **context["interpreter_fingerprint"],
        "runtime_authorization":"not_granted_by_preflight", "business_approval_reused":False,
        "publication":{"policy_version":"gate-to-lv-preflight.v1","source_schema":source.get("schema_version"),
                       "source_relative_id":str(source_file.relative_to(package_root.parent.parent.parent.parent)),
                       "source_sha256":source_sha,"source_identity":{"run_id":run_id,"gate_id":manifest["gate_id"],"lv_id":manifest["lv_id"]},
                       "lineage":"adoption-checkpoint-6eb80ad","derived":True},
    }
    evidence["preflight_evidence_sha256"] = ""
    raw = canonical_json_bytes(evidence); evidence_sha = _sha256(raw)
    target = _preflight_root(run_id).parent / f"{run_id}-v2b-{source_sha[:12]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = _canonical_json(target / "preflight.evidence.json")
        stable = lambda value: {k:v for k,v in value.items() if k not in {"captured_at","preflight_evidence_sha256"}}
        if stable(existing) != stable(evidence): return {"status":"REJECTED","error_code":"EVIDENCE_PUBLICATION_CONFLICT"}
        return {"status":"READY","preflight_evidence_sha256":_sha256((target/"preflight.evidence.json").read_bytes()),"idempotent":True}
    temp = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=str(target.parent)))
    try:
        (temp/"preflight.evidence.json").write_bytes(canonical_json_bytes(evidence))
        (temp/"preflight.evidence.sha256").write_text(evidence_sha, encoding="ascii")
        (temp/"preflight.status").write_bytes(canonical_json_bytes({"schema_version":PREFLIGHT_STATUS_SCHEMA_VERSION,"status":"READY","hard_stop":True,"package_manifest_sha256":expected["package_manifest_sha256"],"preflight_evidence_sha256":evidence_sha,"runtime_authorization":"not_granted_by_preflight"}))
        os.replace(temp, target)
    finally:
        if temp.exists(): import shutil; shutil.rmtree(temp)
    return {"status":"READY","preflight_evidence_sha256":evidence_sha,"idempotent":False}


def _verify_preflight_evidence(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    root = Path(context.get("preflight_root") or _preflight_root(context["run_id"]))
    expected = {"preflight.evidence.json", "preflight.evidence.sha256", "preflight.status"}
    def valid_candidate(candidate: Path) -> bool:
        try:
            data = (candidate/"preflight.evidence.json").read_bytes()
            return (candidate.is_dir() and not candidate.is_symlink() and
                    (candidate/"preflight.evidence.sha256").read_text(encoding="ascii").strip() == _sha256(data))
        except (OSError, UnicodeError):
            return False
    if not valid_candidate(root):
        candidates = sorted(root.parent.glob(f"{context['run_id']}-v2-*"))
        valid = [p for p in candidates if valid_candidate(p)]
        if valid:
            root = valid[-1]
    if not root.is_dir() or root.is_symlink():
        raise LVReviewError("preflight evidence is missing")
    entries = list(root.iterdir())
    if {entry.name for entry in entries} != expected or not all(entry.is_file() and not entry.is_symlink() for entry in entries):
        raise LVReviewError("preflight evidence must contain exactly three regular files")
    evidence_path = root / "preflight.evidence.json"
    evidence_bytes = evidence_path.read_bytes()
    evidence_hash = _sha256(evidence_bytes)
    if (root / "preflight.evidence.sha256").read_text(encoding="ascii").strip() != evidence_hash:
        raise LVReviewError("preflight evidence sidecar hash mismatch")
    evidence = _canonical_json(evidence_path)
    status = _canonical_json(root / "preflight.status")
    expected_status = {
        "schema_version": PREFLIGHT_STATUS_SCHEMA_VERSION,
        "status": "READY",
        "hard_stop": True,
        "package_manifest_sha256": evidence["package_manifest_sha256"],
        "preflight_evidence_sha256": evidence_hash,
        "runtime_authorization": "not_granted_by_preflight",
    }
    if status != expected_status:
        raise LVReviewError("preflight status is invalid")
    manifest = context["manifest"]
    checks = {
        "schema_version": PREFLIGHT_EVIDENCE_SCHEMA_VERSION,
        "run_id": context["run_id"],
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "project_id": manifest["project_id"],
        "gate_id": manifest["gate_id"],
        "lv_id": manifest["lv_id"],
        "source_head": manifest["source_head"],
        "source_tree": manifest["source_tree"],
        "source_index_fingerprint": manifest["source_index_fingerprint"],
        "source_worktree_fingerprint": manifest["source_worktree_fingerprint"],
        "source_worktree_state": "clean",
        "canonical_plan_sha256": manifest["canonical_plan_sha256"],
        "gate_ledger_commit": manifest["gate_ledger_commit"],
        "gate_ledger_blob_oid": manifest["gate_ledger_blob_oid"],
        "gate_ledger_sha256": manifest["gate_ledger_sha256"],
        "owned_files": manifest["owned_files"],
        "result_path_expected": str(context["result_path"]),
        "result_path_absent": True,
        "review_attempt_absent": True,
        "runtime_authorization": "not_granted_by_preflight",
        "business_approval_reused": False,
    }
    for field, expected_value in checks.items():
        if evidence.get(field) != expected_value:
            raise LVReviewError(f"preflight evidence mismatch: {field}")
    if evidence.get("python_interpreter_reference") != ".venv/bin/python" and manifest.get("interpreter_policy_id") != "IMMUTABLE_EXTERNAL_INTERPRETER":
        raise LVReviewError("preflight Python evidence is invalid")
    if not evidence.get("python_version") or (manifest.get("interpreter_policy_id") != "IMMUTABLE_EXTERNAL_INTERPRETER" and evidence.get("python_venv_verified") is not True):
        raise LVReviewError("preflight Python evidence is invalid")
    for field, expected_value in context["interpreter_fingerprint"].items():
        if evidence.get(field) != expected_value:
            raise LVReviewError(f"preflight Python evidence mismatch: {field}")
    return evidence, evidence_hash


def _safe_read_result(path: Path) -> tuple[dict[str, Any], str, bytes]:
    if not path.is_file() or path.is_symlink():
        raise LVReviewError("worker result is missing or is not a regular file")
    before = path.lstat()
    if before.st_uid != os.getuid() or before.st_mode & 0o022:
        raise LVReviewError("worker result ownership or permissions are unsafe")
    if before.st_size > MAX_RESULT_BYTES:
        raise LVReviewError("worker result exceeds 1 MiB")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if opened.st_ino != before.st_ino or opened.st_dev != before.st_dev or opened.st_uid != os.getuid() or opened.st_mode & 0o022:
            raise LVReviewError("worker result changed during open")
        data = b""
        while len(data) <= MAX_RESULT_BYTES:
            chunk = os.read(fd, MAX_RESULT_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > MAX_RESULT_BYTES:
            raise LVReviewError("worker result exceeds 1 MiB")
    finally:
        os.close(fd)
    after = path.lstat()
    if after.st_ino != before.st_ino or after.st_dev != before.st_dev or after.st_size != before.st_size:
        raise LVReviewError("worker result changed while reading")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LVReviewError("worker result JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise LVReviewError("worker result must be a JSON object")
    return payload, _sha256(data), data


def _parse_name_status(data: bytes) -> bool:
    parts = data.split(b"\0")
    index = 0
    forbidden = False
    while index < len(parts):
        record = parts[index]
        index += 1
        if not record:
            continue
        code = record.split(b"\t", 1)[0][:1].decode("ascii", errors="ignore")
        if code in _FORBIDDEN_CHANGE_CODES:
            forbidden = True
        if code in {"R", "C"} and index < len(parts):
            index += 1
    return forbidden


def _actual_changes(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    diff = _git(root, "diff", "--name-status", "-z")
    cached = _git(root, "diff", "--cached", "--name-status", "-z")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    submodule = _git(root, "submodule", "status", "--recursive")
    created: set[str] = set()
    modified: set[str] = set()
    deleted: set[str] = set()
    forbidden = _parse_name_status(diff) or _parse_name_status(cached)
    records = status.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        text = record.decode("utf-8", errors="strict")
        xy, path = text[:2], text[3:]
        if any(code in _FORBIDDEN_CHANGE_CODES for code in xy):
            forbidden = True
        if xy == "??" or "A" in xy:
            created.add(path)
        elif "D" in xy:
            deleted.add(path)
        elif "M" in xy:
            modified.add(path)
        if "R" in xy or "C" in xy:
            forbidden = True
            if index < len(records):
                index += 1
    untracked_names = [item.decode("utf-8", errors="strict") for item in untracked.split(b"\0") if item]
    created.update(untracked_names)
    changed = created | modified | deleted
    submodule_changed = any(line[:1] in {b"+", b"-", b"U"} for line in submodule.splitlines() if line)
    return {
        "changed_files": sorted(changed),
        "created_files": sorted(created),
        "modified_files": sorted(modified),
        "deleted_files": sorted(deleted),
        "forbidden_status": forbidden or submodule_changed,
    }


def _run_command(argv: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            process.wait()
        def tail(handle: Any) -> str:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 8192), os.SEEK_SET)
            return handle.read(8192).decode("utf-8", errors="replace")
        stdout_text = tail(stdout_file)
        stderr_text = tail(stderr_file)
    if timed_out:
        return {"argv": argv, "exit_code": None, "timeout": True, "stdout": "", "stderr": "timeout"}
    return {
        "argv": argv,
        "exit_code": process.returncode,
        "timeout": False,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }


def _run_tests(root: Path, interpreter: Path, owned_files: list[str], *, runner: str = "pytest") -> tuple[list[dict[str, Any]], str | None]:
    test_targets = [path for path in owned_files if path.startswith("tests/") and path.endswith(".py")]
    import_targets = [
        path.removesuffix(".py").replace("/", ".")
        for path in owned_files
        if path.endswith(".py") and not path.startswith("tests/")
    ]
    if not test_targets or not import_targets:
        return [], "owned Python test/module scope is missing"
    for relative in test_targets:
        target = root / relative
        if not target.is_file() or target.is_symlink():
            return [], "owned Python test target is missing or unsafe"
    # Select the project-declared standard-library runner for generic
    # projects; pytest is an explicit legacy capability, never an implicit
    # fallback.  unittest discovery has deterministic zero-test semantics.
    test_runner = runner if runner in {"pytest", "unittest"} else "pytest"
    commands = [
        ([str(interpreter), "-B", "-m", test_runner, "-q", *test_targets] if test_runner == "pytest" else [str(interpreter), "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], 60),
        ([str(interpreter), "-B", "-m", test_runner, "-q"] if test_runner == "pytest" else [str(interpreter), "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], 180),
        ([
            str(interpreter),
            "-B",
            "-c",
            "import importlib,sys; [importlib.import_module(name) for name in sys.argv[1:]]",
            *import_targets,
        ], 30),
    ]
    results: list[dict[str, Any]] = []
    for argv, timeout in commands:
        result = _run_command(argv, root, timeout)
        results.append({key: value for key, value in result.items() if key not in {"stdout", "stderr"}})
        if result["timeout"] or result["exit_code"] != 0:
            return results, f"independent test command failed (exit={result['exit_code']})"
    return results, None


def _check(
    identifier: str,
    passed: bool,
    summary: str,
    *,
    exit_code: int | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"check": identifier, "status": "PASS" if passed else "FAIL", "summary": summary[:240]}
    if exit_code is not None:
        item["exit_code"] = exit_code
    if findings:
        item["findings"] = findings
    return item


def _file_snapshot(path: Path) -> tuple[int, int, int, int, str]:
    current = path.lstat()
    if not stat.S_ISREG(current.st_mode) or path.is_symlink():
        raise LVReviewError("immutable input is not a regular non-symlink file")
    return current.st_dev, current.st_ino, current.st_mode, current.st_size, _sha256(path.read_bytes())


def _directory_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, str]]:
    if not root.is_dir() or root.is_symlink():
        raise LVReviewError("immutable input directory is missing or unsafe")
    entries = list(root.iterdir())
    ignored = {"preflight", "worker.request.json", "worker.result.json", "worker_handoff.md", "handoff_report.md"}
    if any(path.is_symlink() or (not path.is_file() and path.name not in ignored) for path in entries):
        raise LVReviewError("immutable input directory contains an unsafe entry")
    return {path.name: _file_snapshot(path) for path in entries if path.name not in ignored}


def _owned_content_snapshot(root: Path, owned_files: list[str]) -> list[dict[str, Any]]:
    """Capture deterministic content evidence without following owned-path symlinks."""
    if not isinstance(owned_files, list) or not owned_files:
        raise LVReviewError("owned files are missing")
    root_resolved = root.resolve(strict=True)
    normalized: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for relative in owned_files:
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise LVReviewError("owned path is invalid")
        relative_path = Path(relative)
        canonical = relative_path.as_posix()
        if relative_path.is_absolute() or canonical in {".", ".."} or ".." in relative_path.parts:
            raise LVReviewError("owned path escapes project root")
        if canonical in seen:
            raise LVReviewError("duplicate owned path")
        seen.add(canonical)
        candidate = root / relative_path
        current = root
        try:
            for part in relative_path.parts:
                current = current / part
                if current.is_symlink():
                    raise LVReviewError("owned path is a symlink")
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise LVReviewError("owned file is missing") from exc
        except (OSError, RuntimeError) as exc:
            raise LVReviewError("owned path is unsafe") from exc
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise LVReviewError("owned path escapes project root") from exc
        normalized.append((canonical, candidate))

    evidence: list[dict[str, Any]] = []
    for relative, candidate in sorted(normalized):
        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise LVReviewError("owned path is not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError as exc:
            raise LVReviewError("owned file could not be opened safely") from exc
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or not stat.S_ISREG(opened.st_mode):
                raise LVReviewError("owned file changed during open")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        finally:
            os.close(descriptor)
        after = candidate.lstat()
        if (
            (after.st_dev, after.st_ino, after.st_size) != (before.st_dev, before.st_ino, before.st_size)
            or not stat.S_ISREG(after.st_mode)
            or size != before.st_size
        ):
            raise LVReviewError("owned file changed while reading")
        evidence.append({
            "path": relative,
            "sha256": digest.hexdigest(),
            "size": size,
            "regular_file": True,
            "not_symlink": True,
        })
    return evidence


_SECRET_NAME = re.compile(r"(?i)(?:api[_-]?key|token|password|secret)")
_CREDENTIAL_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_KNOWN_TOKEN_LITERAL = re.compile(r"(?i)^(?:sk|ghp|xox[baprs])-[a-z0-9_-]{12,}$")


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def _secret_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return bool(_SECRET_NAME.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_SECRET_NAME.search(node.attr))
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_secret_target(item) for item in node.elts)
    return False


def _redacted_finding(relative: str, line: int, kind: str, value: str) -> dict[str, Any]:
    return {
        "path": relative,
        "line": max(1, line),
        "check": "secret_like_value",
        "kind": kind,
        "fingerprint": _sha256(value.encode("utf-8")),
    }


def _explicit_test_sentinel(relative: str, value: str) -> bool:
    normalized = value.casefold()
    return (
        relative.startswith("tests/")
        and normalized.startswith("fixture-")
        and (normalized.endswith("-not-a-secret") or normalized.endswith("-marker"))
        and not _CREDENTIAL_URL.search(value)
    )


def _python_secret_findings(relative: str, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text, filename=relative)
    except (SyntaxError, ValueError) as exc:
        return [_redacted_finding(relative, getattr(exc, "lineno", 1) or 1, "python_ast_parse_error", relative)]

    candidates: list[tuple[ast.AST, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = _static_string(node.value)
            if value and not _explicit_test_sentinel(relative, value) and any(_secret_target(target) for target in node.targets):
                candidates.append((node.value, "secret_named_literal", value))
        elif isinstance(node, ast.AnnAssign):
            value = _static_string(node.value) if node.value is not None else None
            if value and not _explicit_test_sentinel(relative, value) and _secret_target(node.target):
                candidates.append((node.value, "secret_named_literal", value))
        elif isinstance(node, ast.keyword) and node.arg and _SECRET_NAME.search(node.arg):
            value = _static_string(node.value)
            if value and not _explicit_test_sentinel(relative, value):
                candidates.append((node.value, "secret_keyword_literal", value))
        elif isinstance(node, ast.Dict):
            for key, value_node in zip(node.keys, node.values):
                key_value = _static_string(key) if key is not None else None
                value = _static_string(value_node)
                if key_value and _SECRET_NAME.search(key_value) and value and not _explicit_test_sentinel(relative, value):
                    candidates.append((value_node, "secret_mapping_literal", value))

    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if node in docstrings:
            continue
        value = _static_string(node)
        if value is None:
            continue
        enclosing = parent.get(node)
        if isinstance(enclosing, (ast.BinOp, ast.JoinedStr)) and _static_string(enclosing) is not None:
            continue
        if _CREDENTIAL_URL.search(value):
            candidates.append((node, "credential_bearing_url", value))
        elif _KNOWN_TOKEN_LITERAL.fullmatch(value) and not _explicit_test_sentinel(relative, value):
            candidates.append((node, "known_token_literal", value))

    findings: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for node, kind, value in candidates:
        key = (getattr(node, "lineno", 1), kind, _sha256(value.encode("utf-8")))
        if key not in seen:
            seen.add(key)
            findings.append(_redacted_finding(relative, key[0], kind, value))
    return findings


def _scan_owned_files(root: Path, owned_files: list[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    failures: dict[str, list[Any]] = {key: [] for key in ("utf8_decode", "bom", "nul", "trailing_whitespace", "conflict_marker", "secret_like_value")}
    conflict = re.compile(r"^(<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
    secret_assignment = re.compile(
        r"(?i)\b([a-z0-9_]*(?:api[_-]?key|token|password|secret)[a-z0-9_]*)\b"
        r"\s*[:=]\s*(['\"]?)([^\s,'\"}\]]+)\2"
    )
    for relative in owned_files:
        path = root / relative
        try:
            data = path.read_bytes()
        except OSError:
            failures["utf8_decode"].append(relative)
            continue
        if data.startswith(b"\xef\xbb\xbf"):
            failures["bom"].append(relative)
        if b"\0" in data:
            failures["nul"].append(relative)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            failures["utf8_decode"].append(relative)
            continue
        if any(line.rstrip("\r\n").endswith((" ", "\t")) for line in text.splitlines(keepends=True)):
            failures["trailing_whitespace"].append(relative)
        if conflict.search(text):
            failures["conflict_marker"].append(relative)
        if path.suffix == ".py":
            findings = _python_secret_findings(relative, text)
            if findings:
                failures["secret_like_value"].extend(findings)
        else:
            secret_hit = bool(_CREDENTIAL_URL.search(text))
            for match in secret_assignment.finditer(text):
                value = match.group(3)
                surrounding = text[match.start():match.end() + 40].lower()
                if value and not any(marker in surrounding for marker in ("getenv", "environ", "placeholder", "example", "dummy")):
                    secret_hit = True
            if secret_hit:
                failures["secret_like_value"].append(relative)
    for identifier, locations_value in failures.items():
        if identifier == "secret_like_value":
            structured = [item for item in locations_value if isinstance(item, dict)]
            plain = sorted({item for item in locations_value if isinstance(item, str)})
            structured.extend(_redacted_finding(item, 1, "non_python_secret_pattern", item) for item in plain)
            structured.sort(key=lambda item: (item["path"], item["line"], item["kind"]))
            locations = sorted({item["path"] for item in structured})
            checks.append(_check(identifier, not structured, "no findings" if not structured else "redacted findings in: " + ", ".join(locations), findings=structured))
        else:
            locations = sorted(set(locations_value))
            checks.append(_check(identifier, not locations, "no findings" if not locations else "finding locations: " + ", ".join(locations)))
    return checks


def _verify_legacy_lineage(
    context: dict[str, Any],
    worker_hash: str,
    *,
    contract: dict[str, str] | None = None,
    prior_attempt_contract: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if context["review_attempt"] == 1:
        return None
    if context["review_attempt"] > 3:
        raise LVReviewError("review attempts above 3 are not supported")
    if context["review_attempt"] == 2:
        prior_root = context["results_root"].parent / "attempt-01"
        if prior_root.is_dir() and not prior_root.is_symlink():
            required = {"reviewer.report.json", "reviewer.report.sha256", "review.status", "worker.result.json", "worker.result.sha256"}
            entries = list(prior_root.iterdir())
            if {entry.name for entry in entries} != required or not all(
                entry.is_file() and not entry.is_symlink() for entry in entries
            ):
                raise LVReviewError("attempt-01 review artifacts are incomplete or unsafe")
            hashes = {entry.name: _sha256(entry.read_bytes()) for entry in entries}
            report_hash = hashes["reviewer.report.json"]
            if (prior_root / "reviewer.report.sha256").read_text(encoding="ascii").strip() != report_hash:
                raise LVReviewError("attempt-01 reviewer sidecar does not match report")
            if (prior_root / "worker.result.sha256").read_text(encoding="ascii").strip() != worker_hash:
                raise LVReviewError("attempt-01 worker sidecar does not match current worker result")
            if hashes["worker.result.json"] != worker_hash:
                raise LVReviewError("attempt-01 worker result does not match current worker result")
            prior_report = _canonical_json(prior_root / "reviewer.report.json")
            prior_status = _canonical_json(prior_root / "review.status")
            if frozenset(prior_report) not in {frozenset(REVIEW_REPORT_FIELDS), frozenset(LEGACY_REVIEW_REPORT_FIELDS)}:
                raise LVReviewError("attempt-01 reviewer report schema mismatch")
            if set(prior_status) != REVIEW_STATUS_FIELDS:
                raise LVReviewError("attempt-01 review status schema mismatch")
            expected_values = {
                "run_id": context["run_id"],
                "review_attempt": 1,
                "worker_attempt": 1,
                "verdict": "PASS",
                "hard_stop": True,
                "review_only_reexecution": False,
                "reran_worker": False,
                "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
                "preflight_evidence_sha256": context["preflight_evidence_sha256"],
                "worker_result_sha256": worker_hash,
            }
            for field, expected_value in expected_values.items():
                if prior_report.get(field) != expected_value or prior_status.get(field) != expected_value:
                    raise LVReviewError(f"attempt-01 review contract mismatch: {field}")
            if prior_status.get("reviewer_report_sha256") != report_hash:
                raise LVReviewError("attempt-01 status does not match reviewer report")
            artifacts = [
                {
                    "path": f"_workspace/orchestration-results/{context['run_id']}/attempt-01/{name}",
                    "sha256": hashes[name],
                }
                for name in sorted(required)
            ]
            return {
                "prior_review_location_kind": "attempt_directory",
                "prior_review_contract_status": "verified_pass_hard_stop",
                "review_attempt": 1,
                "artifacts": artifacts,
                "prior_reviewer_report_sha256": report_hash,
                "package_manifest_sha256": expected_values["package_manifest_sha256"],
                "preflight_evidence_sha256": expected_values["preflight_evidence_sha256"],
                "worker_result_sha256": worker_hash,
            }
    expected = contract if contract is not None else LEGACY_REVIEW_CONTRACTS.get(context["run_id"])
    required = {"reviewer.report.json", "reviewer.report.sha256", "review.status", "worker.result.json", "worker.result.sha256"}
    if not expected or set(expected) != required:
        raise LVReviewError("verified prior review lineage is required")
    run_root = context["results_root"].parent
    artifacts = []
    for name, expected_hash in expected.items():
        path = run_root / name
        if not path.is_file() or path.is_symlink():
            raise LVReviewError("legacy review artifact is missing or unsafe")
        actual_hash = _sha256(path.read_bytes())
        if actual_hash != expected_hash:
            raise LVReviewError("legacy review artifact hash mismatch")
        artifacts.append({"path": f"_workspace/orchestration-results/{context['run_id']}/{name}", "sha256": actual_hash})
    if expected["worker.result.json"] != worker_hash:
        raise LVReviewError("legacy review worker result does not match current worker result")
    lineage: dict[str, Any] = {
        "prior_review_location_kind": "legacy_run_root",
        "prior_review_contract_status": "artifact_contract_failed",
        "artifacts": artifacts,
        "prior_reviewer_report_sha256": expected["reviewer.report.json"],
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "preflight_evidence_sha256": context["preflight_evidence_sha256"],
        "worker_result_sha256": worker_hash,
    }
    if context["review_attempt"] == 2:
        return lineage

    expected_prior = prior_attempt_contract
    if expected_prior is None:
        expected_prior = PRIOR_ATTEMPT_CONTRACTS.get(context["run_id"], {}).get(2)
    if not expected_prior or set(expected_prior) != required:
        raise LVReviewError("verified attempt-02 review lineage is required")
    prior_root = run_root / "attempt-02"
    prior_hashes: dict[str, str] = {}
    prior_artifacts: list[dict[str, str]] = []
    for name, expected_hash in expected_prior.items():
        path = prior_root / name
        if not path.is_file() or path.is_symlink():
            raise LVReviewError("attempt-02 review artifact is missing or unsafe")
        actual_hash = _sha256(path.read_bytes())
        if actual_hash != expected_hash:
            raise LVReviewError("attempt-02 review artifact hash mismatch")
        prior_hashes[name] = actual_hash
        prior_artifacts.append({
            "path": f"_workspace/orchestration-results/{context['run_id']}/attempt-02/{name}",
            "sha256": actual_hash,
        })
    report_hash = prior_hashes["reviewer.report.json"]
    try:
        sidecar_hash = (prior_root / "reviewer.report.sha256").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise LVReviewError("attempt-02 reviewer sidecar is invalid") from exc
    if sidecar_hash != report_hash:
        raise LVReviewError("attempt-02 reviewer sidecar does not match report")
    prior_report = _canonical_json(prior_root / "reviewer.report.json")
    prior_status = _canonical_json(prior_root / "review.status")
    if frozenset(prior_report) not in {frozenset(REVIEW_REPORT_FIELDS), frozenset(LEGACY_REVIEW_REPORT_FIELDS)} or set(prior_status) != REVIEW_STATUS_FIELDS:
        raise LVReviewError("attempt-02 review schema mismatch")
    if prior_status.get("reviewer_report_sha256") != report_hash:
        raise LVReviewError("attempt-02 status does not match reviewer report")
    expected_values = {
        "run_id": context["run_id"],
        "review_attempt": 2,
        "worker_attempt": 1,
        "verdict": "FAIL",
        "hard_stop": True,
        "review_only_reexecution": True,
        "reran_worker": False,
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "preflight_evidence_sha256": context["preflight_evidence_sha256"],
        "worker_result_sha256": worker_hash,
    }
    for field, expected_value in expected_values.items():
        if prior_report.get(field) != expected_value or prior_status.get(field) != expected_value:
            raise LVReviewError(f"attempt-02 review contract mismatch: {field}")
    violations = prior_report.get("violations")
    if not isinstance(violations, list) or "independent check failed: secret_like_value" not in violations:
        raise LVReviewError("attempt-02 secret-like failure evidence is missing")
    checks = prior_report.get("independent_checks")
    if not isinstance(checks, list) or not any(
        isinstance(item, dict) and item.get("check") == "secret_like_value" and item.get("status") == "FAIL"
        for item in checks
    ):
        raise LVReviewError("attempt-02 secret-like independent check is missing")
    if prior_report.get("prior_review_lineage") != lineage:
        raise LVReviewError("attempt-02 legacy lineage mismatch")
    if prior_hashes["worker.result.json"] != worker_hash:
        raise LVReviewError("attempt-02 worker result does not match current worker result")
    lineage["immediate_prior_review"] = {
        "location_kind": "attempt_directory",
        "review_attempt": 2,
        "verdict": "FAIL",
        "hard_stop": True,
        "violation_identifier": "secret_like_value",
        "artifacts": prior_artifacts,
        "prior_reviewer_report_sha256": report_hash,
        "package_manifest_sha256": expected_values["package_manifest_sha256"],
        "preflight_evidence_sha256": expected_values["preflight_evidence_sha256"],
        "worker_result_sha256": worker_hash,
    }
    return lineage


def _set_from_result(payload: dict[str, Any], field: str) -> set[str]:
    values = payload.get(field)
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise LVReviewError(f"worker result field is invalid: {field}")
    if len(values) != len(set(values)):
        raise LVReviewError(f"worker result field contains duplicates: {field}")
    return set(values)


def _build_report(
    context: dict[str, Any],
    worker_hash: str,
    verdict: str,
    *,
    actual: dict[str, Any] | None = None,
    tests: list[dict[str, Any]] | None = None,
    violations: list[str] | None = None,
    blockers: list[str] | None = None,
    reasons: list[str] | None = None,
    after: dict[str, Any] | None = None,
    independent_checks: list[dict[str, Any]] | None = None,
    interpreter_after: dict[str, Any] | None = None,
    prior_review_lineage: dict[str, Any] | None = None,
    owned_content_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = context["manifest"]
    actual = actual or {key: [] for key in ("changed_files", "created_files", "modified_files", "deleted_files")}
    report = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "run_id": context["run_id"],
        "project": manifest.get("project_id"),
        "gate": manifest.get("gate_id"),
        "lv": manifest.get("lv_id"),
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "preflight_evidence_sha256": context.get("preflight_evidence_sha256"),
        "worker_result_sha256": worker_hash,
        "review_attempt": context["review_attempt"],
        "worker_attempt": context.get("worker_attempt", 0),
        "review_only_reexecution": context["review_attempt"] > 1,
        "reran_worker": False,
        "prior_review_lineage": prior_review_lineage,
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict,
        "hard_stop": True,
        "baseline_wallet_head": manifest.get("source_head"),
        "current_wallet_head": (after or {}).get("head"),
        "canonical_plan": {"path": manifest.get("canonical_plan_path"), "sha256": manifest.get("canonical_plan_sha256")},
        "actual_changed_files": actual.get("changed_files", []),
        "actual_created_files": actual.get("created_files", []),
        "actual_modified_files": actual.get("modified_files", []),
        "actual_deleted_files": actual.get("deleted_files", []),
        "owned_files": manifest.get("owned_files", []),
        "git_evidence": {"before": context["git_before"], "after": after or {}},
        "independent_checks": independent_checks or [],
        "interpreter_before": context.get("interpreter_fingerprint", {}),
        "interpreter_after": interpreter_after or {},
        "violations": violations or [],
        "blockers": blockers or [],
        "reasons": reasons or [],
        "owned_content_evidence": owned_content_evidence or {},
    }
    if set(report) != REVIEW_REPORT_FIELDS:
        raise LVReviewError("reviewer report schema field set mismatch")
    return report


def _seal_review(context: dict[str, Any], report: dict[str, Any], worker_hash: str, worker_bytes: bytes) -> dict[str, Any]:
    final_root = context["results_root"]
    if final_root.exists() or final_root.is_symlink():
        raise LVReviewError(f"review attempt-{context['review_attempt']:02d} already exists")
    parent = final_root.parent
    if parent.exists() and parent.is_symlink():
        raise LVReviewError("review result parent is a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=f".{context['run_id']}.", dir=str(parent)))
    if set(report) != REVIEW_REPORT_FIELDS or not report.get("preflight_evidence_sha256"):
        raise LVReviewError("reviewer report schema or preflight binding is incomplete")
    owned_content = report.get("owned_content_evidence")
    if not isinstance(owned_content, dict) or not isinstance(owned_content.get("stable"), bool):
        raise LVReviewError("owned-content evidence is required")
    if owned_content.get("capture_status") == "unavailable":
        if report.get("verdict") == "PASS":
            raise LVReviewError("PASS requires complete owned-content evidence")
    else:
        final_snapshot = _owned_content_snapshot(context["project_root"], list(context["manifest"]["owned_files"]))
        expected_stable = owned_content.get("before") == owned_content.get("after")
        if owned_content["stable"] != expected_stable or (not expected_stable and report.get("verdict") == "PASS"):
            raise LVReviewError("owned-content stability result is invalid")
        if final_snapshot != owned_content.get("after"):
            raise LVReviewError("owned content changed before artifact sealing")
        owned_content["final"] = final_snapshot
    report_bytes = canonical_json_bytes(report)
    report_hash = _sha256(report_bytes)
    status = {
        "schema_version": REVIEW_STATUS_SCHEMA_VERSION,
        "run_id": report["run_id"],
        "review_attempt": report["review_attempt"],
        "worker_attempt": report["worker_attempt"],
        "verdict": report["verdict"],
        "hard_stop": True,
        "reviewer_report_sha256": report_hash,
        "worker_result_sha256": worker_hash,
        "package_manifest_sha256": report["package_manifest_sha256"],
        "preflight_evidence_sha256": report["preflight_evidence_sha256"],
        "review_only_reexecution": report["review_only_reexecution"],
        "reran_worker": report["reran_worker"],
    }
    if set(status) != REVIEW_STATUS_FIELDS:
        raise LVReviewError("review status schema field set mismatch")
    files = {
        "worker.result.json": worker_bytes,
        "worker.result.sha256": (worker_hash + "\n").encode("ascii"),
        "reviewer.report.json": report_bytes,
        "reviewer.report.sha256": (report_hash + "\n").encode("ascii"),
        "review.status": canonical_json_bytes(status),
    }
    for name, data in files.items():
        (temp_root / name).write_bytes(data)
    if {path.name for path in temp_root.iterdir()} != set(files):
        raise LVReviewError("review artifact sealing set mismatch")
    os.replace(temp_root, final_root)
    return {"results_root": str(final_root), "reviewer_report_sha256": report_hash, "review_status": status}


def review_run(
    run_id: str,
    *,
    attempt: object = None,
    package_root: Path | None = None,
    result_path: Path | None = None,
    results_root: Path | None = None,
    interpreter: Path | None = None,
    prior_review_contract: dict[str, str] | None = None,
    prior_attempt_contract: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        review_attempt = parse_review_attempt(attempt)
    except LVReviewError as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    try:
        context = _preflight(
            run_id,
            package_root=package_root,
            result_path=result_path or _result_path(run_id),
            results_root=results_root,
            interpreter=interpreter,
            allow_worker_changes=True,
            check_result_absent=False,
            review_attempt=review_attempt,
        )
    except (LVReviewError, LVExecutionPackageError) as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    context["review_attempt"] = review_attempt
    worker_hash = ""
    worker_bytes = b""
    independent_checks: list[dict[str, Any]] = []
    prior_review_lineage: dict[str, Any] | None = None
    interpreter_after: dict[str, Any] = {}
    owned_content_before: list[dict[str, Any]] = []
    try:
        evidence, evidence_hash = _verify_preflight_evidence(context)
        if not evidence_hash:
            raise LVReviewError("preflight evidence seal hash is missing")
        context["preflight_evidence"] = evidence
        context["preflight_evidence_sha256"] = evidence_hash
        package_snapshot = _directory_snapshot(context["package_root"])
        evidence_root = Path(context.get("preflight_root") or _preflight_root(run_id))
        preflight_snapshot = _directory_snapshot(evidence_root)
        payload, worker_hash, worker_bytes = _safe_read_result(context["result_path"])
        worker_snapshot = _file_snapshot(context["result_path"])
        worker_attempt = payload.get("attempt")
        if isinstance(worker_attempt, bool) or not isinstance(worker_attempt, int) or worker_attempt <= 0:
            raise LVReviewError("worker result attempt must be a positive integer")
        if worker_attempt != 1 or worker_attempt > review_attempt:
            raise LVReviewError("worker result attempt does not match review recovery contract")
        if payload.get("preflight_evidence_sha256") != evidence_hash:
            raise LVReviewError("worker result preflight evidence binding mismatch")
        if payload.get("owned_files") != context["manifest"].get("owned_files"):
            raise LVReviewError("worker result owned-files contract mismatch")
        context["worker_attempt"] = worker_attempt
        validate_worker_result(payload, context["manifest"])
        if payload.get("worker_type") != "manual":
            raise LVReviewError("worker_type must be manual")
        for result_field, manifest_field in (
            ("source_head_before", "source_head"),
            ("source_tree_before", "source_tree"),
            ("source_index_before", "source_index_fingerprint"),
            ("source_worktree_before", "source_worktree_fingerprint"),
        ):
            if payload.get(result_field) != context["manifest"].get(manifest_field):
                raise LVReviewError(f"worker {result_field} does not match package")
        current_identity = _capture_git_evidence(context["project_root"])
        actual = _actual_changes(context["project_root"])
        prior_review_lineage = _verify_legacy_lineage(
            context,
            worker_hash,
            contract=prior_review_contract,
            prior_attempt_contract=prior_attempt_contract,
        )
        owned_content_before = _owned_content_snapshot(
            context["project_root"], list(context["manifest"]["owned_files"])
        )
        worker_sets = {field: _set_from_result(payload, field) for field in ("changed_files", "created_files", "modified_files", "deleted_files")}
        actual_sets = {field: set(actual[field]) for field in worker_sets}
        violations: list[str] = []
        for evidence_field, manifest_field in (
            ("head", "source_head"),
            ("tree", "source_tree"),
            ("index_fingerprint", "source_index_fingerprint"),
        ):
            if context["git_before"][evidence_field] != context["manifest"].get(manifest_field):
                violations.append(f"Git {evidence_field} differs from package baseline")
        for evidence_field, git_field in (
            ("branch_name", "branch"),
            ("local_git_config_sha256", "local_config_fingerprint"),
            ("remote_config_sha256", "remote_fingerprint"),
            ("submodule_status_sha256", "submodule_fingerprint"),
            ("source_head", "head"),
            ("source_tree", "tree"),
            ("source_index_fingerprint", "index_fingerprint"),
        ):
            if context["git_before"][git_field] != evidence[evidence_field]:
                violations.append(f"Git {git_field} differs from preflight evidence")
        if payload.get("source_head_after") != current_identity["head"] or payload.get("source_tree_after") != current_identity["tree"] or payload.get("source_index_after") != current_identity["index_fingerprint"] or payload.get("source_worktree_after") != current_identity["worktree_fingerprint"]:
            violations.append("worker source-after identity does not match current Git state")
        for field in worker_sets:
            if worker_sets[field] != actual_sets[field]:
                violations.append(f"worker/{field} does not match actual Git state")
        owned = set(context["manifest"]["owned_files"])
        if set(actual["changed_files"]) - owned:
            violations.append("actual change is outside owned files")
        independent_checks.append(_check("owned_file_boundary", not bool(set(actual["changed_files"]) - owned), "actual changes are limited to owned files" if not set(actual["changed_files"]) - owned else "out-of-scope paths detected"))
        staged_absent = not bool(_git(context["project_root"], "diff", "--cached", "--name-only").strip())
        independent_checks.append(_check("staged_changes_absent", staged_absent, "no staged changes" if staged_absent else "staged changes detected"))
        if not staged_absent:
            violations.append("staged changes detected")
        if actual["forbidden_status"]:
            violations.append("forbidden Git status detected")
        for path_text in actual["changed_files"]:
            path = context["project_root"] / path_text
            if path.is_symlink() or (path.exists() and not path.is_file()):
                violations.append(f"unsafe changed path: {path_text}")
        owned_test_files = [
            path
            for path in context["manifest"]["owned_files"]
            if path.startswith("tests/") and path.endswith(".py")
        ]
        if not owned_test_files or any(
            not (context["project_root"] / path).is_file()
            or (context["project_root"] / path).is_symlink()
            for path in owned_test_files
        ):
            return {
                "status": "BLOCKED",
                "run_id": run_id,
                "reason": "owned Python test target is missing or unsafe",
                "hard_stop": True,
            }
        independent_checks.extend(_scan_owned_files(context["project_root"], list(context["manifest"]["owned_files"])))
        diff_check = _run_command(["git", "diff", "--check"], context["project_root"], 30)
        diff_passed = not diff_check["timeout"] and diff_check["exit_code"] == 0
        independent_checks.append(_check("git_diff_check", diff_passed, "git diff --check passed" if diff_passed else "git diff --check failed", exit_code=diff_check["exit_code"]))
        if not diff_passed:
            violations.append("git diff --check failed")
        tests, test_error = _run_tests(
            context["project_root"],
            context["interpreter"],
            list(context["manifest"]["owned_files"]),
            runner="unittest" if context["manifest"].get("interpreter_policy_id") == "IMMUTABLE_EXTERNAL_INTERPRETER" else "pytest",
        )
        test_ids = ("owned_tests", "wallet_pytest", "owned_imports")
        for index, identifier in enumerate(test_ids):
            result = tests[index] if index < len(tests) else {"exit_code": None, "timeout": False}
            passed = result.get("exit_code") == 0 and not result.get("timeout")
            independent_checks.append(_check(identifier, passed, "independent command passed" if passed else "independent command failed", exit_code=result.get("exit_code")))
        if context.get("interpreter_probe_required", True):
            try:
                interpreter_after = (_validate_external_interpreter(context["interpreter"])
                    if context["manifest"].get("interpreter_policy_id") == "IMMUTABLE_EXTERNAL_INTERPRETER"
                    else _validate_interpreter(context["project_root"], context["interpreter"],
                        allowed_system_roots=tuple(context.get("interpreter_allowed_system_roots", (Path("/usr/bin"), Path("/usr/local/bin"))))))
                if interpreter_after != context["interpreter_fingerprint"]:
                    violations.append("interpreter fingerprint changed during review")
            except LVReviewError as exc:
                violations.append(f"interpreter validation failed after tests: {exc}")
        else:
            interpreter_after = dict(context["interpreter_fingerprint"])
        actual_after = _actual_changes(context["project_root"])
        if any(actual_after[field] != actual[field] for field in ("changed_files", "created_files", "modified_files", "deleted_files")):
            violations.append("Git change set changed during independent tests")
        actual = actual_after
        after = _capture_git_evidence(context["project_root"])
        fingerprint_passed = all(after[field] == context["git_before"][field] for field in ("head", "tree", "index_fingerprint", "worktree_fingerprint"))
        independent_checks.append(_check("wallet_git_fingerprints", fingerprint_passed, "Wallet HEAD/index/worktree fingerprints are unchanged" if fingerprint_passed else "Wallet fingerprint drift detected"))
        immutable_git_fields = (
            "head",
            "tree",
            "index_fingerprint",
            "branch",
            "local_config_fingerprint",
            "remote_fingerprint",
            "submodule_fingerprint",
        )
        if any(after[field] != context["git_before"][field] for field in immutable_git_fields):
            violations.append("Git evidence changed during review")
        if test_error:
            violations.append(test_error)
        if payload.get("violations"):
            violations.append("worker reported violations")
        if payload.get("error") is not None:
            violations.append("worker reported an error")
        package_unchanged = _directory_snapshot(context["package_root"]) == package_snapshot
        preflight_unchanged = _directory_snapshot(evidence_root) == preflight_snapshot
        worker_unchanged = _file_snapshot(context["result_path"]) == worker_snapshot
        owned_content_after = _owned_content_snapshot(
            context["project_root"], list(context["manifest"]["owned_files"])
        )
        owned_content_stable = owned_content_after == owned_content_before
        independent_checks.append(_check(
            "owned_content_unchanged",
            owned_content_stable,
            "owned file content is unchanged during review" if owned_content_stable else "owned file content changed during review",
        ))
        if not owned_content_stable:
            violations.append("owned file content changed during independent checks")
        for identifier, passed, summary in (
            ("package_unchanged", package_unchanged, "sealed package manifest is unchanged"),
            ("preflight_unchanged", preflight_unchanged, "sealed preflight evidence is unchanged"),
            ("worker_result_unchanged", worker_unchanged, "original worker result is unchanged"),
        ):
            independent_checks.append(_check(identifier, passed, summary if passed else identifier + " failed"))
            if not passed:
                violations.append(identifier + " failed")
        failed_checks = [item["check"] for item in independent_checks if item["status"] != "PASS"]
        for identifier in failed_checks:
            marker = f"independent check failed: {identifier}"
            if marker not in violations:
                violations.append(marker)
        verdict = "PASS" if not violations else "FAIL"
        report = _build_report(
            context, worker_hash, verdict, actual=actual, violations=violations, after=after,
            independent_checks=independent_checks, interpreter_after=interpreter_after,
            prior_review_lineage=prior_review_lineage,
            owned_content_evidence={
                "algorithm": "sha256",
                "before": owned_content_before,
                "after": owned_content_after,
                "final": owned_content_after,
                "stable": owned_content_stable,
            },
        )
    except (LVReviewError, LVExecutionPackageError) as exc:
        if not context.get("preflight_evidence_sha256") or context.get("review_attempt", 1) > 1 and prior_review_lineage is None:
            return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
        if not owned_content_before and str(exc).startswith("owned "):
            return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
        report = _build_report(
            context, worker_hash, "BLOCKED", blockers=[str(exc)],
            reasons=["strict intake or identity validation failed"],
            independent_checks=independent_checks, interpreter_after=interpreter_after,
            prior_review_lineage=prior_review_lineage,
            owned_content_evidence={
                "algorithm": "sha256", "before": owned_content_before, "after": [], "final": [],
                "stable": False, "capture_status": "unavailable",
            },
        )
        if not worker_bytes:
            return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    try:
        sealed = _seal_review(context, report, worker_hash, worker_bytes)
    except LVReviewError as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    outcome = {"status": report["verdict"], "hard_stop": True, **sealed}
    if report.get("verdict") in {"BLOCKED", "FAIL"}:
        outcome["reason"] = report.get("blockers") or report.get("violations") or report.get("reasons") or "review blocked"
    return outcome
