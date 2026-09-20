from __future__ import annotations

import unittest

from runtime.orchestrator.operator_turn_budget import (
    CHECKPOINT_REQUIRED,
    CONTINUE_CURRENT_TASK,
    START_NEXT_TASK,
    YIELD_AT_CHECKPOINT,
    assess_turn_budget,
    full_regression_allowed,
)


class OperatorTurnBudgetTests(unittest.TestCase):
    def test_next_task_starts_only_when_estimate_plus_reserve_fits(self) -> None:
        decision = assess_turn_budget(
            elapsed_seconds=100, soft_budget_seconds=600,
            estimated_work_seconds=200, reserve_seconds=120,
            task_in_progress=False, durable_checkpoint=True, long_process_durable=True,
        )
        self.assertEqual(decision.disposition, START_NEXT_TASK)

    def test_near_budget_does_not_start_new_task(self) -> None:
        decision = assess_turn_budget(
            elapsed_seconds=400, soft_budget_seconds=600,
            estimated_work_seconds=120, reserve_seconds=120,
            task_in_progress=False, durable_checkpoint=True, long_process_durable=True,
        )
        self.assertEqual(decision.disposition, YIELD_AT_CHECKPOINT)

    def test_near_budget_requires_checkpoint_before_yield(self) -> None:
        decision = assess_turn_budget(
            elapsed_seconds=500, soft_budget_seconds=600,
            estimated_work_seconds=60, reserve_seconds=120,
            task_in_progress=True, durable_checkpoint=False, long_process_durable=False,
        )
        self.assertEqual(decision.disposition, CHECKPOINT_REQUIRED)
        self.assertFalse(decision.allow_turn_yield)

    def test_long_running_work_can_yield_only_with_durable_process_and_checkpoint(self) -> None:
        blocked = assess_turn_budget(
            elapsed_seconds=500, soft_budget_seconds=600,
            estimated_work_seconds=200, reserve_seconds=120,
            task_in_progress=True, durable_checkpoint=True, long_process_durable=False,
        )
        self.assertEqual(blocked.disposition, CHECKPOINT_REQUIRED)
        safe = assess_turn_budget(
            elapsed_seconds=500, soft_budget_seconds=600,
            estimated_work_seconds=200, reserve_seconds=120,
            task_in_progress=True, durable_checkpoint=True, long_process_durable=True,
        )
        self.assertEqual(safe.disposition, YIELD_AT_CHECKPOINT)
        self.assertTrue(safe.allow_turn_yield)

    def test_in_progress_work_continues_when_budget_is_sufficient(self) -> None:
        decision = assess_turn_budget(
            elapsed_seconds=100, soft_budget_seconds=600,
            estimated_work_seconds=120, reserve_seconds=120,
            task_in_progress=True, durable_checkpoint=False, long_process_durable=False,
        )
        self.assertEqual(decision.disposition, CONTINUE_CURRENT_TASK)

    def test_full_regression_is_gate_or_final_only(self) -> None:
        self.assertFalse(full_regression_allowed("TASK_COMPLETE"))
        self.assertTrue(full_regression_allowed("GATE_CLOSE"))
        self.assertTrue(full_regression_allowed("FINAL_EDP"))


if __name__ == "__main__":
    unittest.main()
