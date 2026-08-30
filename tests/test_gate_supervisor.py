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
            self.assertEqual(result.state["metrics"]["model_invocations"],0)

    def test_canonical_lifecycle_review_fail_remediates_then_exits(self):
        with tempfile.TemporaryDirectory() as d:
            sup=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="GATE_BY_GATE",lv_order=["l1"])
            seen=[]; review_count=[0]
            def handler(name, status="PASS"):
                def call(state):
                    seen.append(name)
                    if name == "REVIEW" and review_count[0] == 0:
                        review_count[0] += 1; return {"status":"FAIL","error_signature":"review-failure","progress_digest":"d1"}
                    return {"status":status}
                return call
            handlers={name:handler(name) for name in ("PACKAGE","PREFLIGHT","WORKER","REVIEW","REMEDIATION","CHECKPOINT","EXIT")}
            result=sup.run_lifecycle(handlers)
            self.assertEqual(result.status,"USER_APPROVAL_REQUIRED")
            self.assertIn("REMEDIATION",seen); self.assertEqual(seen.count("WORKER"),1)

    def test_registry_routing_requires_exact_scope_and_capabilities(self):
        manifests=[{"asset_id":"codex","scope":"global","capabilities":["implement"],"permissions":["write"],"owned_files":["app/"]},
                   {"asset_id":"review","scope":"global","capabilities":["review"],"permissions":["read"],"owned_files":["app/"]}]
        result=PersistentGateSupervisor.select_worker_asset(manifests,capabilities={"implement"},permissions={"write"},owned_files=["app/x.py"])
        self.assertEqual(result["selected"],["codex"])
        with self.assertRaisesRegex(GateSupervisorError,"ambiguous"):
            PersistentGateSupervisor.select_worker_asset(manifests+[manifests[0]],capabilities={"implement"},permissions={"write"},owned_files=["app/x.py"])
