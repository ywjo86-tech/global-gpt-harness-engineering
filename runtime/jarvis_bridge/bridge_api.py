from __future__ import annotations

from pathlib import Path
from typing import Any

from .approval_handler import read_pending_approvals, submit_approval as _submit_approval
from .command_dispatcher import dispatch_command
from .event_stream import read_recent_events
from .state_reader import read_dashboard_state, render_dashboard_markdown


def refresh_dashboard_snapshot(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    return read_dashboard_state(project_root, run_id=run_id)


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
