import tempfile
import unittest

from tests.test_production_lifecycle import binding
from runtime.orchestrator.gate_terminal import GateTerminalController, GateTerminalError


class GateTerminalTests(unittest.TestCase):
    def test_three_lv_lifecycle_restart_after_checkpoint_and_lv_exit(self):
        with tempfile.TemporaryDirectory() as d:
            one=GateTerminalController(d,binding(),["LV-1","LV-2","LV-3"])
            self.assertEqual(one.review_pass("LV-1")["next_lv"],"LV-2")
            two=GateTerminalController(d,binding(),["LV-1","LV-2","LV-3"])
            self.assertEqual(two.review_pass("LV-2")["next_lv"],"LV-3")
            final=GateTerminalController(d,binding(),["LV-1","LV-2","LV-3"]).review_pass("LV-3")
            self.assertEqual(final["stage"],"HANDOFF_SEALED"); self.assertEqual(final["next_gate_status"],"USER_APPROVAL_REQUIRED")

    def test_terminal_replay_is_idempotent_and_next_gate_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            controller=GateTerminalController(d,binding(),["LV-1"]); first=controller.review_pass("LV-1")
            self.assertEqual(first,controller.replay_terminal())
            self.assertEqual(first,controller.review_pass("LV-1"))
            with self.assertRaisesRegex(GateTerminalError,"USER_APPROVAL_REQUIRED"): controller.start_next_gate()

    def test_duplicate_out_of_order_and_plan_drift_fail(self):
        with tempfile.TemporaryDirectory() as d:
            controller=GateTerminalController(d,binding(),["LV-1","LV-2"])
            with self.assertRaisesRegex(GateTerminalError,"out-of-order"): controller.review_pass("LV-2")
            controller.review_pass("LV-1")
            with self.assertRaisesRegex(GateTerminalError,"plan binding"): GateTerminalController(d,binding(),["LV-X"]).load()


if __name__ == "__main__": unittest.main()
