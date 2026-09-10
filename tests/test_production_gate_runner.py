import tempfile
import unittest
import json
from unittest.mock import patch

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

    def test_startup_persists_runner_root_before_callback_failure(self):
        with tempfile.TemporaryDirectory() as d:
            runner = self.runner(d)
            with self.assertRaises(RuntimeError):
                runner.run(lambda _: (_ for _ in ()).throw(RuntimeError("startup fixture")), lambda _: {})
            self.assertTrue(runner.state_path.is_file())
            self.assertTrue(runner.run_root.is_dir())
            self.assertTrue(runner.startup_path.is_file())
            events = runner.events_path.read_text(encoding="utf-8").splitlines()
            self.assertTrue(any('"event":"RUN_STARTED"' in row for row in events))

    def test_startup_failure_readback_preserves_helper_boundary_id(self):
        with tempfile.TemporaryDirectory() as d:
            runner = self.runner(d)
            runner.ensure_started()
            runner.record_startup_failure(
                stage="AUTHORIZATION", category="UNKNOWN",
                authorization_failure_source="GOVERNANCE",
                authorization_reason_presence="ABSENT",
                authorization_reason_mapping="UNKNOWN",
                authorization_helper_id="VERIFY_SAME_RUN_GOVERNED_DESCENDANT",
                authorization_entry_id="AUTHORIZE_PRODUCTION_DESCENDANT",
                authorization_call_phase="RAISED",
                authorization_exception_bucket="GATE_CONTROLLER_ERROR",
                package_transition_check_id="LV_EXECUTION_PACKAGE_ADAPTER",
                package_transition_check_count=1,
                package_transition_semantics="BLOCK",
                package_transition_phase="PRECONDITION",
                package_transition_reason_presence="ABSENT",
                package_dispatch_call_phase="RAISED",
                decision_to_package_bridge_id="PACKAGE_DISPATCH_PREP",
                decision_to_package_bridge_phase="BLOCKED",
                decision_to_package_bridge_semantics="BLOCK",
                decision_to_package_bridge_reason_presence="ABSENT",
                package_adapter_call_intent="NO",
                decision_to_package_bridge_step_count=2,
            )
            persisted = json.loads(runner.startup_failure_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["authorization_helper_id"],
                "VERIFY_SAME_RUN_GOVERNED_DESCENDANT",
            )
            self.assertEqual(persisted["authorization_entry_id"],
                             "AUTHORIZE_PRODUCTION_DESCENDANT")
            self.assertEqual(persisted["authorization_call_phase"], "RAISED")
            self.assertEqual(persisted["authorization_exception_bucket"],
                             "GATE_CONTROLLER_ERROR")
            self.assertEqual(persisted["package_transition_check_id"],
                             "LV_EXECUTION_PACKAGE_ADAPTER")
            self.assertEqual(persisted["package_transition_check_count"], 1)
            self.assertEqual(persisted["package_transition_semantics"], "BLOCK")
            self.assertEqual(persisted["package_transition_phase"], "PRECONDITION")
            self.assertEqual(persisted["package_transition_reason_presence"], "ABSENT")
            self.assertEqual(persisted["package_dispatch_call_phase"], "RAISED")
            self.assertEqual(persisted["decision_to_package_bridge_id"], "PACKAGE_DISPATCH_PREP")
            self.assertEqual(persisted["decision_to_package_bridge_phase"], "BLOCKED")
            self.assertEqual(persisted["decision_to_package_bridge_semantics"], "BLOCK")
            self.assertEqual(persisted["decision_to_package_bridge_reason_presence"], "ABSENT")
            self.assertEqual(persisted["package_adapter_call_intent"], "NO")

    def test_issue060_worker_verification_provenance_is_distinct_and_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            runner = self.runner(d); runner.ensure_started()
            runner.record_startup_failure(
                stage="PACKAGE_DISPATCH", category="RESUME_STATE_BLOCK",
                worker_verification_last_entered_step="DIFF_CHECK_EXECUTION",
                worker_verification_last_successful_step="DIFF_CHECK_EXECUTION",
                worker_verification_failure_step="FOCUSED_TEST_EXECUTION",
                worker_verification_failure_category="NONZERO_EXIT",
                worker_verification_exception_bucket="PROCESS",
            )
            persisted=json.loads(runner.startup_failure_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["stage"], "PACKAGE_DISPATCH")
            self.assertEqual(persisted["authorization_failure_source"], "UNKNOWN")
            self.assertEqual(persisted["worker_verification_failure_step"], "FOCUSED_TEST_EXECUTION")
            self.assertEqual(persisted["worker_verification_failure_category"], "NONZERO_EXIT")
            self.assertEqual(persisted["worker_verification_exception_bucket"], "PROCESS")

    def test_noncanonical_bridge_phase_is_rejected_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            runner = self.runner(d)
            runner.ensure_started()
            with self.assertRaises(ProductionGateRunnerError):
                runner.record_startup_failure(
                    stage="AUTHORIZATION", category="UNKNOWN",
                    decision_to_package_bridge_id="PACKAGE_DISPATCH_PREP",
                    decision_to_package_bridge_phase="DISPATCH_READY",
                    decision_to_package_bridge_semantics="BLOCK",
                    package_adapter_call_intent="NO",
                )
            self.assertFalse(runner.startup_failure_path.exists())

    def test_core_failure_record_survives_optional_diagnostic_schema_error(self):
        with tempfile.TemporaryDirectory() as d:
            runner = self.runner(d)
            runner.ensure_started()
            runner.record_startup_failure_core(
                stage="PACKAGE_DISPATCH", category="UNKNOWN",
            )
            with self.assertRaises(ProductionGateRunnerError):
                runner.record_startup_failure(
                    stage="PACKAGE_DISPATCH", category="UNKNOWN",
                    decision_to_package_bridge_id="PACKAGE_DISPATCH_PREP",
                    decision_to_package_bridge_phase="INVALID_PHASE",
                    decision_to_package_bridge_semantics="BLOCK",
                    package_adapter_call_intent="NO",
                )
            payload = json.loads(runner.startup_failure_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "PACKAGE_DISPATCH")
            self.assertEqual(payload["startup_failure_category"], "UNKNOWN")
            self.assertEqual(payload["startup_failure_status"], "BLOCK")
            self.assertEqual(payload["evidence_origin"], "TOP_LEVEL_BLOCK_FINALIZER")

    def test_core_failure_write_error_is_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            runner = self.runner(d)
            runner.ensure_started()
            with patch("runtime.orchestrator.production_gate_runner._atomic",
                       side_effect=OSError("fixture write failure")):
                with self.assertRaises(OSError):
                    runner.record_startup_failure_core(stage="UNKNOWN", category="UNKNOWN")
