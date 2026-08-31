import tempfile
import unittest

from runtime.orchestrator.production_gate_runner import ProductionGateRunner, ProductionGateRunnerError


class ProductionGateRunnerTests(unittest.TestCase):
    def runner(self, root):
        return ProductionGateRunner(root,project_id="p",gate_id="g",run_id="r",mode="GATE_BY_GATE",
                                    canonical_lvs=["done","partial","new-a","new-b"],inherited_completed_lvs=["done"])

    def test_three_remaining_lvs_single_call_to_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def execute(lv): calls.append(lv); return {"status":"SYSTEM_TRANSITION","lv_id":lv,"review_verdicts":["PASS"]}
            out=self.runner(d).run(execute,lambda completed:{"gate_status":"EXITED","next_gate_status":"USER_APPROVAL_REQUIRED","completed_lvs":list(completed)})
            self.assertEqual(calls,["partial","new-a","new-b"]); self.assertEqual(out["status"],"USER_APPROVAL_REQUIRED")
            self.assertEqual(out["state"]["user_resume_requests"],0); self.assertEqual(out["state"]["user_lv_approval_requests"],0)
            self.assertEqual(out["state"]["worker_invocations"],{"partial":1,"new-a":1,"new-b":1})

    def test_review_remediation_is_internal_to_lv_and_worker_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            def execute(lv): return {"status":"SYSTEM_TRANSITION","lv_id":lv,"review_verdicts":["FAIL","PASS"],"remediated":True}
            out=self.runner(d).run(execute,lambda _:{"gate_status":"EXITED","next_gate_status":"USER_APPROVAL_REQUIRED"})
            self.assertTrue(out["state"]["last_lv_outcome"]["remediated"])
            self.assertTrue(all(value==1 for value in out["state"]["worker_invocations"].values()))

    def test_restart_after_checkpoint_and_terminal_replay(self):
        with tempfile.TemporaryDirectory() as d:
            first=self.runner(d); count=[0]
            def crash(lv):
                count[0]+=1
                if count[0]==2: raise RuntimeError("process crash")
                return {"status":"SYSTEM_TRANSITION","lv_id":lv}
            with self.assertRaises(RuntimeError): first.run(crash,lambda _:self.fail())
            seen=[]
            out=self.runner(d).run(lambda lv:(seen.append(lv) or {"status":"SYSTEM_TRANSITION","lv_id":lv}),lambda _:{"gate_status":"EXITED","next_gate_status":"USER_APPROVAL_REQUIRED"})
            self.assertEqual(seen,["new-a","new-b"]); self.assertEqual(out["status"],"USER_APPROVAL_REQUIRED")
            replay=self.runner(d).run(lambda _:self.fail("completed LV rerun"),lambda _:self.fail("terminal rerun"))
            self.assertFalse(replay["mutation_performed"]); self.assertEqual(replay["invoked_lvs"],[])

    def test_no_progress_order_budget_and_gate_boundary_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProductionGateRunnerError,"no canonical progress"):
                self.runner(d).run(lambda lv:{"status":"PASS","lv_id":lv},lambda _: {})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProductionGateRunnerError,"terminal boundary"):
                self.runner(d).run(lambda lv:{"status":"SYSTEM_TRANSITION","lv_id":lv},lambda _:{"gate_status":"EXITED","next_gate_status":"NEXT_GATE_RUNNING"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProductionGateRunnerError,"out of order"):
                ProductionGateRunner(d,project_id="p",gate_id="g",run_id="r",mode="GATE_BY_GATE",canonical_lvs=["a","b"],inherited_completed_lvs=["b"])

    def test_full_plan_requires_different_authorization_surface(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProductionGateRunnerError,"GATE_BY_GATE"):
                ProductionGateRunner(d,project_id="p",gate_id="g",run_id="r",mode="FULL_PLAN",canonical_lvs=["a"],inherited_completed_lvs=[])
