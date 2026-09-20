"""Bounded Operator-turn execution policy.

This module does not own orchestration or effects. It only answers whether the
current turn should continue the current task, start another task, checkpoint,
or yield at an already-durable checkpoint before a caller-supplied soft budget.
"""
from __future__ import annotations

from dataclasses import dataclass

START_NEXT_TASK = "START_NEXT_TASK"
CONTINUE_CURRENT_TASK = "CONTINUE_CURRENT_TASK"
CHECKPOINT_REQUIRED = "CHECKPOINT_REQUIRED"
YIELD_AT_CHECKPOINT = "YIELD_AT_CHECKPOINT"
FULL_REGRESSION_POINTS = frozenset({"GATE_CLOSE", "FINAL_EDP"})


@dataclass(frozen=True, slots=True)
class TurnBudgetDecision:
    disposition: str
    allow_turn_yield: bool
    remaining_seconds: int
    reason: str


def full_regression_allowed(reason: str) -> bool:
    return str(reason).strip() in FULL_REGRESSION_POINTS


def assess_turn_budget(
    *, elapsed_seconds: int, soft_budget_seconds: int,
    estimated_work_seconds: int, reserve_seconds: int,
    task_in_progress: bool, durable_checkpoint: bool,
    long_process_durable: bool,
) -> TurnBudgetDecision:
    values = (elapsed_seconds, soft_budget_seconds, estimated_work_seconds, reserve_seconds)
    if any(not isinstance(value, int) or value < 0 for value in values) or soft_budget_seconds == 0:
        raise ValueError("turn budget values must be non-negative integers with positive soft budget")
    remaining = max(0, soft_budget_seconds - elapsed_seconds)
    fits = estimated_work_seconds + reserve_seconds <= remaining
    if fits:
        return TurnBudgetDecision(
            CONTINUE_CURRENT_TASK if task_in_progress else START_NEXT_TASK,
            False, remaining, "estimated work fits inside soft budget and reserve",
        )
    if not durable_checkpoint:
        return TurnBudgetDecision(
            CHECKPOINT_REQUIRED, False, remaining,
            "soft budget reserve would be crossed before a durable checkpoint exists",
        )
    if task_in_progress and not long_process_durable:
        return TurnBudgetDecision(
            CHECKPOINT_REQUIRED, False, remaining,
            "in-flight long work is not durably recoverable",
        )
    return TurnBudgetDecision(
        YIELD_AT_CHECKPOINT, True, remaining,
        "soft budget reserve reached with durable continuation evidence",
    )
