from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .task_queue import TaskQueueItem


@dataclass(slots=True)
class WorkerPoolSummary:
    total_workers: int
    runnable_workers: int
    blocked_workers: int
    completed_workers: int
    failed_workers: int
    pending_workers: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_worker_pool(queue: list[TaskQueueItem]) -> WorkerPoolSummary:
    blocked = [item for item in queue if item.status.startswith("blocked")]
    completed = [item for item in queue if item.status == "completed"]
    failed = [item for item in queue if item.status == "failed"]
    pending = [item for item in queue if item.status == "pending"]
    runnable = [item for item in pending if not item.approval_required]
    return WorkerPoolSummary(
        total_workers=len(queue),
        runnable_workers=len(runnable),
        blocked_workers=len(blocked),
        completed_workers=len(completed),
        failed_workers=len(failed),
        pending_workers=len(pending),
    )


def select_next_workers(queue: list[TaskQueueItem], limit: int | None = None) -> list[TaskQueueItem]:
    runnable = [item for item in queue if item.status == "pending" and not item.approval_required]
    if limit is None:
        return runnable
    return runnable[: max(limit, 0)]
