import tempfile, unittest
from pathlib import Path
from runtime.orchestrator.gate_supervisor import GateSupervisorError, PersistentGateSupervisor


class GateSupervisorTests(unittest.TestCase):
    def test_unattended_multilv_gate_by_gate_stops_at_approval_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            sup=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="GATE_BY_GATE",lv_order=["l1","l2"])
            calls=[]
            def transition(state):
                calls.append((state["current_lv"],state["stage"]))
                if state["stage"] == "GATE_EXIT": return {"status":"PASS","next_stage":"GATE_EXIT"}
                return {"status":"PASS","next_stage":"EXIT" if state["stage"] == "CHECKPOINT" else "CHECKPOINT"}
            # Worker through the lifecycle; EXIT is reached after CHECKPOINT.
            result=sup.run(transition)
            self.assertEqual(result.status,"USER_APPROVAL_REQUIRED"); self.assertGreater(result.invocations,2)
            replay=sup.run(lambda _:self.fail("terminal replay invoked child"))
            self.assertEqual(replay.invocations,0); self.assertFalse(replay.mutation_performed)

    def test_full_plan_completes_multiple_lvs_and_restart_replay(self):
        with tempfile.TemporaryDirectory() as d:
            sup=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="FULL_PLAN",lv_order=["l1","l2"])
            result=sup.run(lambda state:{"status":"PASS","next_stage":"GATE_EXIT" if state["stage"] == "GATE_EXIT" else "EXIT"})
            self.assertEqual(result.status,"COMPLETED"); self.assertEqual(result.state["completed_lvs"],["l1","l2"])
            replay=sup.run(lambda _:self.fail("terminal replay invoked child"))
            self.assertEqual(replay.invocations,0); self.assertFalse(replay.mutation_performed)

    def test_duplicate_supervisor_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            sup=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="FULL_PLAN",lv_order=["l1"])
            lock=sup._lock()
            try:
                with self.assertRaisesRegex(GateSupervisorError,"duplicate"):
                    sup.run(lambda _: {"status":"PASS","next_stage":"EXIT"})
            finally:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN); lock.close()

    def test_restart_resumes_persisted_stage_without_user_input(self):
        with tempfile.TemporaryDirectory() as d:
            sup=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="FULL_PLAN",lv_order=["l1"])
            first=sup.run(lambda state:{"status":"PASS","next_stage":"CHECKPOINT"},max_steps=1)
            self.assertEqual(first.status,"GATE_EXECUTION_RESUME_REQUIRED")
            resumed=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="FULL_PLAN",lv_order=["l1"])
            result=resumed.run(lambda state:{"status":"PASS","next_stage":"GATE_EXIT" if state["stage"] == "GATE_EXIT" else "EXIT"})
            self.assertEqual(result.status,"COMPLETED"); self.assertEqual(result.state["completed_lvs"],["l1"])

    def test_failure_retries_then_hard_stops_without_loop(self):
        with tempfile.TemporaryDirectory() as d:
            sup=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="FULL_PLAN",lv_order=["l1"],retry_budget=1)
            result=sup.run(lambda _: {"status":"FAIL","error_signature":"same"})
            self.assertEqual(result.status,"HARD_STOP"); self.assertEqual(result.state["retries"],{"same":1})
