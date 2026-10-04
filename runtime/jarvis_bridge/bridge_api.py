from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .approval_handler import read_pending_approvals, submit_approval as _submit_approval
from .command_dispatcher import dispatch_command
from .event_stream import read_recent_events
from .state_reader import read_dashboard_state, read_dashboard_state_projection_only, render_dashboard_markdown


def _console_atom(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "_", text).strip("_")
    return (normalized or fallback)[:200]


def refresh_dashboard_snapshot(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    return read_dashboard_state(project_root, run_id=run_id)


def refresh_operations_projection(project_root: str | Path, run_id: str | None = None) -> dict[str, object]:
    from runtime.orchestrator.operations_diagnostic_projection import build_diagnostic_health_projection
    from runtime.orchestrator.operator_console_projection import build_operator_console_projection
    from runtime.orchestrator.operations_read_model import build_operations_read_model_from_console_snapshot

    snapshot = read_dashboard_state_projection_only(project_root, run_id=run_id)
    stage_gate = snapshot.get("stage_gate_result") if isinstance(snapshot.get("stage_gate_result"), dict) else {}
    console = build_operator_console_projection(
        {
            "project_id": _console_atom(snapshot.get("project_name"), "UNKNOWN_PROJECT"),
            "run_id": _console_atom(snapshot.get("run_id"), "UNKNOWN_RUN"),
            "task_id": "",
            "gate_id": _console_atom(stage_gate.get("gate_id"), "UNKNOWN_GATE"),
            "stage": _console_atom(snapshot.get("current_phase"), "UNKNOWN"),
            "execution_readiness": "WAITING_APPROVAL" if snapshot.get("approval_required") else "READY",
            "operator_authority_label": "GPT_OPERATOR",
            "checkpoint_refs": tuple(),
            "evidence_refs": tuple(),
        },
        transport_state="OBSERVE_ONLY",
        status_flags=tuple(),
    )
    diagnostic_findings = snapshot.get("diagnostic_findings")
    if not isinstance(diagnostic_findings, list):
        diagnostic_findings = []
    attention_events = snapshot.get("attention_events")
    if not isinstance(attention_events, list):
        attention_events = []
    recovery_refs = snapshot.get("recovery_refs")
    if not isinstance(recovery_refs, list):
        recovery_refs = []
    health = build_diagnostic_health_projection(
        current_state={"normalized_state": console.stage, "freshness": "UNKNOWN"},
        diagnostic_findings=diagnostic_findings,
        attention_events=attention_events,
        recovery_refs=tuple(str(item) for item in recovery_refs),
    )
    acceptance = snapshot.get("operational_acceptance")
    return build_operations_read_model_from_console_snapshot(
        console,
        snapshot,
        diagnostic_health=health,
        operational_acceptance=acceptance if isinstance(acceptance, dict) else None,
    ).to_dict()


def get_status(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    return refresh_dashboard_snapshot(project_root, run_id=run_id)


def get_active_project(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    snapshot = refresh_dashboard_snapshot(project_root, run_id=run_id)
    return {
        "project_root": snapshot.get("project_root", ""),
        "project_name": snapshot.get("project_name", ""),
        "run_id": snapshot.get("run_id", ""),
        "current_phase": snapshot.get("current_phase", ""),
        "next_step": snapshot.get("next_step", ""),
    }


def get_workers(project_root: str | Path, run_id: str | None = None) -> list[dict[str, Any]]:
    snapshot = refresh_dashboard_snapshot(project_root, run_id=run_id)
    return list(snapshot.get("active_workers", []))


def get_pending_approvals(project_root: str | Path, run_id: str | None = None) -> list[dict[str, Any]]:
    return read_pending_approvals(project_root, run_id=run_id)


def submit_approval(project_root: str | Path, approval: str, run_id: str | None = None) -> dict[str, Any]:
    return _submit_approval(project_root, approval, run_id=run_id)


def run_command(
    project_root: str | Path,
    command: str,
    *,
    run_id: str | None = None,
    mode: str = "mock",
    approval: str = "",
    execute: bool = True,
) -> dict[str, Any]:
    return dispatch_command(project_root, command, run_id=run_id, mode=mode, approval=approval, execute=execute)


def get_recent_logs(project_root: str | Path, run_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    return read_recent_events(project_root, run_id=run_id, limit=limit)


def get_stage_gate_result(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    snapshot = refresh_dashboard_snapshot(project_root, run_id=run_id)
    return dict(snapshot.get("stage_gate_result", {}))


def render_dashboard(project_root: str | Path, run_id: str | None = None) -> str:
    snapshot = refresh_dashboard_snapshot(project_root, run_id=run_id)
    return render_dashboard_markdown(snapshot)
