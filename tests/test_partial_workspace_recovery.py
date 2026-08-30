import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_production_lifecycle import binding
from runtime.orchestrator.partial_workspace_recovery import PartialRecoveryError, PartialRecoveryMachine


class PartialWorkspaceRecoveryTests(unittest.TestCase):
    def machine(self, root):
        machine=PartialRecoveryMachine(root,binding()); machine.advance("WORKER_REQUESTED"); machine.advance("WORKER_RUNNING"); machine.advance("PARTIAL_WORKSPACE_DETECTED"); return machine

    def test_live_worker_blocks_duplicate_and_pid_reuse_is_terminated(self):
        with tempfile.TemporaryDirectory() as d:
            live=self.machine(d); self.assertEqual(live.classify_worker(recorded_pid=7,recorded_start="10",process_probe=lambda p:"10",diff={"a.py":"x"},owned_scope=["a.py"]),"LIVE_BOUND_WORKER")
        with tempfile.TemporaryDirectory() as d:
            reused=self.machine(d); self.assertEqual(reused.classify_worker(recorded_pid=7,recorded_start="10",process_probe=lambda p:"11",diff={"a.py":"x"},owned_scope=["a.py"]),"TERMINATED_ADOPTABLE_PARTIAL")

    def test_terminated_diff_adoption_scope_and_duplicate_replay(self):
        with tempfile.TemporaryDirectory() as d:
            machine=self.machine(d); machine.classify_worker(recorded_pid=7,recorded_start="10",process_probe=lambda p:None,diff={"a.py":"x"},owned_scope=["a.py"])
            first=machine.adopt({"a.py":"x"},["a.py"]); self.assertEqual(first,machine.adopt({"a.py":"x"},["a.py"]))
        with tempfile.TemporaryDirectory() as d:
            machine=self.machine(d); self.assertEqual(machine.classify_worker(recorded_pid=7,recorded_start="10",process_probe=lambda p:None,diff={"bad.py":"x"},owned_scope=["a.py"]),"INVALID_OR_AMBIGUOUS_PARTIAL")

    def test_crash_restart_atomic_publication_and_no_manual_completion(self):
        with tempfile.TemporaryDirectory() as d:
            machine=self.machine(d); machine.classify_worker(recorded_pid=7,recorded_start="10",process_probe=lambda p:None,diff={"a.py":"x"},owned_scope=["a.py"]); machine.adopt({"a.py":"x"},["a.py"])
            restarted=PartialRecoveryMachine(d,binding()); self.assertEqual(restarted.state,"ADOPTION_VALIDATED")
            with patch("runtime.orchestrator.partial_workspace_recovery.os.link",side_effect=OSError("fixture")), self.assertRaises(OSError): restarted.publish_result({"status":"completed"})
            self.assertFalse((Path(d)/"worker.result.json").exists())
            restarted.publish_result({"status":"completed"}); self.assertEqual(restarted.publish_result({"status":"completed"})["payload"]["status"],"completed")
            with self.assertRaises(PartialRecoveryError): restarted.complete()

    def test_review_fail_remediation_pass_checkpoint_exit(self):
        with tempfile.TemporaryDirectory() as d:
            machine=self.machine(d); machine.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={"a.py":"x"},owned_scope=["a.py"]); machine.adopt({"a.py":"x"},["a.py"]); machine.publish_result({"status":"completed"})
            self.assertEqual(machine.review("FAIL"),"REMEDIATION_REQUIRED")
            # A remediation publishes a distinct machine/result namespace in production;
            # the state transition itself remains generic and replay-safe here.
            machine.advance("RESULT_PUBLISHED",{"remediated":True}); self.assertEqual(machine.review("PASS"),"REVIEW_PASSED"); machine.complete(); self.assertEqual(machine.state,"LV_EXITED")


if __name__ == "__main__": unittest.main()
