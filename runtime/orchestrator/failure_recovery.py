from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .retry_policy import RetryDecision, next_retry_count, should_retry
from .task_queue import TaskQueueItem


@dataclass(slots=True)
class FailureRecoveryPlan:
    retryable: list[dict[str, Any]]
    blocked: list[dict[str, Any]]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_failure_recovery_plan(queue: list[TaskQueueItem], *, max_retries: int = 2) -> FailureRecoveryPlan:
    retryable: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in queue:
        decision: RetryDecision = should_retry(item, max_retries=max_retries)
        payload = {
            "thread_id": item.thread_id,
            "assigned_agent": item.assigned_agent,
            "status": item.status,
            "retry_count": item.retry_count,
            "can_retry": decision.can_retry,
            "reason": decision.reason,
        }
        if decision.can_retry:
            payload["next_retry_count"] = next_retry_count(item)
            retryable.append(payload)
        elif item.status == "failed":
            blocked.append(payload)
    summary = f"retryable={len(retryable)} blocked={len(blocked)}"
    return FailureRecoveryPlan(retryable=retryable, blocked=blocked, summary=summary)
