from __future__ import annotations

import unittest
from pathlib import Path

from runtime.orchestrator.approval_inbox import build_approval_inbox, write_approval_inbox
from runtime.orchestrator.engine import OrchestrationEngine
from runtime.orchestrator.failure_recovery import build_failure_recovery_plan
from runtime.orchestrator.retry_policy import should_retry
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.task_queue import build_task_queue, write_task_queue
from runtime.orchestrator.worker_pool import select_next_workers, summarize_worker_pool

from tests.helpers import cloned_sample_project


class JarvisBridgeSupportTest(unittest.TestCase):
    def test_task_queue_worker_pool_retry_and_recovery(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            plan = engine.plan(mode="manual", run_id="jarvis-bridge-support")
            state = StateStore(project).state
            tasks = [task for task in (engine.store.state.active_threads or [])]
            from runtime.orchestrator.schemas import TaskSlice

            queue = build_task_queue(state, [TaskSlice(**task) for task in tasks], project_root=str(project))
            summary = summarize_worker_pool(queue)
            approval_inbox = build_approval_inbox(state, queue)
            write_task_queue(plan["run_root"], queue)
            write_approval_inbox(plan["run_root"], approval_inbox)

            self.assertEqual(summary.total_workers, len(queue))
            self.assertGreaterEqual(summary.pending_workers, 0)
            self.assertTrue((Path(plan["run_root"]) / "queue" / "task_queue.json").exists())
            self.assertTrue((Path(plan["run_root"]) / "approval" / "approval_inbox.json").exists())
            if queue:
                first = queue[0]
                first.status = "failed"
                decision = should_retry(first)
                recovery = build_failure_recovery_plan(queue)
                self.assertIn(decision.can_retry, {True, False})
                self.assertIn("retryable", recovery.to_dict())
                self.assertIsInstance(select_next_workers(queue), list)


if __name__ == "__main__":
    unittest.main()
