from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract_adapter import evaluate_canonical_state, load_project_mapping, sha256_file
from .lv_preview import LVPreviewValidationError, preview_lv_read_only


MANIFEST_SCHEMA_VERSION = "orchestration.lv_execution_package.v1"
WORKER_RESULT_SCHEMA_VERSION = "orchestration.lv_worker.result.v1"
PACKAGE_STATUS = "sealed"
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RESULT_STATUSES = {"completed", "partial", "failed", "blocked", "aborted"}
_RUNTIME_APPROVAL_STATES = {
    "allowed_by_active_policy",
    "user_approved",
    "denied",
    "unknown",
    "not_requested",
}
_RESULT_ARRAY_FIELDS = (
    "changed_files",
    "created_files",
    "modified_files",
    "deleted_files",
    "tests",
    "commands_summary",
    "violations",
)


class LVExecutionPackageError(ValueError):
    pass


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_canonical_json(path: Path, payload: object) -> str:
    data = canonical_json_bytes(payload)
    path.write_bytes(data)
    return _sha256_bytes(data)


def _git(project_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise LVExecutionPackageError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def _safe_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise LVExecutionPackageError("run_id must be a safe non-empty path segment")
    return run_id


def _canonical_root(project_root: str | Path) -> Path:
    supplied = Path(project_root)
    if not supplied.exists() or not supplied.is_dir():
        raise LVExecutionPackageError("project root must be an existing directory")
    absolute = supplied.absolute()
    root = supplied.resolve()
    if absolute != root:
        raise LVExecutionPackageError("project root may not contain symlinked path components")
    return root


def _project_root_fingerprint(root: Path) -> str:
    return _sha256_bytes(str(root).encode("utf-8"))


def _assert_clean_source(root: Path) -> None:
    status = _git(root, "status", "--porcelain=v1")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    if status.strip() or untracked.strip():
        raise LVExecutionPackageError("project worktree must be clean with no staged or untracked files")


def _tracked_content_fingerprint(root: Path) -> str:
    paths = _git(root, "ls-files", "-z").split(b"\0")
    digest = hashlib.sha256()
    for raw_path in sorted(path for path in paths if path):
        relative = raw_path.decode("utf-8")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise LVExecutionPackageError(f"tracked source path is not a regular file: {relative}")
        digest.update(raw_path)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _index_fingerprint(root: Path) -> str:
    return _sha256_bytes(_git(root, "ls-files", "-s", "-z"))


def _ledger_binding(root: Path, mapping: Any, canonical_state: dict[str, Any]) -> dict[str, str]:
    ledger_path = mapping.gate_state_ledger_path
    if ledger_path is None:
        raise LVExecutionPackageError("a committed Gate ledger is required")
    relative = ledger_path.relative_to(root).as_posix()
    commit = _git(root, "rev-list", "-n", "1", "HEAD", "--", relative).decode("ascii").strip()
    if not commit:
        raise LVExecutionPackageError("no committed Gate ledger revision exists")
    committed = _git(root, "show", f"{commit}:{relative}")
    current = ledger_path.read_bytes()
    if committed != current:
        raise LVExecutionPackageError("working Gate ledger differs from committed ledger content")
    blob_oid = _git(root, "rev-parse", f"{commit}:{relative}").decode("ascii").strip()
    if canonical_state.get("ledger_path") != relative:
        raise LVExecutionPackageError("lifecycle ledger path does not match the mapped ledger")
    expected_hash = _sha256_bytes(committed)
    return {
        "commit": commit,
        "blob_oid": blob_oid,
        "sha256": expected_hash,
        "path": relative,
    }


def _source_snapshot(root: Path, preview: dict[str, Any], ledger: dict[str, str]) -> dict[str, Any]:
    source_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    source_tree = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    return {
        "project_id": root.name,
        "source_head": source_head,
        "source_tree": source_tree,
        "source_index_fingerprint": _index_fingerprint(root),
        "source_worktree_fingerprint": _tracked_content_fingerprint(root),
        "source_worktree_state": "clean",
        "canonical_plan_path": preview["selected_canonical_plan"]["path"],
        "canonical_plan_sha256": preview["selected_canonical_plan"]["sha256"],
        "gate_ledger_commit": ledger["commit"],
        "gate_ledger_blob_oid": ledger["blob_oid"],
        "gate_ledger_sha256": ledger["sha256"],
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _worker_prompt(manifest: dict[str, Any]) -> str:
    task = manifest["task"]
    owned = "\n".join(f"- {item}" for item in manifest["owned_files"])
    checks = "\n".join(f"- {item}" for item in manifest["completion_checks"])
    return (
        "# Manual LV Worker Package\n\n"
        f"Run ID: {manifest['run_id']}\n"
        f"Project ID: {manifest['project_id']}\n"
        f"Gate ID: {manifest['gate_id']}\n"
        f"LV ID: {manifest['lv_id']}\n"
        "Package manifest SHA-256: verify package.manifest.sha256\n\n"
        "## Required checks\n"
        "- Verify package.manifest.sha256 before any action.\n"
        "- Re-verify source_snapshot.json, HEAD, tree, index, and clean worktree.\n"
        "- This package does not grant runtime or sandbox permission.\n"
        "- Execute only in a separately authorized external Codex runtime session.\n"
        "- Business/Gate approval must not be reused as runtime permission.\n"
        "- Do not modify the package manifest to change approval state.\n"
        "- Record the runtime state observed at execution time in the result object.\n"
        "- Worker reporting is not Harness final approval or verification.\n\n"
        "## Task context\n"
        f"Purpose: {task['purpose']}\n"
        f"Dependencies: {', '.join(manifest['dependencies']) or 'none'}\n"
        "Completion checks:\n"
        f"{checks or '- none'}\n\n"
        "## Editable scope\n"
        f"{owned}\n\n"
        "## Mandatory prohibitions\n"
        "- Do not create, modify, or delete any file outside editable scope.\n"
        "- Do not modify the plan, approval, checkpoint, or Gate ledger.\n"
        "- Do not expand the Gate or LV scope or work on a later LV.\n"
        "- Do not run git add, commit, or push.\n"
        "- Do not use network access or install packages.\n"
        "- Do not print secrets or environment variable values.\n"
        "- Worker self-PASS is not final Business/Gate approval.\n\n"
        "## Required result\n"
        f"Return JSON matching {WORKER_RESULT_SCHEMA_VERSION}; include the exact run/package/gate/LV identity, source before/after evidence, file arrays, tests, commands, violations, and structured error.\n"
    )


def _manifest_payload(
    root: Path,
    run_id: str,
    preview: dict[str, Any],
    canonical_state: dict[str, Any],
    ledger: dict[str, str],
    package_input_hash: str,
    snapshot_hash: str,
    prompt_hash: str,
    source_snapshot: dict[str, Any],
) -> dict[str, Any]:
    selected = preview["selected_lv"]
    source_head = source_snapshot["source_head"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_status": PACKAGE_STATUS,
        "project_id": root.name,
        "project_root_fingerprint": _project_root_fingerprint(root),
        "package_input_sha256": package_input_hash,
        "source_snapshot_sha256": snapshot_hash,
        "worker_prompt_sha256": prompt_hash,
        "source_head": source_head,
        "source_tree": source_snapshot["source_tree"],
        "source_index_fingerprint": source_snapshot["source_index_fingerprint"],
        "source_worktree_fingerprint": source_snapshot["source_worktree_fingerprint"],
        "canonical_plan_path": preview["selected_canonical_plan"]["path"],
        "canonical_plan_sha256": preview["selected_canonical_plan"]["sha256"],
        "gate_id": selected["gate_id"],
        "lv_id": selected["lv_id"],
        "approval_id": canonical_state.get("approval_id"),
        "approval_record_hash": canonical_state.get("approval_record_hash"),
        "checkpoint_commit": canonical_state.get("checkpoint_commit"),
        "gate_ledger_commit": ledger["commit"],
        "gate_ledger_blob_oid": ledger["blob_oid"],
        "gate_ledger_sha256": ledger["sha256"],
        "active_scope": list(canonical_state["active_scope"]),
        "owned_files": list(preview["approved_owned_files"]),
        "task": {
            "purpose": selected["purpose"],
            "execution": selected["execution"],
        },
        "dependencies": list(selected["dependencies"]),
        "completion_checks": list(selected["completion_criteria"]),
        "execution_mode": "manual",
        "business_scope_mutation_policy": "owned_files_only",
        "execution_authorization_required": True,
        "runtime_sandbox_approval_state": {
            "source": "external_codex_runtime",
            "state": "not_requested",
            "business_approval_reused": False,
            "verified_by_harness": False,
        },
        "worker_result_schema_version": WORKER_RESULT_SCHEMA_VERSION,
    }


def validate_worker_result(payload: object, manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LVExecutionPackageError("worker result must be a JSON object")
    required = {
        "schema_version", "run_id", "package_manifest_sha256", "gate_id", "lv_id", "status",
        "started_at", "completed_at", "source_head_before", "source_head_after", "source_tree_before",
        "source_tree_after", "source_index_before", "source_index_after", "source_worktree_before",
        "source_worktree_after", *_RESULT_ARRAY_FIELDS, "error", "worker_type", "runtime_sandbox_approval_state",
    }
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise LVExecutionPackageError(f"worker result missing fields: {', '.join(missing)}")
    if payload["schema_version"] != WORKER_RESULT_SCHEMA_VERSION:
        raise LVExecutionPackageError("unsupported worker result schema version")
    if payload["run_id"] != manifest["run_id"] or payload["package_manifest_sha256"] != manifest["manifest_sha256"]:
        raise LVExecutionPackageError("worker result package identity mismatch")
    if payload["gate_id"] != manifest["gate_id"] or payload["lv_id"] != manifest["lv_id"]:
        raise LVExecutionPackageError("worker result Gate/LV identity mismatch")
    if payload["status"] not in _RESULT_STATUSES:
        raise LVExecutionPackageError("worker result status is invalid")
    for field in _RESULT_ARRAY_FIELDS:
        if not isinstance(payload[field], list):
            raise LVExecutionPackageError(f"worker result field must be an array: {field}")
    if payload["status"] == "completed" and payload["error"] is not None:
        raise LVExecutionPackageError("completed worker result must have error=null")
    if payload["status"] != "completed" and not isinstance(payload["error"], dict):
        raise LVExecutionPackageError("non-completed worker result must have a structured error")
    runtime_state = payload["runtime_sandbox_approval_state"]
    if not isinstance(runtime_state, dict):
        raise LVExecutionPackageError("runtime/sandbox approval state must be an object")
    runtime_required = {"source", "state", "business_approval_reused", "verified_by_harness"}
    missing_runtime = sorted(runtime_required - runtime_state.keys())
    if missing_runtime:
        raise LVExecutionPackageError(
            f"runtime/sandbox approval state missing fields: {', '.join(missing_runtime)}"
        )
    if runtime_state["source"] != "external_codex_runtime":
        raise LVExecutionPackageError("runtime/sandbox approval source is invalid")
    if runtime_state["business_approval_reused"] is not False:
        raise LVExecutionPackageError("business approval cannot be reused as runtime approval")
    if runtime_state["verified_by_harness"] is not False:
        raise LVExecutionPackageError("Harness verification cannot be self-reported")
    state = runtime_state["state"]
    if not isinstance(state, str) or state not in _RUNTIME_APPROVAL_STATES:
        raise LVExecutionPackageError("runtime/sandbox approval state is invalid")
    status = payload["status"]
    if status == "completed" and state not in {"allowed_by_active_policy", "user_approved"}:
        raise LVExecutionPackageError("completed worker result requires runtime approval")
    if status == "blocked" and state not in {"denied", "unknown", "not_requested"}:
        raise LVExecutionPackageError("blocked worker result has inconsistent runtime state")
    return dict(payload)


def create_lv_execution_package(
    project_root: str | Path,
    gate_id: str,
    lv_id: str,
    run_id: str,
    *,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _canonical_root(project_root)
    run_id = _safe_run_id(run_id)
    _assert_clean_source(root)
    preview = preview_lv_read_only(root, gate_id, lv_id)
    mapping = load_project_mapping(root)
    if mapping is None:
        raise LVExecutionPackageError("a project contract mapping is required")
    canonical_state = evaluate_canonical_state(mapping)
    for field in ("gate_id", "approval_id", "approval_record_hash", "checkpoint_commit", "selected_source", "canonical_plan", "plan_sha256", "active_scope", "owned_files"):
        if canonical_state.get(field) in (None, "", []):
            raise LVExecutionPackageError(f"canonical lifecycle evidence is missing: {field}")
    if canonical_state.get("gate_id") != gate_id or canonical_state.get("active_scope") != [lv_id]:
        raise LVExecutionPackageError("canonical lifecycle evidence does not match the requested Gate/LV")
    ledger = _ledger_binding(root, mapping, canonical_state)
    source_snapshot = _source_snapshot(root, preview, ledger)
    package_input = {
        "project_root": str(root),
        "project_id": root.name,
        "run_id": run_id,
        "gate_id": gate_id,
        "lv_id": lv_id,
        "canonical_plan_path": preview["selected_canonical_plan"]["path"],
        "canonical_plan_sha256": preview["selected_canonical_plan"]["sha256"],
        "project_root_fingerprint": _project_root_fingerprint(root),
        "source_head": source_snapshot["source_head"],
        "source_tree": source_snapshot["source_tree"],
        "source_index_fingerprint": source_snapshot["source_index_fingerprint"],
        "source_worktree_fingerprint": source_snapshot["source_worktree_fingerprint"],
        "gate_ledger_commit": ledger["commit"],
        "gate_ledger_blob_oid": ledger["blob_oid"],
        "gate_ledger_sha256": ledger["sha256"],
        "execution_mode": "manual",
        "execution_authorization_required": True,
    }
    selected = preview["selected_lv"]
    task_manifest = {
        "purpose": selected["purpose"],
        "execution": selected["execution"],
    }
    package_input_hash = _sha256_bytes(canonical_json_bytes(package_input))
    source_snapshot_hash = _sha256_bytes(canonical_json_bytes(source_snapshot))
    manifest_seed = {
        "run_id": run_id,
        "project_id": root.name,
        "gate_id": gate_id,
        "lv_id": lv_id,
        "task": task_manifest,
    }
    prompt_seed = {"manifest": manifest_seed, "owned_files": preview["approved_owned_files"]}
    prompt_hash = _sha256_bytes(canonical_json_bytes(prompt_seed))
    manifest = _manifest_payload(
        root,
        run_id,
        preview,
        canonical_state,
        ledger,
        package_input_hash,
        source_snapshot_hash,
        prompt_hash,
        source_snapshot,
    )

    harness_root = Path(__file__).resolve().parents[2]
    base = Path(output_root).resolve() if output_root is not None else harness_root / "_workspace" / "orchestration-runs"
    base.mkdir(parents=True, exist_ok=True)
    final_dir = base / run_id
    if final_dir.exists() or final_dir.is_symlink():
        raise LVExecutionPackageError("run_id already exists")
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.tmp-", dir=str(base)))
    try:
        input_path = temp_dir / "package.input.json"
        snapshot_path = temp_dir / "source_snapshot.json"
        prompt_path = temp_dir / "worker_prompt.md"
        package_input_hash = _write_canonical_json(input_path, package_input)
        source_snapshot_hash = _write_canonical_json(snapshot_path, source_snapshot)
        prompt_text = _worker_prompt(manifest)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        prompt_hash = sha256_file(prompt_path)
        manifest["package_input_sha256"] = package_input_hash
        manifest["source_snapshot_sha256"] = source_snapshot_hash
        manifest["worker_prompt_sha256"] = prompt_hash
        manifest_hash = _write_canonical_json(temp_dir / "package.manifest.json", manifest)
        prompt_path.write_text(_worker_prompt(manifest), encoding="utf-8")
        prompt_hash = sha256_file(prompt_path)
        if prompt_hash != manifest["worker_prompt_sha256"]:
            raise LVExecutionPackageError("worker prompt hash changed during sealing")
        (temp_dir / "package.manifest.sha256").write_text(manifest_hash + "\n", encoding="ascii")
        status_payload = {"manifest_sha256": manifest_hash, "package_status": PACKAGE_STATUS}
        _write_canonical_json(temp_dir / "package.status", status_payload)
        manifest["manifest_sha256"] = manifest_hash
        expected = {
            "package.manifest.json", "package.manifest.sha256", "package.input.json",
            "worker_prompt.md", "source_snapshot.json", "package.status",
        }
        if {path.name for path in temp_dir.iterdir()} != expected:
            raise LVExecutionPackageError("sealed package contains an unexpected file")
        os.replace(temp_dir, final_dir)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        if final_dir.exists():
            raise LVExecutionPackageError("package sealing failed after final directory creation")
        raise
    return {
        "run_id": run_id,
        "package_root": str(final_dir),
        "manifest": manifest,
        "manifest_sha256": manifest_hash,
    }
