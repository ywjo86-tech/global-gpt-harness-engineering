from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


class LVReviewError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def _results_root(run_id: str) -> Path:
    _safe_run_id(run_id)
    return _harness_root() / "_workspace" / "orchestration-results" / run_id


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
    if {entry.name for entry in entries} != expected or not all(entry.is_file() and not entry.is_symlink() for entry in entries):
        raise LVReviewError("sealed package must contain exactly six regular files")
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


def _assert_canonical_binding(root: Path, manifest: dict[str, Any]) -> None:
    mapping = load_project_mapping(root)
    if mapping is None:
        raise LVReviewError("project contract mapping is required")
    state = evaluate_canonical_state(mapping)
    ledger = _ledger_binding(root, mapping, state)
    checks = {
        "project_id": root.name,
        "gate_id": "GATE-1",
        "lv_id": "G1-LV3-1",
        "canonical_plan_path": state.get("canonical_plan"),
        "canonical_plan_sha256": state.get("plan_sha256"),
        "approval_id": state.get("approval_id"),
        "approval_record_hash": state.get("approval_record_hash"),
        "checkpoint_commit": state.get("checkpoint_commit"),
        "gate_ledger_commit": ledger["commit"],
        "gate_ledger_blob_oid": ledger["blob_oid"],
        "gate_ledger_sha256": ledger["sha256"],
        "active_scope": ["G1-LV3-1"],
        "owned_files": ["app/config.py", "tests/test_config.py"],
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
    results_root = results_root or _results_root(run_id)
    if results_root.exists() or results_root.is_symlink():
        raise LVReviewError("review attempt-01 already exists")
        interpreter = interpreter or root / ".venv" / "bin" / "python"
    expected_interpreter = root / ".venv" / "bin" / "python"
    if interpreter != expected_interpreter or not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise LVReviewError("Wallet .venv/bin/python is unavailable")
    git_before = _capture_git_evidence(root)
    if not git_before["branch"]:
        raise LVReviewError("detached HEAD is not allowed for preflight")
    return {
        "run_id": run_id,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "source": source,
        "project_root": root,
        "package_root": package_root,
        "result_path": result_path,
        "results_root": results_root,
        "interpreter": interpreter,
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
        "python_version": _python_version(context["interpreter"]),
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


def preflight_run(run_id: str) -> dict[str, Any]:
    try:
        context = _preflight(run_id)
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


def _verify_preflight_evidence(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    root = Path(context.get("preflight_root") or _preflight_root(context["run_id"]))
    expected = {"preflight.evidence.json", "preflight.evidence.sha256", "preflight.status"}
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
    if evidence.get("python_interpreter_reference") != ".venv/bin/python" or not evidence.get("python_version"):
        raise LVReviewError("preflight Python evidence is invalid")
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


def _run_tests(root: Path, interpreter: Path) -> tuple[list[dict[str, Any]], str | None]:
    target = root / "tests" / "test_config.py"
    if not target.is_file() or target.is_symlink():
        return [], "tests/test_config.py is missing or unsafe"
    commands = [
        ([str(interpreter), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_config.py"], 60),
        ([str(interpreter), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"], 180),
        ([str(interpreter), "-B", "-c", "import app.config"], 30),
    ]
    results: list[dict[str, Any]] = []
    for argv, timeout in commands:
        result = _run_command(argv, root, timeout)
        results.append({key: value for key, value in result.items() if key not in {"stdout", "stderr"}})
        if result["timeout"] or result["exit_code"] != 0:
            return results, "independent test command failed"
    return results, None


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
) -> dict[str, Any]:
    manifest = context["manifest"]
    actual = actual or {key: [] for key in ("changed_files", "created_files", "modified_files", "deleted_files")}
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "run_id": context["run_id"],
        "package_manifest_sha256": _sha256(context["manifest_path"].read_bytes()),
        "worker_result_sha256": worker_hash,
        "gate_id": manifest.get("gate_id"),
        "lv_id": manifest.get("lv_id"),
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict,
        "hard_stop": True,
        "source_before": context["git_before"],
        "source_after": after or {},
        "actual_changed_files": actual.get("changed_files", []),
        "actual_created_files": actual.get("created_files", []),
        "actual_modified_files": actual.get("modified_files", []),
        "actual_deleted_files": actual.get("deleted_files", []),
        "owned_files": manifest.get("owned_files", []),
        "git_evidence": {"before": context["git_before"], "after": after or {}},
        "test_results": tests or [],
        "violations": violations or [],
        "blockers": blockers or [],
        "reasons": reasons or [],
    }


def _seal_review(context: dict[str, Any], report: dict[str, Any], worker_hash: str, worker_bytes: bytes) -> dict[str, Any]:
    final_root = context["results_root"]
    if final_root.exists() or final_root.is_symlink():
        raise LVReviewError("review attempt-01 already exists")
    parent = final_root.parent
    if parent.exists() and parent.is_symlink():
        raise LVReviewError("review result parent is a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=f".{context['run_id']}.", dir=str(parent)))
    report_bytes = canonical_json_bytes(report)
    report_hash = _sha256(report_bytes)
    status = {
        "verdict": report["verdict"],
        "hard_stop": True,
        "reviewer_report_sha256": report_hash,
        "worker_result_sha256": worker_hash,
        "package_manifest_sha256": report["package_manifest_sha256"],
        "preflight_evidence_sha256": report.get("preflight_evidence_sha256", ""),
    }
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
    package_root: Path | None = None,
    result_path: Path | None = None,
    results_root: Path | None = None,
    interpreter: Path | None = None,
) -> dict[str, Any]:
    try:
        context = _preflight(
            run_id,
            package_root=package_root,
            result_path=result_path or _result_path(run_id),
            results_root=results_root,
            interpreter=interpreter,
            allow_worker_changes=True,
            check_result_absent=False,
        )
    except (LVReviewError, LVExecutionPackageError) as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    worker_hash = ""
    worker_bytes = b""
    try:
        evidence, evidence_hash = _verify_preflight_evidence(context)
        context["preflight_evidence"] = evidence
        context["preflight_evidence_sha256"] = evidence_hash
        payload, worker_hash, worker_bytes = _safe_read_result(context["result_path"])
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
        if actual["forbidden_status"]:
            violations.append("forbidden Git status detected")
        for path_text in actual["changed_files"]:
            path = context["project_root"] / path_text
            if path.is_symlink() or (path.exists() and not path.is_file()):
                violations.append(f"unsafe changed path: {path_text}")
        if "tests/test_config.py" not in actual["changed_files"] and not (context["project_root"] / "tests/test_config.py").is_file():
            return {"status": "BLOCKED", "run_id": run_id, "reason": "tests/test_config.py is missing", "hard_stop": True}
        tests, test_error = _run_tests(context["project_root"], context["interpreter"])
        actual_after = _actual_changes(context["project_root"])
        if any(actual_after[field] != actual[field] for field in ("changed_files", "created_files", "modified_files", "deleted_files")):
            violations.append("Git change set changed during independent tests")
        actual = actual_after
        after = _capture_git_evidence(context["project_root"])
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
        verdict = "PASS" if not violations else "FAIL"
        report = _build_report(context, worker_hash, verdict, actual=actual, tests=tests, violations=violations, after=after)
    except (LVReviewError, LVExecutionPackageError) as exc:
        report = _build_report(context, worker_hash, "BLOCKED", blockers=[str(exc)], reasons=["strict intake or identity validation failed"])
        if not worker_bytes:
            return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    try:
        sealed = _seal_review(context, report, worker_hash, worker_bytes)
    except LVReviewError as exc:
        return {"status": "BLOCKED", "run_id": run_id, "reason": str(exc), "hard_stop": True}
    return {"status": report["verdict"], "hard_stop": True, **sealed}
