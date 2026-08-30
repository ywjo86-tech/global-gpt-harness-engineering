"""Registry-selected, fail-closed production implementation worker."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .lv_execution_package import canonical_json_bytes
from .schemas import WorkerRequest


class ProductionWorkerError(ValueError):
    pass


EXECUTOR_ID = "codex-cli-production"
EXECUTOR_VERSION = "1"
_SECRET = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|token)\s*[:=]\s*\S+")


def _redact(value: str) -> str:
    return _SECRET.sub(lambda match: match.group(1) + "=[REDACTED]", value)


def production_executor_manifest() -> dict[str, Any]:
    return {
        "asset_id": EXECUTOR_ID,
        "asset_type": "worker_executor",
        "version": EXECUTOR_VERSION,
        "production": True,
        "test_double": False,
        "capabilities": ["implement", "test", "checkpoint"],
        "permissions": ["owned-files-write", "project-tests", "local-git-commit"],
        "network_policy": "NO_TASK_NETWORK",
        "secret_policy": "NO_SECRET_ACCESS_OR_OUTPUT",
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _safe_scope(values: object) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ProductionWorkerError("production worker owned scope is missing")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ProductionWorkerError("production worker owned scope is unsafe")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ProductionWorkerError("production worker owned scope is unsafe")
        result.append(value)
    return result


def _command(root: Path, argv: list[str], timeout: int = 900) -> dict[str, Any]:
    try:
        result = subprocess.run(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, timeout=timeout)
        stdout = bytes(result.stdout or b""); stderr = bytes(result.stderr or b"")
        return {"command": argv, "exit_code": result.returncode, "timeout": False,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest()}
    except subprocess.TimeoutExpired as exc:
        return {"command": argv, "exit_code": 124, "timeout": True,
                "stdout_sha256": hashlib.sha256(bytes(exc.stdout or b"")).hexdigest(),
                "stderr_sha256": hashlib.sha256(bytes(exc.stderr or b"")).hexdigest()}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_managed_child(argv: list[str], *, root: Path, prompt: bytes, timeout: int,
                       cancel_path: Path, grace_period: float = 2.0) -> tuple[bytes, bytes, dict[str, Any]]:
    """Run one child process group and leave deterministic termination evidence."""
    started_at = _utc(); started = time.monotonic()
    process = subprocess.Popen(argv, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    termination = "EXITED"; requested_signal = None
    try:
        assert process.stdin is not None
        process.stdin.write(prompt); process.stdin.close(); process.stdin = None
        while process.poll() is None:
            cancelled = cancel_path.is_file() and not cancel_path.is_symlink()
            timed_out = time.monotonic() - started >= timeout
            if cancelled or timed_out:
                termination = "CANCELLED" if cancelled else "TIMED_OUT"
                requested_signal = "SIGTERM"
                os.killpg(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + grace_period
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if process.poll() is None:
                    requested_signal = "SIGKILL"
                    os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(0.02)
        stdout, stderr = process.communicate()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL); process.wait()
    return bytes(stdout or b""), bytes(stderr or b""), {
        "schema_version":"orchestration.production-worker-process.v1", "pid":process.pid,
        "process_group_id":process.pid, "started_at":started_at, "ended_at":_utc(),
        "termination":termination, "requested_signal":requested_signal,
        "exit_code":process.returncode if process.returncode is not None and process.returncode >= 0 else None,
        "signal":-process.returncode if process.returncode is not None and process.returncode < 0 else None,
        "stdout_sha256":hashlib.sha256(bytes(stdout or b"")).hexdigest(),
        "stderr_sha256":hashlib.sha256(bytes(stderr or b"")).hexdigest(), "hard_stop":True,
    }


def _prompt(request: WorkerRequest, baseline: str, owned: list[str]) -> str:
    criteria = "\n".join(f"- {item}" for item in request.task.validation_criteria)
    scope = "\n".join(f"- {item}" for item in owned)
    return f"""Execute this sealed production LV implementation in the current repository.
Project/Gate/LV/run/attempt: {request.contract_summary.get('project_id')} / {request.contract_summary.get('gate_id')} / {request.contract_summary.get('lv_id')} / {request.extra_context.get('run_id')} / {request.extra_context.get('attempt')}
Baseline HEAD: {baseline}
Plan SHA-256: {request.contract_summary.get('canonical_plan_sha256')}
Task: {request.task.input}
Owned files (do not modify anything else):
{scope}
Completion criteria:
{criteria}
Use the existing project interpreter/environment. Do not use network, packages, secrets, system changes, push, reset, rebase, clean, stash, or the next Gate. Implement and test the task, run focused and full tests plus compile/import and git diff checks, then create one local checkpoint commit containing only owned files. Finish with a clean index and worktree. Do not manufacture orchestration artifacts; the controller collects evidence independently.
"""


def execute_production_worker(request: WorkerRequest, *,
                              executor: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
                              timeout: int = 1800) -> dict[str, Any]:
    """Run the registered Codex executor and independently collect product evidence."""
    root = Path(request.project_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or root.resolve() != root:
        raise ProductionWorkerError("production worker project root is unsafe")
    if request.extra_context.get("execution_mode") != "production":
        raise ProductionWorkerError("production executor requires production mode")
    owned = _safe_scope(request.task.editable_scope)
    baseline = str(request.extra_context.get("source_snapshot", {}).get("source_head") or request.state_snapshot.get("head", ""))
    baseline_status = _git(root, "status", "--porcelain=v1", "-uall").stdout
    current_before = _git(root, "rev-parse", "HEAD").stdout.strip()
    adoption = current_before != baseline
    if adoption:
        ancestor = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", baseline, current_before], check=False)
        if ancestor.returncode != 0:
            raise ProductionWorkerError("production worker baseline is dirty or drifted")
        adopted_changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", current_before).stdout.splitlines()
        if not adopted_changed or any(path not in owned for path in adopted_changed):
            raise ProductionWorkerError("production worker adoption scope violation")
    prompt = _prompt(request, baseline, owned)
    output = Path(request.task.output_dir); output.mkdir(parents=True, exist_ok=True)
    last = output / "executor.last-message.txt"
    argv = ["codex", "--sandbox", "workspace-write", "--ask-for-approval", "never", "--cd", str(root),
            "exec", "--ephemeral", "--output-last-message", str(last), "-"]
    pending_paths = [line[3:] for line in baseline_status.splitlines() if len(line) > 3]
    if pending_paths and any(not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in owned) for path in pending_paths):
        raise ProductionWorkerError("production worker changed files outside owned scope")
    cancel_path = output / "cancel.request"
    if adoption:
        stdout = stderr = b""
        worker_exit = 0; timed_out = False
        process_evidence = {"schema_version":"orchestration.production-worker-process.v1","pid":None,"process_group_id":None,
                            "started_at":None,"ended_at":None,"termination":"ADOPTED_CHECKPOINT","requested_signal":None,
                            "exit_code":0,"signal":None,"stdout_sha256":hashlib.sha256(b"").hexdigest(),
                            "stderr_sha256":hashlib.sha256(b"").hexdigest(),"hard_stop":True}
    elif pending_paths:
        stdout = stderr = b""
        worker_exit = 0; timed_out = False
        process_evidence = {"schema_version":"orchestration.production-worker-process.v1","pid":None,"process_group_id":None,
                            "started_at":None,"ended_at":None,"termination":"RESUMED_PENDING_CHECKPOINT","requested_signal":None,
                            "exit_code":0,"signal":None,"stdout_sha256":hashlib.sha256(b"").hexdigest(),
                            "stderr_sha256":hashlib.sha256(b"").hexdigest(),"hard_stop":True}
    elif executor is None:
        stdout, stderr, process_evidence = _run_managed_child(argv, root=root, prompt=prompt.encode(), timeout=timeout,
                                                               cancel_path=cancel_path)
        worker_exit = int(process_evidence["exit_code"] if process_evidence["exit_code"] is not None else 128 + int(process_evidence["signal"] or 0))
        timed_out = process_evidence["termination"] == "TIMED_OUT"
    else:
        completed = executor(argv, input=prompt.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False, timeout=timeout)
        worker_exit = int(completed.returncode); timed_out = False
        stdout = bytes(completed.stdout or b""); stderr = bytes(completed.stderr or b"")
        process_evidence = {"schema_version":"orchestration.production-worker-process.v1","pid":None,"process_group_id":None,
                            "started_at":None,"ended_at":None,"termination":"EXITED","requested_signal":None,
                            "exit_code":worker_exit,"signal":None,"stdout_sha256":hashlib.sha256(stdout).hexdigest(),
                            "stderr_sha256":hashlib.sha256(stderr).hexdigest(),"hard_stop":True}
    process_path = output / "executor.process.json"
    process_path.write_bytes(canonical_json_bytes(process_evidence))
    if _SECRET.search((stdout + b"\n" + stderr).decode("utf-8", "replace")):
        raise ProductionWorkerError("production executor emitted secret-like output")
    if worker_exit != 0 or timed_out or process_evidence["termination"] not in {"EXITED", "RESUMED_PENDING_CHECKPOINT", "ADOPTED_CHECKPOINT"}:
        raise ProductionWorkerError("production executor failed or timed out")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    if head == baseline:
        lines = _git(root, "status", "--porcelain=v1", "-uall").stdout.splitlines()
        changed = [line[3:] for line in lines if len(line) > 3]
    else:
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).stdout.splitlines()
    if not changed:
        diagnostic = _redact(last.read_text(encoding="utf-8", errors="replace")[:500]) if last.is_file() else "no final message"
        raise ProductionWorkerError(f"production executor produced no product changes: {diagnostic}")
    outside = [path for path in changed if not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in owned)]
    if outside:
        raise ProductionWorkerError(f"production executor changed files outside owned scope: {outside}")
    tests = [path for path in owned if path.startswith("tests/") and path.endswith(".py")]
    if not tests:
        raise ProductionWorkerError("production worker focused test scope is missing")
    python = root / ".venv" / "bin" / "python"; pytest = root / ".venv" / "bin" / "pytest"
    if not python.is_file() or not pytest.is_file():
        raise ProductionWorkerError("registered project interpreter is unavailable")
    commands = {
        "worker": {"command": argv, "exit_code": worker_exit, "timeout": timed_out,
                   "stdout_sha256": hashlib.sha256(stdout).hexdigest(), "stderr_sha256": hashlib.sha256(stderr).hexdigest()},
        "focused_test": _command(root, [str(python), "-m", "pytest", "-q", *tests]),
        "full_regression": _command(root, [str(python), "-m", "pytest", "-q"]),
        "compile_import": _command(root, [str(python), "-m", "compileall", "-q", *owned]),
        "git_diff_check": _command(root, ["git", "diff", "--check"] if head == baseline else ["git", "diff", "--check", f"{baseline}..{head}"]),
    }
    if any(item["exit_code"] != 0 or item.get("timeout") for item in commands.values()):
        raise ProductionWorkerError("production worker independent command verification failed")
    if head == baseline:
        added = _git(root, "add", "--", *changed)
        if added.returncode != 0:
            raise ProductionWorkerError("production checkpoint staging failed")
        committed = _git(root, "commit", "-m", f"feat({request.contract_summary['lv_id']}): production checkpoint")
        if committed.returncode != 0:
            raise ProductionWorkerError("production checkpoint commit failed")
        head = _git(root, "rev-parse", "HEAD").stdout.strip()
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).stdout.splitlines()
    status = _git(root, "status", "--porcelain=v1").stdout
    if status:
        raise ProductionWorkerError("production worker did not leave a clean repository")
    tree = _git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    baseline_tree = _git(root, "rev-parse", f"{baseline}^{{tree}}").stdout.strip()
    ids = {"project_id": request.contract_summary["project_id"], "gate_id": request.contract_summary["gate_id"],
           "lv_id": request.contract_summary["lv_id"], "run_id": request.extra_context["run_id"],
           "approval_event_id": request.extra_context["approval_event_id"],
           "plan_sha256": request.contract_summary["canonical_plan_sha256"]}
    evidence = {**ids, "schema_version":"orchestration.product-completion-evidence.v1",
        "status":"completed", "tests":list(request.task.validation_criteria),
        "attempt":int(request.extra_context["attempt"]), "completion_mode":"CODE_CHANGE", "owned_files":owned,
        "changed_files":changed, "baseline_head":baseline, "baseline_tree":baseline_tree,
        "current_head":head, "current_tree":tree, "checkpoint_commit":head, "commands":commands,
        "staged_changes":False, "unstaged_changes":False, "review_verdict":"PASS",
        "executor":{"identity":EXECUTOR_ID,"version":EXECUTOR_VERSION},
        "package_sha256":request.extra_context["package_manifest_sha256"],
        "artifact_sha_chain":{"request":hashlib.sha256(canonical_json_bytes(request.to_dict())).hexdigest(),
                              "executor_output":hashlib.sha256(stdout+b"\0"+stderr).hexdigest(),
                              "process_evidence":hashlib.sha256(process_path.read_bytes()).hexdigest()}, "hard_stop":True}
    evidence["evidence_sha256"] = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
    return evidence
