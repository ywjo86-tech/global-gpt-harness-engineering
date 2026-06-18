from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .task_queue import TaskQueueItem


@dataclass(slots=True)
class RetryDecision:
    thread_id: str
    can_retry: bool
    retry_count: int
    max_retries: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def should_retry(item: TaskQueueItem, *, max_retries: int = 2) -> RetryDecision:
    if item.status != "failed":
        return RetryDecision(item.thread_id, False, item.retry_count, max_retries, "task is not failed")
    if item.retry_count >= max_retries:
        return RetryDecision(item.thread_id, False, item.retry_count, max_retries, "retry budget exhausted")
    if item.risk_class == "dangerous":
        return RetryDecision(item.thread_id, False, item.retry_count, max_retries, "dangerous work requires fresh approval")
    return RetryDecision(item.thread_id, True, item.retry_count, max_retries, "eligible for retry")


def next_retry_count(item: TaskQueueItem) -> int:
    return item.retry_count + 1
