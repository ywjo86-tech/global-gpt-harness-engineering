"""Canonical registered-job resume adapter for OCPv2 state-changing directives.

This module is deliberately part of the Full Plan execution layer, not the transport
layer.  It may resume only an already-registered immutable Full Plan job.  It never
registers a job, selects an LV, constructs a WorkerRequest, selects a provider, or calls
a shell/tool backend directly.  Those authorities remain in the existing Full Plan,
Provider Router, Production Execution Gateway, and Full MCP path.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .contract_adapter import MAPPING_ROOT_ENV
from .harness_state_root import job_state_root
from .production_full_plan_entry import (
    build_gate_executor,
    canonical_job_path,
    load_registered_job,
    preflight_job,
)
from .production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError, TERMINAL_STATES
from .production_run_authority import executor_runtime_identity


class CanonicalRemoteResumeError(ValueError):
    pass


def _safe_component(value: object, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 160 or "/" in text or "\\" in text or ".." in text:
        raise CanonicalRemoteResumeError(f"unsafe {label}")
    return text


def _project_head(job: Mapping[str, Any]) -> str:
    project = Path(str(job.get("project_root") or "")).expanduser().resolve()
    completed = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise CanonicalRemoteResumeError("PROJECT_HEAD_UNAVAILABLE")
    return completed.stdout.strip()


def _runtime_release(job: Mapping[str, Any]) -> str:
    runtime_root = str(job.get("runtime_code_root") or job.get("harness_root") or "")
    return str(executor_runtime_identity(runtime_root).get("runtime_source_sha256") or "")


def _active_queue_item(state: Mapping[str, Any]) -> Mapping[str, Any]:
    active = [
        item for item in state.get("queue", [])
        if isinstance(item, Mapping) and item.get("status") not in {"COMPLETED", "BLOCKED", "CANCELLED"}
    ]
    if len(active) != 1:
        raise CanonicalRemoteResumeError("ACTIVE_QUEUE_BINDING_MISMATCH")
    return active[0]


def execute_registered_full_plan_continuation(
    *,
    harness_state_root: str | Path,
    project_id: str,
    run_id: str,
    gate_id: str,
    task_id: str,
    task_execution_id: str,
    expected_state_sha256: str,
    expected_owner_epoch: int,
    expected_source_head: str,
    expected_runtime_release_digest: str,
    current_project_head: Callable[[Mapping[str, Any]], str] = _project_head,
    current_runtime_release_digest: Callable[[Mapping[str, Any]], str] = _runtime_release,
) -> dict[str, Any]:
    """Resume one exact registered Full Plan continuation generation.

    Every externally observed binding is checked before the single owner-claim write.
    The owner claim and Full Plan resume then occur while the existing Full Plan run lock
    remains held, closing the race between CAS validation and dispatch.
    """
    project = _safe_component(project_id, "project ID")
    run = _safe_component(run_id, "run ID")
    gate = _safe_component(gate_id, "Gate ID")
    task = _safe_component(task_id, "task ID")
    task_execution = _safe_component(task_execution_id, "task execution ID")
    state_sha = str(expected_state_sha256 or "")
    if len(state_sha) != 64 or any(ch not in "0123456789abcdef" for ch in state_sha):
        raise CanonicalRemoteResumeError("invalid expected Full Plan state SHA")
    try:
        owner_epoch = int(expected_owner_epoch)
    except (TypeError, ValueError) as exc:
        raise CanonicalRemoteResumeError("invalid expected owner epoch") from exc
    if isinstance(expected_owner_epoch, bool) or owner_epoch <= 0:
        raise CanonicalRemoteResumeError("invalid expected owner epoch")

    root = Path(harness_state_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise CanonicalRemoteResumeError("HARNESS_STATE_ROOT_INVALID")
    path = root / "_workspace" / "production-full-plan-jobs" / project / f"{run}.job.json"
    if path.is_symlink() or not path.is_file():
        raise CanonicalRemoteResumeError("REGISTERED_FULL_PLAN_JOB_REQUIRED")

    job = load_registered_job(path)
    if str(job.get("project_id") or "") != project or str(job.get("run_id") or "") != run:
        raise CanonicalRemoteResumeError("REGISTERED_JOB_BINDING_MISMATCH")
    if job_state_root(job) != root.resolve():
        raise CanonicalRemoteResumeError("REGISTERED_JOB_STATE_ROOT_MISMATCH")
    if canonical_job_path(job).resolve() != path.resolve():
        raise CanonicalRemoteResumeError("REGISTERED_JOB_CANONICAL_PATH_MISMATCH")
    gate_ids = [str(item.get("gate_id") or "") for item in job.get("gates", []) if isinstance(item, Mapping)]
    if gate not in gate_ids:
        raise CanonicalRemoteResumeError("GATE_BINDING_MISMATCH")

    if expected_source_head and str(current_project_head(job)) != str(expected_source_head):
        raise ProductionFullPlanError("STALE_DIRECTIVE: source head mismatch")
    if (
        expected_runtime_release_digest
        and str(current_runtime_release_digest(job)) != str(expected_runtime_release_digest)
    ):
        raise ProductionFullPlanError("STALE_DIRECTIVE: runtime release mismatch")

    supervisor = DurableFullPlanSupervisor(
        root,
        project_id=project,
        run_id=run,
        gates=gate_ids,
        authority_core_sha256=str(job.get("authority_core_sha256") or ""),
        **dict(job.get("policy") or {}),
    )
    previous_mapping_root = os.environ.get(MAPPING_ROOT_ENV)
    mapping_root = job.get("mapping_root")
    handle = supervisor._acquire_run_lock()
    try:
        state, _ = supervisor.load()
        if str(state.get("state_sha256") or "") != state_sha:
            raise ProductionFullPlanError("STALE_DIRECTIVE: Full Plan state mismatch")
        if state.get("current_gate") != gate or state.get("state") in TERMINAL_STATES:
            raise CanonicalRemoteResumeError("GATE_BINDING_MISMATCH")
        item = _active_queue_item(state)
        if task != gate or str(item.get("gate_id") or "") != gate or str(item.get("gate_run_id") or "") != task_execution:
            raise CanonicalRemoteResumeError("TASK_BINDING_MISMATCH")

        prior = state.get("continuation_owner")
        prior_epoch = int(prior.get("epoch", 0)) if isinstance(prior, Mapping) else 0
        next_epoch = max(prior_epoch, int(state.get("epoch", 0))) + 1
        if next_epoch != owner_epoch:
            raise ProductionFullPlanError("STALE_DIRECTIVE: continuation owner epoch mismatch")

        if expected_source_head and str(current_project_head(job)) != str(expected_source_head):
            raise ProductionFullPlanError("STALE_DIRECTIVE: source head mismatch")
        if (
            expected_runtime_release_digest
            and str(current_runtime_release_digest(job)) != str(expected_runtime_release_digest)
        ):
            raise ProductionFullPlanError("STALE_DIRECTIVE: runtime release mismatch")

        state["continuation_owner"] = {
            "gate_id": gate,
            "epoch": next_epoch,
            "claimed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        supervisor._persist(
            state,
            {"event": "CONTINUATION_OWNER_CLAIMED", "gate_id": gate, "owner_epoch": next_epoch, "source": "OCPV2"},
        )

        if mapping_root is not None:
            os.environ[MAPPING_ROOT_ENV] = str(mapping_root)
        full = supervisor._run_locked(
            build_gate_executor(job),
            preflight=lambda _: preflight_job(job),
        )
        result_state = full.state
        return {
            "result_class": "CANONICAL_FULL_PLAN_RESULT",
            "status": full.status,
            "state_sha256": str(result_state.get("state_sha256") or ""),
            "current_gate": str(result_state.get("current_gate") or ""),
            "executed_gates": list(full.executed_gates),
            "recovered_on_startup": bool(full.recovered_on_startup),
        }
    finally:
        if previous_mapping_root is None:
            os.environ.pop(MAPPING_ROOT_ENV, None)
        else:
            os.environ[MAPPING_ROOT_ENV] = previous_mapping_root
        supervisor._release_run_lock(handle)
