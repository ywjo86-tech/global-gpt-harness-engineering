"""Jarvis bridge for reading orchestration state and dispatching commands."""

from .approval_handler import read_pending_approvals, submit_approval
from .bridge_api import (
    get_active_project,
    get_pending_approvals,
    get_recent_logs,
    get_stage_gate_result,
    get_status,
    get_workers,
    refresh_dashboard_snapshot,
    run_command,
)
from .command_dispatcher import dispatch_command
from .event_stream import read_recent_events
from .state_reader import read_dashboard_state, render_dashboard_markdown

