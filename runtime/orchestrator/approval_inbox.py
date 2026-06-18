from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .schemas import RuntimeState
from .task_queue import TaskQueueItem


@dataclass(slots=True)
class ApprovalInboxEntry:
    thread_id: str
    assigned_agent: str
    approval_classification: str
    reason: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_approval_inbox(state: RuntimeState, queue: list[TaskQueueItem]) -> list[ApprovalInboxEntry]:
    inbox: list[ApprovalInboxEntry] = []
    for item in queue:
        if item.approval_required and item.status in {"pending", "blocked_by_approval", "blocked_by_stage_gate"}:
            inbox.append(
                ApprovalInboxEntry(
                    thread_id=item.thread_id,
                    assigned_agent=item.assigned_agent,
                    approval_classification=item.risk_class,
                    reason="approval required before execution",
                    status=item.status,
                )
            )
    if state.approval_required and not inbox:
        inbox.append(
            ApprovalInboxEntry(
                thread_id=state.active_run_id or "run",
                assigned_agent="orchestrator",
                approval_classification="mixed",
                reason="pending approval exists in runtime state",
                status="pending_approval",
            )
        )
    return inbox


def write_approval_inbox(run_root: str | Path, inbox: list[ApprovalInboxEntry]) -> Path:
    root = Path(run_root)
    bridge_dir = root / "approval"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    json_path = bridge_dir / "approval_inbox.json"
    json_path.write_text(json.dumps([item.to_dict() for item in inbox], indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = bridge_dir / "approval_inbox.md"
    lines = [
        "# Approval Inbox",
        "",
        f"Pending approvals: {len(inbox)}",
        "",
        "## Items",
    ]
    if inbox:
        for item in inbox:
            lines.append(f"- {item.thread_id}: {item.assigned_agent} | {item.approval_classification} | {item.status}")
    else:
        lines.append("- none")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path
