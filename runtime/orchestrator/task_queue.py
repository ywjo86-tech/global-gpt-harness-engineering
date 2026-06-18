from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import RuntimeState, TaskSlice


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class TaskQueueItem:
    task_id: str
    project_path: str
    thread_id: str
    assigned_agent: str
    risk_class: str
    input_files: list[str] = field(default_factory=list)
    editable_scope: list[str] = field(default_factory=list)
    forbidden_scope: list[str] = field(default_factory=list)
    expected_output: str = ""
    status: str = "pending"
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    retry_count: int = 0
    approval_required: bool = False
    next_step: str = ""
    worker_request_path: str = ""
    output_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _task_id(run_id: str, thread_id: str) -> str:
    return f"{run_id}:{thread_id}"


def build_task_queue(state: RuntimeState, tasks: list[TaskSlice], *, project_root: str) -> list[TaskQueueItem]:
    pending_threads = {item.get("thread_id", ""): item for item in state.pending_workers}
    completed_threads = {item.get("thread_id", ""): item for item in state.completed_workers}
    failed_threads = {item.get("thread_id", ""): item for item in state.failed_workers}
    items: list[TaskQueueItem] = []
    for task in tasks:
        requires_approval = task.thread_id in pending_threads
        status = "pending"
        if task.thread_id in completed_threads:
            status = "completed"
        elif task.thread_id in failed_threads:
            status = "failed"
        elif requires_approval:
            status = "blocked_by_approval"
        items.append(
            TaskQueueItem(
                task_id=_task_id(state.active_run_id or state.run_root or "run", task.thread_id),
                project_path=project_root,
                thread_id=task.thread_id,
                assigned_agent=task.assigned_agent,
                risk_class=task.risk_class,
                input_files=[
                    path
                    for path in [
                        task.task_prompt_path,
                        task.input_manifest_path,
                        task.expected_output_path,
                        task.worker_request_path,
                    ]
                    if path
                ],
                editable_scope=list(task.editable_scope or []),
                forbidden_scope=list(task.forbidden_scope or []),
                expected_output=task.expected_output,
                status=status,
                created_at=_utc_now(),
                retry_count=0,
                approval_required=requires_approval,
                next_step=task.merge_point,
                worker_request_path=task.worker_request_path,
                output_dir=task.output_dir,
            )
        )
    return items


def summarize_task_queue(queue: list[TaskQueueItem]) -> dict[str, Any]:
    counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "blocked_by_approval": 0,
        "blocked_by_stage_gate": 0,
        "cancelled": 0,
    }
    approvals_required = 0
    for item in queue:
        counts[item.status] = counts.get(item.status, 0) + 1
        if item.approval_required:
            approvals_required += 1
    return {
        "queue_size": len(queue),
        "status_counts": counts,
        "approvals_required": approvals_required,
        "runnable_threads": [item.thread_id for item in queue if item.status == "pending" and not item.approval_required],
        "blocked_threads": [item.thread_id for item in queue if item.status.startswith("blocked")],
    }


def write_task_queue(run_root: str | Path, queue: list[TaskQueueItem]) -> Path:
    root = Path(run_root)
    queue_dir = root / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in queue]
    json_path = queue_dir / "task_queue.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = queue_dir / "task_queue.md"
    lines = [
        "# Task Queue",
        "",
        f"Queue size: {len(queue)}",
        "",
        "## Items",
    ]
    if queue:
        for item in queue:
            lines.append(
                f"- {item.thread_id}: {item.assigned_agent} | {item.status} | approval_required={item.approval_required}"
            )
    else:
        lines.append("- none")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path
