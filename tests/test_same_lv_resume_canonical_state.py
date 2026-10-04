import unittest

from runtime.orchestrator.gate_orchestrator import (
    _project_sealed_state_for_lv_invocation,
)


class SameLVResumeCanonicalStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = "a" * 40
        self.current = "b" * 40
        self.state = {
            "state": "GATE1_RESUME_READY",
            "checkpoint_commit": self.baseline,
            "active_scope": ["TASK-001"],
        }
        self.transition = {
            "schema_version": "orchestration.canonical-active-lv-transition.v1",
            "baseline_head": self.baseline,
            "current_head": self.current,
            "transition_type": "SYSTEM_TRANSITION",
        }

    def test_same_lv_resume_preserves_immutable_package_checkpoint(self) -> None:
        projected = _project_sealed_state_for_lv_invocation(
            self.state,
            transition_record=self.transition,
            observed_head=self.current,
            lv_resume=True,
        )
        self.assertEqual(projected["checkpoint_commit"], self.baseline)
        self.assertNotIn("transition", projected)
        self.assertEqual(self.state["checkpoint_commit"], self.baseline)
        self.assertNotIn("transition", self.state)

    def test_fresh_successor_lv_projects_transition_current_head(self) -> None:
        projected = _project_sealed_state_for_lv_invocation(
            self.state,
            transition_record=self.transition,
            observed_head=self.current,
            lv_resume=False,
        )
        self.assertEqual(projected["checkpoint_commit"], self.current)
        self.assertEqual(projected["transition"], self.transition)
        self.assertEqual(self.state["checkpoint_commit"], self.baseline)
        self.assertNotIn("transition", self.state)

    def test_no_transition_returns_copy_without_checkpoint_drift(self) -> None:
        projected = _project_sealed_state_for_lv_invocation(
            self.state,
            transition_record=None,
            observed_head=self.baseline,
            lv_resume=True,
        )
        self.assertEqual(projected, self.state)
        self.assertIsNot(projected, self.state)


if __name__ == "__main__":
    unittest.main()
