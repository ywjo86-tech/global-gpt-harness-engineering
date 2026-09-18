from __future__ import annotations

import tempfile
import unittest

from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import WorkflowContractError, WorkflowCoordinator, next_state


class AIOfficeWorkflowTest(unittest.TestCase):
    def make(self, directory: str):
        store = AIOfficeStateStore(directory, project_id="PHASE5_AI_OFFICE_HARNESS_UPGRADE", run_id="workflow-run")
        store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:approved")
        coordinator = WorkflowCoordinator(store, office_id="CEO", department_id="PURCHASING", schedule_ref="schedule:daily")
        return store, coordinator

    def test_014_only_declared_transitions_are_valid(self) -> None:
        self.assertEqual(next_state("NEW", "REQUIREMENT_ACCEPTED"), "INTAKE_READY")
        with self.assertRaises(WorkflowContractError):
            next_state("NEW", "EXECUTION_ACCEPTED")

    def test_014_persisted_revision_advances_and_rehydrates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, coordinator = self.make(directory)
            first = coordinator.transition("REQUIREMENT_ACCEPTED", reason_ref="reason:intake")
            second = coordinator.transition("CONTEXT_ASSEMBLED", reason_ref="reason:context")
            self.assertEqual((first.revision, second.revision), (1, 2))
            restarted = AIOfficeStateStore(directory, project_id=store.project_id, run_id=store.run_id).load()
            self.assertEqual(restarted.revision, 2)
            self.assertEqual(restarted.workflow_state, "CONTEXT_READY")

    def test_014_full_plan_assignment_is_recorded_only_as_external_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, coordinator = self.make(directory)
            coordinator.transition("REQUIREMENT_ACCEPTED", reason_ref="reason:intake")
            coordinator.transition("CONTEXT_ASSEMBLED", reason_ref="reason:context")
            run = coordinator.transition(
                "FULL_PLAN_HANDOFF_REFERENCED",
                reason_ref="reason:handoff",
                external_assignment_ref="assignment:external-001",
            )
            self.assertEqual(run.workflow_state, "PLAN_COORDINATED")
            self.assertEqual(run.external_full_plan_assignment_ref, "assignment:external-001")
            self.assertEqual(run.external_fanin_ref, "")
            with self.assertRaises(WorkflowContractError):
                coordinator.transition(
                    "GOVERNANCE_READY",
                    reason_ref="reason:governance",
                    external_assignment_ref="assignment:illegal-rewrite",
                )


if __name__ == "__main__":
    unittest.main()
