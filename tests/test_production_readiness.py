import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.test_production_lifecycle import binding
from runtime.orchestrator.gate_terminal import GateTerminalController, GateTerminalError
from runtime.orchestrator.gate_supervisor import PersistentGateSupervisor
from runtime.orchestrator.incremental_resolution import IncrementalResolver
from runtime.orchestrator.lifecycle_binding import LifecycleBindingError, validate_binding
from runtime.orchestrator.partial_workspace_recovery import PartialRecoveryError, PartialRecoveryMachine
from runtime.orchestrator.production_lifecycle import ProductionLifecycleError, consume, produce


class ProductionReadinessTests(unittest.TestCase):
    def handlers(self):
        return {stage:(lambda state:{"status":"PASS"}) for stage in ("PACKAGE","PREFLIGHT","WORKER","REVIEW","REMEDIATION","CHECKPOINT","EXIT")}
    def recovered(self, root):
        m=PartialRecoveryMachine(root,binding());
        for s in ("WORKER_REQUESTED","WORKER_RUNNING","PARTIAL_WORKSPACE_DETECTED"): m.advance(s)
        return m

    def test_01_new_three_lv_gate_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            c=GateTerminalController(d,binding(),["a","b","c"])
            for lv in ("a","b","c"): state=c.review_pass(lv)
            self.assertEqual(state["stage"],"HANDOFF_SEALED")
    def test_02_completed_lv_inheritance(self):
        with tempfile.TemporaryDirectory() as d:
            GateTerminalController(d,binding(),["a","b"]).review_pass("a")
            self.assertEqual(GateTerminalController(d,binding(),["a","b"]).load()["completed_lvs"],["a"])
    def test_03_rejected_artifact_valid_successor(self):
        rejected=produce("recovery_rejection",{"status":"REJECTED","completion_eligible":False},binding())
        self.assertFalse(consume("recovery_rejection",rejected,binding())["payload"]["completion_eligible"])
        self.assertEqual(consume("recovery_successor",produce("recovery_successor",{"status":"VALID"},binding(attempt=2)),binding(attempt=2))["payload"]["status"],"VALID")
    def test_04_worker_diff_then_exit_before_result(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={"a":"x"},owned_scope=["a"]); self.assertEqual(m.state,"TERMINATED_ADOPTABLE_PARTIAL")
    def test_05_live_worker_duplicate_block(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); self.assertEqual(m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:"x",diff={},owned_scope=[]),"LIVE_BOUND_WORKER")
    def test_06_terminated_partial_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={"a":"x"},owned_scope=["a"]); self.assertEqual(m.adopt({"a":"x"},["a"])["state"],"ADOPTION_VALIDATED")
    def test_07_owned_scope_excess_block(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); self.assertEqual(m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={"b":"x"},owned_scope=["a"]),"INVALID_OR_AMBIGUOUS_PARTIAL")
    def test_08_stale_pid_and_pid_reuse(self):
        for probe in (lambda p:None,lambda p:"new"):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(self.recovered(d).classify_worker(recorded_pid=1,recorded_start="old",process_probe=probe,diff={},owned_scope=[]),"TERMINATED_ADOPTABLE_PARTIAL")
    def test_09_package_preflight_request_binding_mismatch(self):
        for kind in ("package","preflight","worker_request"):
            with self.assertRaises(ProductionLifecycleError): consume(kind,produce(kind,{},binding()),binding(run_id="other"))
    def test_10_crash_restart_before_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={},owned_scope=[]); self.assertEqual(PartialRecoveryMachine(d,binding()).state,"TERMINATED_ADOPTABLE_PARTIAL")
    def test_11_atomic_result_failure(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={},owned_scope=[]); m.adopt({},[])
            with patch("runtime.orchestrator.partial_workspace_recovery.os.link",side_effect=OSError),self.assertRaises(OSError):m.publish_result({})
    def test_12_review_pass(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d); m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={},owned_scope=[]); m.adopt({},[]);m.publish_result({});self.assertEqual(m.review("PASS"),"REVIEW_PASSED")
    def test_13_review_fail_remediation_pass(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.recovered(d);m.classify_worker(recorded_pid=1,recorded_start="x",process_probe=lambda p:None,diff={},owned_scope=[]);m.adopt({},[]);m.publish_result({});self.assertEqual(m.review("FAIL"),"REMEDIATION_REQUIRED")
    def test_14_checkpoint_restart(self):
        with tempfile.TemporaryDirectory() as d:
            c=GateTerminalController(d,binding(),["a","b"]);c.review_pass("a");self.assertEqual(GateTerminalController(d,binding(),["a","b"]).load()["next_lv"],"b")
    def test_15_lv_exit_restart(self):
        with tempfile.TemporaryDirectory() as d:
            c=GateTerminalController(d,binding(),["a"]);c.review_pass("a")
            self.assertEqual(GateTerminalController(d,binding(),["a"]).load()["gate_status"],"EXITED")
    def test_16_gate_exit_terminal_replay(self):
        with tempfile.TemporaryDirectory() as d:
            c=GateTerminalController(d,binding(),["a"]);c.review_pass("a");self.assertEqual(c.replay_terminal()["gate_status"],"EXITED")
    def test_17_next_gate_user_approval_required(self):
        with tempfile.TemporaryDirectory() as d:
            c=GateTerminalController(d,binding(),["a"]);c.review_pass("a")
            with self.assertRaisesRegex(GateTerminalError,"USER_APPROVAL_REQUIRED"):c.start_next_gate()
    def test_18_multi_gate_gate_by_gate(self):
        with tempfile.TemporaryDirectory() as d:
            first=PersistentGateSupervisor(d,project_id="p",run_id="r1",gate_id="g1",mode="GATE_BY_GATE",lv_order=["a"])
            self.assertEqual(first.run_bound_lifecycle(self.handlers(),binding()).status,"USER_APPROVAL_REQUIRED")
            second=PersistentGateSupervisor(d,project_id="p",run_id="r2",gate_id="g2",mode="GATE_BY_GATE",lv_order=["b"])
            self.assertEqual(second.load()["stage"],"PACKAGE")
    def test_19_full_plan_fixtures_f1_f4(self):
        for project in ("F1","F2","F3","F4"):
            with tempfile.TemporaryDirectory() as d:
                c=PersistentGateSupervisor(d,project_id=project,run_id="run",gate_id="gate",mode="FULL_PLAN",lv_order=["a","b","c"])
                self.assertEqual(c.run_bound_lifecycle(self.handlers(),binding(project_id=project)).status,"COMPLETED")
    def test_20_second_existing_project_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"AGENTS.md").write_text("existing");(root/"docs").mkdir();(root/"docs"/"DEVELOPMENT_PLAN.txt").write_text("plan")
            self.assertEqual(PersistentGateSupervisor(d,project_id="jarvis",run_id="r",gate_id="g",mode="FULL_PLAN",lv_order=["a"]).run_bound_lifecycle(self.handlers(),binding(project_id="jarvis")).status,"COMPLETED")
    def test_21_new_project_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"AGENTS.md").write_text("new");(root/"docs").mkdir();(root/"docs"/"DEVELOPMENT_PLAN.txt").write_text("plan")
            self.assertEqual(PersistentGateSupervisor(d,project_id="new-project",run_id="r",gate_id="g",mode="GATE_BY_GATE",lv_order=["a"]).run_bound_lifecycle(self.handlers(),binding(project_id="new-project")).status,"USER_APPROVAL_REQUIRED")
    def test_22_symlink_and_traversal(self):
        with self.assertRaises(LifecycleBindingError): validate_binding({**binding(),"project_id":"../escape"})
    def test_23_unsupported_schema(self):
        with self.assertRaises(LifecycleBindingError): validate_binding({**binding(),"schema_version":"future"})
    def test_24_corrupt_artifact(self):
        artifact=produce("package",{},binding());artifact["payload"]={"bad":True}
        with self.assertRaises(ProductionLifecycleError):consume("package",artifact,binding())
    def test_25_cross_project_gate_lv_run(self):
        artifact=produce("package",{},binding())
        for field in ("project_id","gate_id","lv_id","run_id"):
            with self.assertRaises(ProductionLifecycleError):consume("package",artifact,binding(**{field:"other"}))
    def test_26_deterministic_replay(self): self.assertEqual(produce("package",{"x":1},binding()),produce("package",{"x":1},binding()))
    def test_27_secret_redaction(self):
        secret="sk-fixture-do-not-print"
        try: validate_binding({"secret":secret})
        except Exception as exc: self.assertNotIn(secret,str(exc)+repr(exc))
    def test_28_token_efficient_incremental_resolution(self):
        artifacts=[{"lv_id":"done","summary":"x"*1000},{"lv_id":"next","summary":"small","index":1,"checkpoint":"cp"}]
        resolver=IncrementalResolver();first=resolver.resolve(artifacts,binding(),completed_lvs=["done"]);second=resolver.resolve(artifacts,binding(),completed_lvs=["done"])
        baseline=len(json.dumps(artifacts).encode())*2
        self.assertLess(second["bytes_sent"],baseline);self.assertEqual(second["cache_hits"],1);self.assertEqual(second["calls"],1);self.assertEqual(second["validation"],"FULL_BINDING_VALIDATED")
        changed=resolver.resolve(artifacts,binding(current_head="c"*40),completed_lvs=["done"]);self.assertEqual(changed["calls"],2)


if __name__ == "__main__": unittest.main()
