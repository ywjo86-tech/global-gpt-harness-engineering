from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.orchestrator.approval_inbox import build_approval_inbox, write_approval_inbox
from runtime.orchestrator.audit_log import append_audit_event, read_recent_audit_events
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.schemas import TaskSlice
from runtime.orchestrator.task_queue import build_task_queue, summarize_task_queue, write_task_queue
from runtime.orchestrator.worker_pool import summarize_worker_pool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run_root(project_root: Path, state_store: StateStore, run_id: str | None = None) -> Path:
    resolved_run_id = run_id or state_store.state.active_run_id
    if resolved_run_id:
        return project_root / "runtime" / "orchestrator_runs" / resolved_run_id
    runs_dir = project_root / "runtime" / "orchestrator_runs"
    if runs_dir.exists():
        candidates = [path for path in runs_dir.iterdir() if path.is_dir()]
        if candidates:
            return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return project_root / "runtime"


def _tail_lines(path: Path, limit: int = 50) -> list[str]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return lines[-limit:]


def _queue_payload(queue: list[Any]) -> list[dict[str, Any]]:
    return [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in queue]


def render_dashboard_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Jarvis Orchestration Panel",
        "",
        "## Current Project",
        f"- project: {snapshot.get('project_root', 'none')}",
        f"- run id: {snapshot.get('run_id', 'none')}",
        f"- current phase: {snapshot.get('current_phase', 'none')}",
        f"- next action: {snapshot.get('next_step', 'none')}",
        "",
        "## Status",
        f"- fan-out: {snapshot.get('fanout_status', 'none')}",
        f"- fan-in: {snapshot.get('fanin_status', 'none')}",
        f"- stage gate: {snapshot.get('stage_gate_decision', {}).get('decision', 'none') if isinstance(snapshot.get('stage_gate_decision'), dict) else snapshot.get('stage_gate_decision', 'none')}",
        f"- approvals required: {snapshot.get('approval_required', False)}",
        "",
        "## Active Workers",
    ]
    workers = snapshot.get("active_workers", [])
    if workers:
        for worker in workers:
            lines.append(
                f"- {worker.get('thread_id', 'unknown')}: {worker.get('assigned_agent', 'unknown')} | {worker.get('status', 'pending')}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Pending Approvals",
        ]
    )
    approvals = snapshot.get("pending_approvals", [])
    if approvals:
        for item in approvals:
            lines.append(
                f"- {item.get('thread_id', 'unknown')}: {item.get('assigned_agent', 'unknown')} | {item.get('approval_classification', 'unknown')} | {item.get('status', 'unknown')}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Stage Gate",
        ]
    )
    stage_gate = snapshot.get("stage_gate_result", {})
    if stage_gate:
        lines.append(f"- decision: {stage_gate.get('status', stage_gate.get('decision', 'none'))}")
        lines.append(f"- next step: {stage_gate.get('next_step', 'none')}")
    else:
        lines.append("- decision: none")
    lines.extend(
        [
            "",
            "## Recent Logs",
        ]
    )
    recent_logs = snapshot.get("recent_logs", [])
    if recent_logs:
        for line in recent_logs[-10:]:
            lines.append(f"- {line}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def read_dashboard_state(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state_store = StateStore(root)
    state = state_store.state
    run_root = _latest_run_root(root, state_store, run_id)
    run_manifest = _read_json(run_root / "run_manifest.json") or {}
    fanout_plan = _read_json(run_root / "fanout_plan.json") or []
    collection_report = _read_json(run_root / "fanin" / "collection_report.json") or {}
    fanin_report = _read_json(run_root / "fanin" / "fanin_report.json") or _read_json(run_root / "fanin" / "fanin_result.json") or {}
    stage_gate_result = _read_json(run_root / "gate" / "stage_gate_result.json") or _read_json(root / "runtime" / "stage_gate.json") or {}
    tasks = [item for item in state.active_threads] or list(fanout_plan)

    queue: list[Any] = []
    if tasks:
        task_slices = [TaskSlice(**item) if isinstance(item, dict) else item for item in tasks]
        queue = build_task_queue(state, task_slices, project_root=str(root))
    queue_payload = _queue_payload(queue)
    approval_inbox = build_approval_inbox(state, queue)
    approval_inbox_path = write_approval_inbox(run_root, approval_inbox)
    task_queue_path = write_task_queue(run_root, queue)
    worker_pool = summarize_worker_pool(queue).to_dict()
    task_summary = summarize_task_queue(queue)
    recent_logs = _tail_lines(root / "logs" / "app.log")
    recent_audit = read_recent_audit_events(run_root / "logs" / "audit.log") or []

    snapshot = {
        "project_root": str(root),
        "project_name": root.name,
        "run_id": run_manifest.get("run_id") or state.active_run_id or run_root.name,
        "run_root": str(run_root),
        "current_phase": state.current_phase,
        "next_step": state.next_step,
        "fanout_status": state.fanout_status,
        "fanin_status": state.fanin_status,
        "collection_status": state.collection_status,
        "stage_gate_decision": state.stage_gate_decision or stage_gate_result,
        "approval_required": state.approval_required,
        "active_workers": queue_payload,
        "pending_approvals": [item.to_dict() for item in approval_inbox],
        "task_queue": queue_payload,
        "task_queue_summary": task_summary,
        "worker_pool": worker_pool,
        "run_manifest": run_manifest,
        "fanout_plan": fanout_plan,
        "collection_report": collection_report,
        "fanin_report": fanin_report,
        "stage_gate_result": stage_gate_result,
        "recent_logs": recent_logs,
        "recent_audit_events": recent_audit,
        "approval_inbox_path": str(approval_inbox_path),
        "task_queue_path": str(task_queue_path),
        "last_updated": _utc_now(),
    }
    bridge_dir = root / "runtime" / "jarvis_bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    (bridge_dir / "dashboard_snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    (bridge_dir / "dashboard_snapshot.md").write_text(render_dashboard_markdown(snapshot), encoding="utf-8")
    append_audit_event(
        run_root / "logs" / "audit.log",
        "dashboard",
        "snapshot refreshed",
        run_id=snapshot["run_id"],
        current_phase=snapshot["current_phase"],
        approval_required=snapshot["approval_required"],
    )
    append_audit_event(
        bridge_dir / "audit.log",
        "dashboard",
        "snapshot refreshed",
        run_id=snapshot["run_id"],
        current_phase=snapshot["current_phase"],
        approval_required=snapshot["approval_required"],
    )
    return snapshot
