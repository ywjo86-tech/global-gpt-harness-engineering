from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .lv_execution_package import canonical_json_bytes, validate_worker_result
from .lv_review import (
    REVIEW_REPORT_FIELDS, REVIEW_STATUS_FIELDS,
    _assert_package, _project_root_for, _result_path, _run_tests, _scan_owned_files,
    _validate_interpreter, _verify_preflight_evidence,
)

PACKAGE_SCHEMA = "orchestration.lv_remediation.package.v1"
PREFLIGHT_SCHEMA = "orchestration.lv_remediation.preflight.v1"
WORKER_SCHEMA = "orchestration.lv_remediation.worker.result.v1"
REVIEW_SCHEMA = "orchestration.lv_remediation.review.v1"
STATUS_SCHEMA = "orchestration.lv_remediation.status.v1"
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,63}\Z")
PACKAGE_FIELDS = {
    "schema_version", "run_id", "parent_run_id", "parent_review_attempt", "parent_worker_attempt",
    "project_id", "gate_id", "lv_id", "canonical_plan", "approval_id", "approval_record_hash",
    "gate_ledger_commit", "gate_ledger_sha256", "owned_files", "before_owned_content", "source_baseline",
    "reason_code", "reason", "change_policy", "parent_artifact_sha256", "parent_package_sha256",
    "parent_preflight_sha256", "worker_prompt_sha256", "created_at", "hard_stop", "transition_authorized",
}
PREFLIGHT_FIELDS = {
    "schema_version", "run_id", "manifest_sha256", "parent_run_id", "project_id", "gate_id", "lv_id",
    "canonical_plan", "before_owned_content", "worker_result_path", "captured_at", "hard_stop",
    "runtime_authorization", "transition_authorized",
}
_PARENT_FILES = {
    "review.status", "reviewer.report.json", "reviewer.report.sha256",
    "worker.result.json", "worker.result.sha256",
}


class LVRemediationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_id(value: str) -> str:
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
        raise LVRemediationError("run_id must be a safe non-empty path segment")
    return value


def _harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _root(run_id: str) -> Path:
    return _harness_root() / "_workspace" / "orchestration-remediations" / _safe_id(run_id)


def remediation_worker_result_path(run_id: str) -> Path:
    return Path("/tmp") / f"harness-lv-remediation-worker-result-{_safe_id(run_id)}.json"


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise LVRemediationError(f"required regular file is missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LVRemediationError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise LVRemediationError(f"JSON object required: {path.name}")
    return value


def _write_json(path: Path, value: object) -> str:
    data = canonical_json_bytes(value)
    path.write_bytes(data)
    return _sha(data)


def _atomic_seal(final: Path, files: dict[str, bytes]) -> None:
    if final.exists() or final.is_symlink():
        raise LVRemediationError(f"immutable artifact already exists: {final.name}")
    parent = final.parent
    if parent.exists() and parent.is_symlink():
        raise LVRemediationError("artifact parent is a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=str(parent)))
    try:
        for name, data in files.items():
            (temp / name).write_bytes(data)
        if {item.name for item in temp.iterdir()} != set(files):
            raise LVRemediationError("atomic artifact set mismatch")
        os.replace(temp, final)
    except Exception as exc:
        shutil.rmtree(temp, ignore_errors=True)
        if isinstance(exc, LVRemediationError):
            raise
        raise LVRemediationError("atomic artifact sealing failed") from exc


def _git(root: Path, *args: str) -> bytes:
    cp = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if cp.returncode:
        raise LVRemediationError(f"git {' '.join(args)} failed")
    return cp.stdout


def _index(root: Path) -> str:
    return _sha(_git(root, "ls-files", "-s", "-z"))


def _git_identity(root: Path) -> dict[str, str]:
    return {
        "branch": _git(root, "branch", "--show-current").decode().strip(),
        "head": _git(root, "rev-parse", "HEAD").decode().strip(),
        "tree": _git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        "index": _index(root),
    }


def _status_paths(root: Path) -> tuple[list[str], list[str]]:
    raw = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z").split(b"\0")
    paths: list[str] = []
    staged: list[str] = []
    for entry in raw:
        if not entry:
            continue
        text = entry.decode("utf-8")
        if len(text) < 4:
            raise LVRemediationError("malformed Git status entry")
        code, path = text[:2], text[3:]
        if " -> " in path:
            raise LVRemediationError("renames are forbidden during remediation")
        paths.append(path)
        if code[0] not in {" ", "?"}:
            staged.append(path)
    return sorted(set(paths)), sorted(set(staged))


def _snapshot(root: Path, owned: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for relative in owned:
        pure = PurePosixPath(relative)
        if not relative or pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
            raise LVRemediationError("owned path is unsafe")
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise LVRemediationError(f"owned file is missing or unsafe: {relative}")
        data = path.read_bytes()
        result.append({"path": relative, "sha256": _sha(data), "size": len(data)})
    return result


def _dir_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise LVRemediationError("artifact directory is missing or unsafe")
    entries = sorted(root.iterdir())
    if not all(p.is_file() and not p.is_symlink() for p in entries):
        raise LVRemediationError("artifact directory contains an unsafe entry")
    return {p.name: _sha(p.read_bytes()) for p in entries}


def _latest_parent(parent_run_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    base = _harness_root() / "_workspace" / "orchestration-results" / _safe_id(parent_run_id)
    attempts = sorted((p for p in base.glob("attempt-[0-9][0-9]") if p.is_dir()), key=lambda p: p.name)
    if not attempts:
        raise LVRemediationError("parent review attempt is missing")
    parent = attempts[-1]
    if {p.name for p in parent.iterdir()} != _PARENT_FILES:
        raise LVRemediationError("parent review artifact set mismatch")
    report = _json(parent / "reviewer.report.json")
    status = _json(parent / "review.status")
    report_hash = _sha((parent / "reviewer.report.json").read_bytes())
    if (parent / "reviewer.report.sha256").read_text(encoding="ascii").strip() != report_hash:
        raise LVRemediationError("parent reviewer sidecar mismatch")
    worker_hash = _sha((parent / "worker.result.json").read_bytes())
    if (parent / "worker.result.sha256").read_text(encoding="ascii").strip() != worker_hash:
        raise LVRemediationError("parent worker sidecar mismatch")
    if report.get("verdict") != "PASS" or report.get("hard_stop") is not True:
        raise LVRemediationError("parent must be a sealed PASS hard-stop review")
    if status.get("verdict") != "PASS" or status.get("hard_stop") is not True or status.get("reviewer_report_sha256") != report_hash:
        raise LVRemediationError("parent status does not bind the PASS report")
    if report.get("run_id") != parent_run_id or status.get("run_id") != parent_run_id:
        raise LVRemediationError("parent run identity mismatch")
    return parent, report, status


def _verify_parent(manifest: dict[str, Any]) -> None:
    parent, report, status = _latest_parent(str(manifest["parent_run_id"]))
    _validate_parent_lineage(str(manifest["parent_run_id"]), parent, report, status)
    actual = _dir_hashes(parent)
    if actual != manifest.get("parent_artifact_sha256"):
        raise LVRemediationError("parent review artifact drift")
    package = _harness_root() / "_workspace" / "orchestration-runs" / str(manifest["parent_run_id"])
    preflight = _harness_root() / "_workspace" / "orchestration-preflights" / str(manifest["parent_run_id"])
    if _dir_hashes(package) != manifest.get("parent_package_sha256"):
        raise LVRemediationError("parent package drift")
    if _dir_hashes(preflight) != manifest.get("parent_preflight_sha256"):
        raise LVRemediationError("parent preflight drift")
    if report.get("review_attempt") != manifest.get("parent_review_attempt") or status.get("worker_attempt") != manifest.get("parent_worker_attempt"):
        raise LVRemediationError("parent attempt lineage mismatch")



def _validate_parent_lineage(parent_run_id: str, parent: Path, report: dict[str, Any], status: dict[str, Any]) -> tuple[dict[str, Any], str]:
    package_root = _harness_root() / "_workspace" / "orchestration-runs" / parent_run_id
    manifest, manifest_path, _ = _assert_package(package_root, parent_run_id)
    project_root = _project_root_for(str(manifest.get("project_id", "")))
    historical_evidence = _json(_harness_root() / "_workspace" / "orchestration-preflights" / parent_run_id / "preflight.evidence.json")
    fingerprint_fields = {
        "python_version", "python_executable_sha256", "python_prefix_fingerprint",
        "python_base_prefix_fingerprint", "python_venv_verified", "python_owner_validation_mode",
        "python_namespace_fingerprint", "python_mount_fingerprint",
    }
    interpreter_fingerprint = {field: historical_evidence.get(field) for field in fingerprint_fields}
    if any(value in {None, ""} for value in interpreter_fingerprint.values()):
        raise LVRemediationError("parent preflight interpreter evidence is incomplete")
    evidence, evidence_hash = _verify_preflight_evidence({
        "run_id": parent_run_id, "manifest": manifest, "manifest_path": manifest_path,
        "preflight_root": _harness_root() / "_workspace" / "orchestration-preflights" / parent_run_id,
        "result_path": _result_path(parent_run_id), "interpreter_fingerprint": interpreter_fingerprint,
    })
    if set(report) != REVIEW_REPORT_FIELDS or set(status) != REVIEW_STATUS_FIELDS:
        raise LVRemediationError("parent review schema field set mismatch")
    worker_bytes = (parent / "worker.result.json").read_bytes()
    worker_hash = _sha(worker_bytes)
    worker = json.loads(worker_bytes.decode("utf-8"))
    validate_worker_result(worker, manifest)
    bindings = {
        "project": manifest["project_id"], "gate": manifest["gate_id"], "lv": manifest["lv_id"],
        "package_manifest_sha256": _sha(manifest_path.read_bytes()),
        "preflight_evidence_sha256": evidence_hash, "worker_result_sha256": worker_hash,
        "canonical_plan": {"path": manifest["canonical_plan_path"], "sha256": manifest["canonical_plan_sha256"]},
        "owned_files": manifest["owned_files"],
    }
    for field, expected in bindings.items():
        if report.get(field) != expected:
            raise LVRemediationError(f"parent review binding mismatch: {field}")
    status_bindings = {
        "run_id": parent_run_id, "review_attempt": report["review_attempt"],
        "worker_attempt": report["worker_attempt"], "verdict": "PASS", "hard_stop": True,
        "reviewer_report_sha256": _sha((parent / "reviewer.report.json").read_bytes()),
        "worker_result_sha256": worker_hash, "package_manifest_sha256": bindings["package_manifest_sha256"],
        "preflight_evidence_sha256": evidence_hash,
        "review_only_reexecution": report["review_only_reexecution"], "reran_worker": report["reran_worker"],
    }
    for field, expected in status_bindings.items():
        if status.get(field) != expected:
            raise LVRemediationError(f"parent review status binding mismatch: {field}")
    if evidence.get("owned_files") != report.get("owned_files"):
        raise LVRemediationError("parent preflight owned-files binding mismatch")
    return manifest, evidence_hash

def _load_package(run_id: str) -> tuple[Path, dict[str, Any]]:
    package = _root(run_id) / "package"
    manifest = _json(package / "remediation.manifest.json")
    if set(manifest) != PACKAGE_FIELDS or manifest.get("schema_version") != PACKAGE_SCHEMA or manifest.get("run_id") != run_id:
        raise LVRemediationError("remediation package schema or identity mismatch")
    digest = _sha((package / "remediation.manifest.json").read_bytes())
    if (package / "remediation.manifest.sha256").read_text(encoding="ascii").strip() != digest:
        raise LVRemediationError("remediation package sidecar mismatch")
    if {p.name for p in package.iterdir()} != {"remediation.manifest.json", "remediation.manifest.sha256", "worker_prompt.md", "package.status"}:
        raise LVRemediationError("remediation package artifact set mismatch")
    if _sha((package / "worker_prompt.md").read_bytes()) != manifest["worker_prompt_sha256"]:
        raise LVRemediationError("remediation worker prompt hash mismatch")
    package_status = _json(package / "package.status")
    if package_status != {"schema_version": STATUS_SCHEMA, "status": "SEALED", "hard_stop": True, "manifest_sha256": digest}:
        raise LVRemediationError("remediation package status mismatch")
    _verify_parent(manifest)
    return package, manifest


def _assert_baseline(root: Path, manifest: dict[str, Any], *, require_before: bool) -> None:
    identity = _git_identity(root)
    for field in ("branch", "head", "tree", "index"):
        if identity[field] != manifest["source_baseline"][field]:
            raise LVRemediationError(f"source baseline drift: {field}")
    paths, staged = _status_paths(root)
    owned = list(manifest["owned_files"])
    if staged:
        raise LVRemediationError("staged changes are forbidden during remediation evidence")
    if not set(paths).issubset(set(owned)):
        raise LVRemediationError("non-owned source drift")
    if require_before and _snapshot(root, owned) != manifest["before_owned_content"]:
        raise LVRemediationError("owned content no longer matches remediation before snapshot")


def create_remediation_package(parent_run_id: str, run_id: str, reason_code: str, reason: str) -> dict[str, Any]:
    parent_run_id, run_id = _safe_id(parent_run_id), _safe_id(run_id)
    if parent_run_id == run_id:
        raise LVRemediationError("remediation run must differ from parent run")
    if not _REASON_CODE.fullmatch(reason_code or ""):
        raise LVRemediationError("reason_code must be bounded uppercase snake case")
    if not isinstance(reason, str) or not reason.strip() or len(reason.encode("utf-8")) > 512:
        raise LVRemediationError("reason must be non-empty and at most 512 UTF-8 bytes")
    parent, report, status = _latest_parent(parent_run_id)
    parent_manifest, _ = _validate_parent_lineage(parent_run_id, parent, report, status)
    project = str(report.get("project", ""))
    root = _project_root_for(project)
    owned = report.get("owned_files")
    evidence = report.get("owned_content_evidence", {})
    if not isinstance(owned, list) or not owned or evidence.get("stable") is not True:
        raise LVRemediationError("parent owned-content binding is incomplete")
    before = _snapshot(root, owned)
    parent_final = evidence.get("final")
    if not isinstance(parent_final, list):
        raise LVRemediationError("parent final owned-content snapshot is missing")
    normalized_parent = [
        {"path": item.get("path"), "sha256": item.get("sha256"), "size": item.get("size")}
        for item in parent_final if isinstance(item, dict)
    ]
    if before != normalized_parent or len(normalized_parent) != len(parent_final):
        raise LVRemediationError("current owned content does not match parent final snapshot")
    identity = _git_identity(root)
    paths, staged = _status_paths(root)
    if staged or not set(paths).issubset(set(owned)):
        raise LVRemediationError("remediation baseline contains staged or non-owned changes")
    parent_package = _harness_root() / "_workspace" / "orchestration-runs" / parent_run_id
    parent_preflight = _harness_root() / "_workspace" / "orchestration-preflights" / parent_run_id
    parent_manifest_hash = _sha((parent_package / "package.manifest.json").read_bytes())
    parent_sidecar = parent_package / "package.manifest.sha256"
    if not parent_sidecar.is_file() or parent_sidecar.is_symlink() or parent_sidecar.read_text(encoding="ascii").strip() != parent_manifest_hash:
        raise LVRemediationError("parent package manifest sidecar mismatch")
    expected_bindings = {
        "project_id": project,
        "gate_id": report["gate"],
        "lv_id": report["lv"],
        "canonical_plan_path": report["canonical_plan"]["path"],
        "canonical_plan_sha256": report["canonical_plan"]["sha256"],
    }
    for field, expected in expected_bindings.items():
        if parent_manifest.get(field) != expected:
            raise LVRemediationError(f"parent package binding mismatch: {field}")
    manifest = {
        "schema_version": PACKAGE_SCHEMA,
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "parent_review_attempt": report["review_attempt"],
        "parent_worker_attempt": status["worker_attempt"],
        "project_id": project,
        "gate_id": report["gate"],
        "lv_id": report["lv"],
        "canonical_plan": report["canonical_plan"],
        "approval_id": parent_manifest.get("approval_id"),
        "approval_record_hash": parent_manifest.get("approval_record_hash"),
        "gate_ledger_commit": parent_manifest.get("gate_ledger_commit"),
        "gate_ledger_sha256": parent_manifest.get("gate_ledger_sha256"),
        "owned_files": owned,
        "before_owned_content": before,
        "source_baseline": identity,
        "reason_code": reason_code,
        "reason": reason.strip(),
        "change_policy": "owned_files_only",
        "parent_artifact_sha256": _dir_hashes(parent),
        "parent_package_sha256": _dir_hashes(parent_package),
        "parent_preflight_sha256": _dir_hashes(parent_preflight),
        "worker_prompt_sha256": "",
        "created_at": _now(),
        "hard_stop": True,
        "transition_authorized": False,
    }
    target = _root(run_id)
    if target.exists() or target.is_symlink():
        raise LVRemediationError("remediation run already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=str(target.parent)))
    try:
        package = temp / "package"
        package.mkdir()
        prompt = (
            f"# Manual LV Remediation Worker\n\nRun ID: {run_id}\nParent Run ID: {parent_run_id}\n"
            f"Project: {project}\nGate: {manifest['gate_id']}\nLV: {manifest['lv_id']}\n"
            f"Owned files: {', '.join(owned)}\nResult: {remediation_worker_result_path(run_id)}\n\n"
            f"Write canonical JSON with schema {WORKER_SCHEMA}. Bind the package and preflight SHA-256, "
            "before/after owned-content SHA-256 and size, dirty_owned_files, remediated_files, tests, commands, "
            "violations, error, worker_type=manual, and external runtime approval state. Do not run review, "
            "stage, commit, start another LV, access secrets, or use network/API access.\n"
        ).encode("utf-8")
        manifest["worker_prompt_sha256"] = _sha(prompt)
        digest = _write_json(package / "remediation.manifest.json", manifest)
        (package / "worker_prompt.md").write_bytes(prompt)
        (package / "remediation.manifest.sha256").write_text(digest + "\n", encoding="ascii")
        _write_json(package / "package.status", {"schema_version": STATUS_SCHEMA, "status": "SEALED", "hard_stop": True, "manifest_sha256": digest})
        os.replace(temp, target)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return {"status": "SEALED", "run_id": run_id, "manifest_sha256": digest, "hard_stop": True}


def create_remediation_preflight(run_id: str) -> dict[str, Any]:
    try:
        package, manifest = _load_package(_safe_id(run_id))
        root = _project_root_for(str(manifest["project_id"]))
        _assert_baseline(root, manifest, require_before=True)
        result = remediation_worker_result_path(run_id)
        if result.exists() or result.is_symlink():
            raise LVRemediationError("remediation worker result already exists")
        target = _root(run_id) / "preflight"
        if target.exists() or target.is_symlink():
            raise LVRemediationError("remediation preflight already exists")
        payload = {
            "schema_version": PREFLIGHT_SCHEMA, "run_id": run_id,
            "manifest_sha256": _sha((package / "remediation.manifest.json").read_bytes()),
            "parent_run_id": manifest["parent_run_id"], "project_id": manifest["project_id"],
            "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
            "canonical_plan": manifest["canonical_plan"], "before_owned_content": manifest["before_owned_content"],
            "worker_result_path": str(result), "captured_at": _now(), "hard_stop": True,
            "runtime_authorization": "not_granted_by_preflight", "transition_authorized": False,
        }
        evidence_bytes = canonical_json_bytes(payload)
        digest = _sha(evidence_bytes)
        worker_template = {
            "schema_version": WORKER_SCHEMA, "run_id": run_id, "parent_run_id": manifest["parent_run_id"],
            "manifest_sha256": payload["manifest_sha256"], "preflight_evidence_sha256": digest,
            "worker_attempt": 1, "status": "completed", "started_at": "<RFC3339>", "completed_at": "<RFC3339>",
            "before_owned_content": manifest["before_owned_content"], "after_owned_content": "<fill exact SHA-256/size snapshot>",
            "owned_files": manifest["owned_files"], "changed_files": "<fill remediated_files only>",
            "dirty_owned_files": "<fill current Git-dirty owned paths>", "remediated_files": "<fill before/after delta paths>",
            "tests": "<fill executed test summaries>", "commands_summary": "<fill bounded command summaries>",
            "violations": [], "error": None, "worker_type": "manual",
            "runtime_sandbox_approval_state": {"source": "external_codex_runtime", "state": "<user_approved|allowed_by_active_policy>", "business_approval_reused": False, "verified_by_harness": False},
        }
        worker_input = {
            "schema_version": "orchestration.lv_remediation.worker.input.v1", "run_id": run_id,
            "parent_run_id": manifest["parent_run_id"], "reason_code": manifest["reason_code"],
            "manifest_sha256": payload["manifest_sha256"], "preflight_evidence_sha256": digest,
            "result_path": str(result), "owned_files": manifest["owned_files"],
            "before_owned_content": manifest["before_owned_content"], "result_template": worker_template,
            "prohibitions": ["non-owned changes", "staging", "commit", "review self-execution", "next-LV transition", "network/API", "secret access"],
        }
        worker_input_bytes = canonical_json_bytes(worker_input)
        worker_input_hash = _sha(worker_input_bytes)
        status_bytes = canonical_json_bytes({"schema_version": STATUS_SCHEMA, "status": "READY", "hard_stop": True, "evidence_sha256": digest, "worker_input_sha256": worker_input_hash})
        _atomic_seal(target, {
            "preflight.evidence.json": evidence_bytes,
            "preflight.evidence.sha256": (digest + "\n").encode("ascii"),
            "worker.input.json": worker_input_bytes,
            "worker.input.sha256": (worker_input_hash + "\n").encode("ascii"),
            "preflight.status": status_bytes,
        })
        return {"status": "READY", "run_id": run_id, "preflight_evidence_sha256": digest, "hard_stop": True}
    except LVRemediationError as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}


def _load_preflight(run_id: str, manifest: dict[str, Any]) -> tuple[Path, dict[str, Any], str]:
    root = _root(run_id) / "preflight"
    expected = {"preflight.evidence.json", "preflight.evidence.sha256", "worker.input.json", "worker.input.sha256", "preflight.status"}
    if not root.is_dir() or {p.name for p in root.iterdir()} != expected:
        raise LVRemediationError("remediation preflight artifact set mismatch")
    evidence = _json(root / "preflight.evidence.json")
    digest = _sha((root / "preflight.evidence.json").read_bytes())
    if (root / "preflight.evidence.sha256").read_text(encoding="ascii").strip() != digest:
        raise LVRemediationError("remediation preflight sidecar mismatch")
    status = _json(root / "preflight.status")
    worker_input = _json(root / "worker.input.json")
    worker_input_hash = _sha((root / "worker.input.json").read_bytes())
    if (root / "worker.input.sha256").read_text(encoding="ascii").strip() != worker_input_hash:
        raise LVRemediationError("remediation worker input sidecar mismatch")
    expected_worker_input = {
        "schema_version": "orchestration.lv_remediation.worker.input.v1", "run_id": run_id,
        "parent_run_id": manifest["parent_run_id"], "reason_code": manifest["reason_code"],
        "manifest_sha256": _sha((_root(run_id) / "package" / "remediation.manifest.json").read_bytes()),
        "preflight_evidence_sha256": digest, "result_path": str(remediation_worker_result_path(run_id)),
        "owned_files": manifest["owned_files"], "before_owned_content": manifest["before_owned_content"],
    }
    for field, expected_value in expected_worker_input.items():
        if worker_input.get(field) != expected_value:
            raise LVRemediationError(f"remediation worker input mismatch: {field}")
    if not isinstance(worker_input.get("result_template"), dict) or set(worker_input["result_template"]) != {
        "schema_version", "run_id", "parent_run_id", "manifest_sha256", "preflight_evidence_sha256",
        "worker_attempt", "status", "started_at", "completed_at", "before_owned_content", "after_owned_content",
        "owned_files", "changed_files", "dirty_owned_files", "remediated_files", "tests", "commands_summary",
        "violations", "error", "worker_type", "runtime_sandbox_approval_state",
    }:
        raise LVRemediationError("remediation worker input template mismatch")
    if set(evidence) != PREFLIGHT_FIELDS or evidence.get("schema_version") != PREFLIGHT_SCHEMA or evidence.get("run_id") != run_id or evidence.get("manifest_sha256") != _sha((_root(run_id) / "package" / "remediation.manifest.json").read_bytes()):
        raise LVRemediationError("remediation preflight schema or identity mismatch")
    if status != {"schema_version": STATUS_SCHEMA, "status": "READY", "hard_stop": True, "evidence_sha256": digest, "worker_input_sha256": worker_input_hash}:
        raise LVRemediationError("remediation preflight status mismatch")
    if evidence.get("before_owned_content") != manifest.get("before_owned_content"):
        raise LVRemediationError("remediation preflight before-content mismatch")
    return root, evidence, digest


def _validate_worker(payload: dict[str, Any], manifest: dict[str, Any], preflight_hash: str, after: list[dict[str, Any]], dirty: list[str], remediated: list[str]) -> None:
    required = {
        "schema_version", "run_id", "parent_run_id", "manifest_sha256", "preflight_evidence_sha256",
        "worker_attempt", "status", "started_at", "completed_at", "before_owned_content", "after_owned_content",
        "owned_files", "changed_files", "dirty_owned_files", "remediated_files", "tests", "commands_summary", "violations", "error", "worker_type",
        "runtime_sandbox_approval_state",
    }
    if set(payload) != required:
        raise LVRemediationError("remediation worker result field set mismatch")
    if payload["schema_version"] != WORKER_SCHEMA or payload["run_id"] != manifest["run_id"] or payload["parent_run_id"] != manifest["parent_run_id"]:
        raise LVRemediationError("remediation worker identity mismatch")
    if payload["manifest_sha256"] != _sha((_root(manifest["run_id"]) / "package" / "remediation.manifest.json").read_bytes()) or payload["preflight_evidence_sha256"] != preflight_hash:
        raise LVRemediationError("remediation worker seal binding mismatch")
    if payload["worker_attempt"] != 1 or payload["worker_type"] != "manual" or payload["status"] != "completed" or payload["error"] is not None:
        raise LVRemediationError("remediation worker execution contract mismatch")
    if payload["owned_files"] != manifest["owned_files"] or payload["before_owned_content"] != manifest["before_owned_content"] or payload["after_owned_content"] != after:
        raise LVRemediationError("remediation worker content binding mismatch")
    if sorted(payload["dirty_owned_files"]) != dirty or sorted(payload["remediated_files"]) != remediated or sorted(payload["changed_files"]) != remediated:
        raise LVRemediationError("remediation worker changed-files mismatch")
    state = payload.get("runtime_sandbox_approval_state")
    if not isinstance(state, dict) or state.get("source") != "external_codex_runtime" or state.get("state") not in {"user_approved", "allowed_by_active_policy"} or state.get("business_approval_reused") is not False or state.get("verified_by_harness") is not False:
        raise LVRemediationError("remediation worker runtime approval state mismatch")


def _run_checks(root: Path, owned: list[str]) -> tuple[list[dict[str, Any]], bool]:
    checks = _scan_owned_files(root, owned)
    interpreter = root / ".venv" / "bin" / "python"
    try:
        _validate_interpreter(root, interpreter)
        test_results, test_error = _run_tests(root, interpreter, owned)
    except Exception as exc:
        test_results, test_error = [], str(exc)
    for index, result in enumerate(test_results):
        checks.append({
            "check": ("focused_tests", "full_tests", "owned_imports")[min(index, 2)],
            "status": "PASS" if result.get("exit_code") == 0 and not result.get("timeout") else "FAIL",
            "exit_code": result.get("exit_code"),
        })
    if test_error and not test_results:
        checks.append({"check": "owned_tests", "status": "FAIL", "summary": test_error[:240]})
    diff_ok = True
    diff_codes: list[int] = []
    for relative in owned:
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--no-index", "--check", "/dev/null", relative],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=60,
        )
        diff_codes.append(diff.returncode)
        output = diff.stdout.decode("utf-8", errors="replace")
        whitespace_error = re.search(r"(?m)^.+:\d+: (?:trailing whitespace|space before tab|new blank line at EOF)\.?$", output) is not None
        diff_ok &= diff.returncode in {0, 1} and not whitespace_error
    checks.append({"check": "owned_bytes_diff_check", "status": "PASS" if diff_ok else "FAIL", "exit_codes": diff_codes})
    return checks, not test_error and all(item.get("status") == "PASS" for item in checks)


def review_remediation(run_id: str) -> dict[str, Any]:
    try:
        run_id = _safe_id(run_id)
        package, manifest = _load_package(run_id)
        preflight, _, preflight_hash = _load_preflight(run_id, manifest)
        root = _project_root_for(str(manifest["project_id"]))
        _assert_baseline(root, manifest, require_before=False)
        actual, staged = _status_paths(root)
        if staged or not set(actual).issubset(set(manifest["owned_files"])):
            raise LVRemediationError("remediation review found staged or non-owned changes")
        after_before = _snapshot(root, manifest["owned_files"])
        before_by_path = {item["path"]: item for item in manifest["before_owned_content"]}
        remediated = sorted(item["path"] for item in after_before if item != before_by_path.get(item["path"]))
        if not remediated:
            raise LVRemediationError("remediation produced no owned-content change")
        result_path = remediation_worker_result_path(run_id)
        worker_bytes = result_path.read_bytes() if result_path.is_file() and not result_path.is_symlink() else b""
        if not worker_bytes:
            raise LVRemediationError("remediation worker result is missing")
        worker = json.loads(worker_bytes.decode("utf-8"))
        if not isinstance(worker, dict):
            raise LVRemediationError("remediation worker result must be an object")
        _validate_worker(worker, manifest, preflight_hash, after_before, actual, remediated)
        package_hashes = _dir_hashes(package)
        preflight_hashes = _dir_hashes(preflight)
        checks, passed = _run_checks(root, manifest["owned_files"])
        _assert_baseline(root, manifest, require_before=False)
        after_after = _snapshot(root, manifest["owned_files"])
        stable = after_before == after_after
        passed &= stable and _dir_hashes(package) == package_hashes and _dir_hashes(preflight) == preflight_hashes and result_path.read_bytes() == worker_bytes
        verdict = "PASS" if passed else "FAIL"
        report = {
            "schema_version": REVIEW_SCHEMA, "run_id": run_id, "parent_run_id": manifest["parent_run_id"],
            "project": manifest["project_id"], "gate": manifest["gate_id"], "lv": manifest["lv_id"],
            "reviewed_at": _now(), "verdict": verdict, "hard_stop": True,
            "transition_authorized": False, "checkpoint_authorized": False,
            "reason_code": manifest["reason_code"], "canonical_plan": manifest["canonical_plan"],
            "approval_id": manifest["approval_id"], "approval_record_hash": manifest["approval_record_hash"],
            "parent_lineage": {"run_id": manifest["parent_run_id"], "review_attempt": manifest["parent_review_attempt"], "worker_attempt": manifest["parent_worker_attempt"], "artifact_sha256": manifest["parent_artifact_sha256"]},
            "manifest_sha256": _sha((package / "remediation.manifest.json").read_bytes()),
            "preflight_evidence_sha256": preflight_hash, "worker_result_sha256": _sha(worker_bytes),
            "worker_attempt": 1, "reran_worker": True, "review_only_reexecution": False,
            "owned_files": manifest["owned_files"], "dirty_owned_files": actual, "changed_files": remediated,
            "owned_content_evidence": {"algorithm": "sha256", "before": manifest["before_owned_content"], "after": after_before, "final": after_after, "stable": stable},
            "independent_checks": checks, "violations": [] if passed else ["independent remediation validation failed"],
        }
        target = _root(run_id) / "review"
        if target.exists() or target.is_symlink():
            raise LVRemediationError("remediation review already exists")
        report_bytes = canonical_json_bytes(report)
        report_hash = _sha(report_bytes)
        status_bytes = canonical_json_bytes({"schema_version": STATUS_SCHEMA, "status": verdict, "verdict": verdict, "hard_stop": True, "transition_authorized": False, "run_id": run_id, "parent_run_id": manifest["parent_run_id"], "reviewer_report_sha256": report_hash, "worker_result_sha256": _sha(worker_bytes)})
        _atomic_seal(target, {
            "reviewer.report.json": report_bytes,
            "reviewer.report.sha256": (report_hash + "\n").encode("ascii"),
            "worker.result.json": worker_bytes,
            "worker.result.sha256": (_sha(worker_bytes) + "\n").encode("ascii"),
            "review.status": status_bytes,
        })
        return {"status": verdict, "run_id": run_id, "reviewer_report_sha256": report_hash, "worker_result_sha256": _sha(worker_bytes), "hard_stop": True}
    except (LVRemediationError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
