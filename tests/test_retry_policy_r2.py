from __future__ import annotations

import unittest

from runtime.orchestrator.retry_policy import should_retry
from runtime.orchestrator.task_queue import TaskQueueItem
from runtime.orchestrator.user_interaction_policy import ApprovalCoverageEvidence


def failed_task(*, risk_class: str = "dangerous", retry_count: int = 0) -> TaskQueueItem:
    return TaskQueueItem(
        task_id="TASK-1", project_path="/tmp/project", thread_id="thread-1",
        assigned_agent="implementation_agent", risk_class=risk_class,
        status="failed", retry_count=retry_count,
    )


def coverage(*, exact: bool = True) -> ApprovalCoverageEvidence:
    return ApprovalCoverageEvidence(
        approval_ref="approval://full-plan/1",
        approved_semantic_digest="a" * 64,
        reviewed_semantic_digest=("a" if exact else "b") * 64,
        allowed_risk_classes=("dangerous",),
        allowed_operations=("TASK_RETRY",),
    )


class RetryPolicyR2Tests(unittest.TestCase):
    def test_dangerous_retry_defaults_to_fresh_approval(self) -> None:
        out = should_retry(failed_task())
        self.assertFalse(out.can_retry)
        self.assertIn("approval", out.reason)

    def test_dangerous_retry_allows_exact_coverage_and_no_effect(self) -> None:
        out = should_retry(
            failed_task(), approval_coverage=coverage(), effect_reconciliation="NO_EFFECT",
        )
        self.assertTrue(out.can_retry)
        self.assertEqual(out.retry_count, 0)

    def test_dangerous_retry_allows_reconciled_effect(self) -> None:
        out = should_retry(
            failed_task(), approval_coverage=coverage(), effect_reconciliation="RECONCILED",
        )
        self.assertTrue(out.can_retry)

    def test_ambiguous_or_stale_coverage_remains_blocked(self) -> None:
        ambiguous = should_retry(
            failed_task(), approval_coverage=coverage(), effect_reconciliation="AMBIGUOUS",
        )
        stale = should_retry(
            failed_task(), approval_coverage=coverage(exact=False), effect_reconciliation="NO_EFFECT",
        )
        self.assertFalse(ambiguous.can_retry)
        self.assertFalse(stale.can_retry)

    def test_retry_budget_still_has_precedence(self) -> None:
        out = should_retry(
            failed_task(retry_count=2), max_retries=2,
            approval_coverage=coverage(), effect_reconciliation="NO_EFFECT",
        )
        self.assertFalse(out.can_retry)
        self.assertEqual(out.reason, "retry budget exhausted")

    def test_general_retry_behavior_is_unchanged(self) -> None:
        out = should_retry(failed_task(risk_class="general"))
        self.assertTrue(out.can_retry)


if __name__ == "__main__":
    unittest.main()
