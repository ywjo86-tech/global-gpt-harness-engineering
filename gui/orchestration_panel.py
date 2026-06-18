"""Global Harness orchestration panel formatting helpers."""

from __future__ import annotations

from typing import Any


def _stringify(value: Any, fallback: str = "none") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def build_orchestration_lines(summary: dict[str, Any] | None) -> list[str]:
    data = dict(summary or {})
    connected = "CONNECTED" if data.get("connected") else "DISCONNECTED"
    stage_gate = data.get("stage_gate_result", {})
    stage_gate_value = stage_gate.get("status") if isinstance(stage_gate, dict) else data.get("stage_gate_decision", {})
    if isinstance(stage_gate_value, dict):
        stage_gate_value = stage_gate_value.get("decision", "none")
    active_workers = list(data.get("active_workers", []) or [])
    approvals = list(data.get("pending_approvals", []) or [])
    recent_logs = list(data.get("recent_logs", []) or [])
    lines = [
        f"Bridge: {connected}",
        f"Project: {_stringify(data.get('project_name') or data.get('project_root'))}",
        f"Run ID: {_stringify(data.get('run_id'))}",
        f"Current Phase: {_stringify(data.get('current_phase'))}",
        f"Next Step: {_stringify(data.get('next_step'))}",
        f"Fan-out: {_stringify(data.get('fanout_status'))} | Fan-in: {_stringify(data.get('fanin_status'))}",
        f"Collection: {_stringify(data.get('collection_status'))} | Stage Gate: {_stringify(stage_gate_value)}",
        f"Approvals Required: {'YES' if data.get('approval_required') else 'NO'} | Pending: {len(approvals)}",
        f"Active Workers: {len(active_workers)} | Recent Logs: {len(recent_logs)}",
        "",
    ]
    if active_workers:
        lines.append("Active Worker Snapshot")
        for worker in active_workers[:5]:
            if isinstance(worker, dict):
                lines.append(
                    f"- {worker.get('thread_id', 'unknown')} | {worker.get('assigned_agent', 'unknown')} | {worker.get('status', 'pending')}"
                )
    else:
        lines.append("Active Worker Snapshot")
        lines.append("- none")
    lines.extend(["", "Pending Approvals"])
    if approvals:
        for item in approvals[:5]:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('thread_id', 'unknown')} | {item.get('assigned_agent', 'unknown')} | {item.get('approval_classification', 'unknown')}"
                )
    else:
        lines.append("- none")
    lines.extend(["", "Recent Bridge Logs"])
    if recent_logs:
        for entry in recent_logs[-5:]:
            lines.append(f"- {_stringify(entry)}")
    else:
        lines.append("- none")
    return lines
