"""Durable receipt tracking for GPT-operated approved implementation plans.

This module has no effect, provider, approval, completion, recovery, or notification
authority. It binds already-approved plan/spec evidence and observes create-once
operator task receipts so DurableFullPlanSupervisor can track progress.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .durable_io import atomic_write_json
from .production_run_authority import executor_runtime_identity

EXECUTOR_KIND = "GPT_OPERATOR_PLAN"
RECEIPT_SCHEMA = "orchestration.operator-plan-receipt.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40_64 = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")


class OperatorPlanExecutionError(ValueError):
    pass

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(str(value or "")):
        raise OperatorPlanExecutionError(f"unsafe {label}")
    return str(value)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=20,
    )
    if completed.returncode != 0:
        raise OperatorPlanExecutionError("Git verification failed")
    return completed.stdout.strip()


def _committed_regular_file(root: Path, path: str | Path, label: str) -> Path:
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    absolute = source.absolute()
    if absolute.is_symlink() or not absolute.is_file():
        raise OperatorPlanExecutionError(f"{label} must be a regular committed file")
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError as exc:
        raise OperatorPlanExecutionError(f"{label} must be a regular committed file") from exc
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if tracked.returncode != 0:
        raise OperatorPlanExecutionError(f"{label} must be a regular committed file")
    return absolute

def build_operator_plan_job(
    *, project_root: str | Path, harness_root: str | Path, runtime_code_root: str | Path,
    project_id: str, run_id: str, task_ids: Sequence[str],
    approved_plan_path: str | Path, approved_spec_path: str | Path,
    approval_ref: str,
) -> dict[str, Any]:
    project = Path(project_root).resolve()
    harness = Path(harness_root).resolve()
    runtime = Path(runtime_code_root).resolve()
    if not project.is_dir() or project.is_symlink() or not harness.is_dir() or harness.is_symlink():
        raise OperatorPlanExecutionError("project/harness root is invalid")
    if not runtime.is_dir():
        raise OperatorPlanExecutionError("runtime code root is invalid")
    plan = _committed_regular_file(project, approved_plan_path, "approved plan")
    spec = _committed_regular_file(project, approved_spec_path, "approved spec")
    tasks = tuple(_safe_id(value, "Task ID") for value in task_ids)
    if not tasks or len(set(tasks)) != len(tasks):
        raise OperatorPlanExecutionError("operator plan Task IDs are empty or duplicated")
    if not str(approval_ref or "").strip():
        raise OperatorPlanExecutionError("approval reference is required")
    branch = _git(project, "branch", "--show-current")
    head = _git(project, "rev-parse", "HEAD")
    common = _git(project, "rev-parse", "--git-common-dir")
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (project / common_path).resolve()
    plan_sha = _sha256_file(plan)
    spec_sha = _sha256_file(spec)
    gates = [{
        "gate_id": task,
        "approval_evidence": str(spec),
        "requirements_sha256": plan_sha,
        "branch": branch,
        "head": head,
        "full_plan_opt_in": True,
        "project_final_validation": True,
    } for task in tasks]
    job: dict[str, Any] = {
        "schema_version": "orchestration.production-full-plan-job.v1",
        "executor_kind": EXECUTOR_KIND,
        "project_root": str(project), "harness_root": str(harness),
        "runtime_code_root": str(runtime), "project_id": _safe_id(project_id, "project ID"),
        "run_id": _safe_id(run_id, "run ID"), "git_common_dir": str(common_path),
        "expected_branch": branch, "approved_plan_path": str(plan),
        "approved_plan_sha256": plan_sha, "approved_spec_path": str(spec),
        "approved_spec_sha256": spec_sha, "approval_ref": str(approval_ref),
        "gates": gates, "required_executables": ["git"],
        "executor_runtime_identity": executor_runtime_identity(runtime),
        "policy": {"retry_budget": 0, "gate_timeout_seconds": 3600,
                   "heartbeat_seconds": 5, "lease_seconds": 20,
                   "stall_alert_seconds": 300},
    }
    validate_operator_plan_job(job)
    return job

def validate_operator_plan_job(job: Mapping[str, Any]) -> None:
    if job.get("executor_kind") != EXECUTOR_KIND:
        raise OperatorPlanExecutionError("operator plan executor kind mismatch")
    project = Path(str(job.get("project_root") or "")).resolve()
    runtime = Path(str(job.get("runtime_code_root") or "")).resolve()
    if not project.is_dir() or project.is_symlink():
        raise OperatorPlanExecutionError("project root is invalid")
    if not runtime.is_dir():
        raise OperatorPlanExecutionError("runtime code root is invalid")
    plan = _committed_regular_file(project, str(job.get("approved_plan_path") or ""), "approved plan")
    spec = _committed_regular_file(project, str(job.get("approved_spec_path") or ""), "approved spec")
    if not _SHA256.fullmatch(str(job.get("approved_plan_sha256") or "")) or _sha256_file(plan) != job.get("approved_plan_sha256"):
        raise OperatorPlanExecutionError("approved plan digest mismatch")
    if not _SHA256.fullmatch(str(job.get("approved_spec_sha256") or "")) or _sha256_file(spec) != job.get("approved_spec_sha256"):
        raise OperatorPlanExecutionError("approved spec digest mismatch")
    branch = _git(project, "branch", "--show-current")
    if branch != str(job.get("expected_branch") or ""):
        raise OperatorPlanExecutionError("operator plan branch mismatch")
    gates = job.get("gates")
    if not isinstance(gates, list) or not gates:
        raise OperatorPlanExecutionError("operator plan Task list is empty")
    ids = [str(item.get("gate_id") or "") for item in gates if isinstance(item, Mapping)]
    if len(ids) != len(gates) or any(not _SAFE_ID.fullmatch(item) for item in ids) or len(set(ids)) != len(ids):
        raise OperatorPlanExecutionError("operator plan Task IDs are empty or duplicated")
    if not str(job.get("approval_ref") or "").strip():
        raise OperatorPlanExecutionError("approval reference is required")


class OperatorPlanReceiptStore:
    def __init__(self, harness_root: str | Path, *, project_id: str, run_id: str) -> None:
        self.root = Path(harness_root).resolve()
        self.project_id = _safe_id(project_id, "project ID")
        self.run_id = _safe_id(run_id, "run ID")
        self.base = self.root / "_workspace" / "operator-plan-receipts" / self.project_id / self.run_id

    def _path(self, gate_id: str) -> Path:
        return self.base / f"{_safe_id(gate_id, 'Task ID')}.json"

    def load(self, gate_id: str) -> dict[str, Any] | None:
        path = self._path(gate_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise OperatorPlanExecutionError("operator plan receipt is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorPlanExecutionError("operator plan receipt is malformed") from exc
        if not isinstance(value, dict) or value.get("schema_version") != RECEIPT_SCHEMA:
            raise OperatorPlanExecutionError("operator plan receipt schema mismatch")
        expected = value.get("receipt_sha256")
        unsigned = {k: v for k, v in value.items() if k != "receipt_sha256"}
        if expected != _digest(unsigned):
            raise OperatorPlanExecutionError("operator plan receipt digest mismatch")
        return value

    def create_pass_receipt(
        self, *, gate_id: str, plan_sha256: str, spec_sha256: str,
        branch: str, source_head: str, tests: Sequence[str],
    ) -> dict[str, Any]:
        if not _SHA256.fullmatch(str(plan_sha256)) or not _SHA256.fullmatch(str(spec_sha256)):
            raise OperatorPlanExecutionError("operator plan receipt binding digest is invalid")
        if not _SHA40_64.fullmatch(str(source_head)):
            raise OperatorPlanExecutionError("operator plan receipt source head is invalid")
        if not str(branch or "").strip():
            raise OperatorPlanExecutionError("operator plan receipt branch is invalid")
        normalized_tests = tuple(str(item).strip() for item in tests if str(item).strip())
        if not normalized_tests:
            raise OperatorPlanExecutionError("operator plan receipt requires verification evidence")
        gate = _safe_id(gate_id, "Task ID")
        binding = {
            "schema_version": RECEIPT_SCHEMA,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "gate_id": gate,
            "plan_sha256": str(plan_sha256),
            "spec_sha256": str(spec_sha256),
            "branch": str(branch),
            "source_head": str(source_head),
            "tests": list(normalized_tests),
            "status": "PASS",
        }
        existing = self.load(gate)
        if existing is not None:
            comparable = {k: v for k, v in existing.items() if k not in {"created_at", "receipt_sha256"}}
            if comparable == binding:
                return existing
            raise OperatorPlanExecutionError("conflicting receipt already exists")
        payload = {**binding, "created_at": _now()}
        payload["receipt_sha256"] = _digest(payload)
        path = self._path(gate)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise OperatorPlanExecutionError("operator plan receipt root is unsafe")
        atomic_write_json(path, payload)
        return payload


def _validate_receipt_for_job(job: Mapping[str, Any], gate_id: str, receipt: Mapping[str, Any]) -> None:
    expected = {
        "project_id": str(job["project_id"]), "run_id": str(job["run_id"]),
        "gate_id": gate_id, "plan_sha256": str(job["approved_plan_sha256"]),
        "spec_sha256": str(job["approved_spec_sha256"]), "branch": str(job["expected_branch"]),
        "status": "PASS",
    }
    if any(str(receipt.get(key) or "") != value for key, value in expected.items()):
        raise OperatorPlanExecutionError("operator plan receipt binding mismatch")
    if not _SHA40_64.fullmatch(str(receipt.get("source_head") or "")):
        raise OperatorPlanExecutionError("operator plan receipt source head is invalid")
    tests = receipt.get("tests")
    if not isinstance(tests, list) or not tests or any(not isinstance(item, str) or not item.strip() for item in tests):
        raise OperatorPlanExecutionError("operator plan receipt verification evidence is invalid")


def build_operator_plan_executor(
    job: Mapping[str, Any], *, receipt_store: OperatorPlanReceiptStore | None = None,
):
    validate_operator_plan_job(job)
    store = receipt_store or OperatorPlanReceiptStore(
        str(job["harness_root"]), project_id=str(job["project_id"]), run_id=str(job["run_id"]),
    )

    def execute(gate_id: str, gate_run_id: str, resume: bool) -> Mapping[str, Any]:
        del gate_run_id, resume
        known = [str(item["gate_id"]) for item in job["gates"]]
        if gate_id not in known:
            raise OperatorPlanExecutionError("Task is outside approved operator plan")
        receipt = store.load(gate_id)
        if receipt is None:
            return {"status": "WAITING_RESOURCE", "reason": "OPERATOR_TASK_RECEIPT_PENDING"}
        _validate_receipt_for_job(job, gate_id, receipt)
        return {
            "status": "GATE_EXIT",
            "receipt_sha256": str(receipt["receipt_sha256"]),
            "next": {"action": "SYSTEM_TRANSITION", "automatic": True},
        }
    return execute


def _successor_spec_binding(job: Mapping[str, Any], resume_gate: str) -> dict[str, Any]:
    from .production_run_authority import seal_authority_core
    sealed = seal_authority_core(job)
    validate_operator_plan_job(sealed)
    tasks = [str(item["gate_id"]) for item in sealed["gates"]]
    gate = _safe_id(resume_gate, "resume Gate")
    if gate not in tasks:
        raise OperatorPlanExecutionError("successor resume Gate is outside approved operator plan")
    return {
        "schema_version": "orchestration.runtime-migration-successor-spec.v1",
        "project_id": str(sealed["project_id"]), "run_id": str(sealed["run_id"]),
        "approved_plan_sha256": str(sealed["approved_plan_sha256"]),
        "approved_spec_sha256": str(sealed["approved_spec_sha256"]),
        "authority_core_sha256": str(sealed["authority_core_sha256"]),
        "resume_gate": gate, "task_ids": tasks,
    }

def seal_successor_operator_job_spec(job: Mapping[str, Any], *, resume_gate: str) -> dict[str, Any]:
    binding = _successor_spec_binding(job, resume_gate)
    return {**binding, "successor_job_spec_sha256": _digest(binding)}

def verify_registered_successor(job_path: str | Path, sealed_spec: Mapping[str, Any]) -> dict[str, Any]:
    from .production_full_plan_entry import load_registered_job
    from .production_full_plan_runner import DurableFullPlanSupervisor, TERMINAL_STATES
    if not isinstance(sealed_spec, Mapping):
        raise OperatorPlanExecutionError("successor specification is malformed")
    required = {"schema_version","project_id","run_id","approved_plan_sha256","approved_spec_sha256","authority_core_sha256","resume_gate","task_ids","successor_job_spec_sha256"}
    if set(sealed_spec) != required:
        raise OperatorPlanExecutionError("successor specification fields mismatch")
    unsigned = {k: sealed_spec[k] for k in required if k != "successor_job_spec_sha256"}
    if sealed_spec.get("successor_job_spec_sha256") != _digest(unsigned):
        raise OperatorPlanExecutionError("successor specification digest mismatch")
    job = load_registered_job(job_path); expected = seal_successor_operator_job_spec(job, resume_gate=str(sealed_spec["resume_gate"]))
    if expected != dict(sealed_spec):
        raise OperatorPlanExecutionError("registered successor binding mismatch")
    gates = [str(item["gate_id"]) for item in job["gates"]]
    supervisor = DurableFullPlanSupervisor(str(job["harness_root"]), project_id=str(job["project_id"]), run_id=str(job["run_id"]), gates=gates, authority_core_sha256=str(job["authority_core_sha256"]), **dict(job.get("policy") or {}))
    if not supervisor.state_path.is_file() or supervisor.state_path.is_symlink():
        raise OperatorPlanExecutionError("successor durable state is not registered")
    state, _ = supervisor.load()
    if state.get("current_gate") != sealed_spec["resume_gate"] or state.get("state") in TERMINAL_STATES:
        raise OperatorPlanExecutionError("successor durable state is not eligible")
    return {"project_id": str(job["project_id"]), "successor_run_id": str(job["run_id"]), "resume_gate": str(sealed_spec["resume_gate"]), "successor_state_sha256": str(state["state_sha256"]), "successor_job_spec_sha256": str(sealed_spec["successor_job_spec_sha256"]), "authority_core_sha256": str(job["authority_core_sha256"])}


def resume_operator_plan_after_receipt(job_path: str | Path, gate_id: str) -> dict[str, Any]:
    """Explicitly reopen WAITING_RESOURCE after a bound PASS receipt exists."""
    from .production_full_plan_entry import canonical_job_path, load_job, load_registered_job
    from .production_full_plan_runner import DurableFullPlanSupervisor

    requested = load_job(job_path)
    canonical = canonical_job_path(requested)
    if canonical.is_symlink() or not canonical.is_file():
        raise OperatorPlanExecutionError("durable operator plan job is not registered")
    job = load_registered_job(canonical)
    validate_operator_plan_job(job)
    if str(job.get("executor_kind")) != EXECUTOR_KIND:
        raise OperatorPlanExecutionError("job is not a GPT operator plan")
    known = [str(item["gate_id"]) for item in job["gates"]]
    if gate_id not in known:
        raise OperatorPlanExecutionError("Task is outside approved operator plan")
    store = OperatorPlanReceiptStore(
        str(job["harness_root"]), project_id=str(job["project_id"]), run_id=str(job["run_id"]),
    )
    receipt = store.load(gate_id)
    if receipt is None:
        raise OperatorPlanExecutionError("operator task PASS receipt is missing")
    _validate_receipt_for_job(job, gate_id, receipt)
    supervisor = DurableFullPlanSupervisor(
        str(job["harness_root"]), project_id=str(job["project_id"]), run_id=str(job["run_id"]),
        gates=known, authority_core_sha256=str(job.get("authority_core_sha256") or ""),
        **dict(job.get("policy") or {}),
    )
    state, _ = supervisor.load()
    if state.get("state") != "WAITING_RESOURCE" or state.get("current_gate") != gate_id:
        raise OperatorPlanExecutionError("operator plan is not waiting for this Task receipt")
    return supervisor.resume_wait("WAITING_RESOURCE")
