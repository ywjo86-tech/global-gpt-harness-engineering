from __future__ import annotations

from pathlib import Path
from typing import Any

from .command_dispatcher import dispatch_command
from .state_reader import read_dashboard_state


def read_pending_approvals(project_root: str | Path, run_id: str | None = None) -> list[dict[str, Any]]:
    snapshot = read_dashboard_state(project_root, run_id=run_id)
    return list(snapshot.get("pending_approvals", []))


def submit_approval(project_root: str | Path, approval: str, run_id: str | None = None) -> dict[str, Any]:
    return dispatch_command(project_root, "approve", run_id=run_id, approval=approval, execute=True)
