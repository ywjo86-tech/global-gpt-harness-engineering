import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.recovery_contract import (
    RecoveryError,
    execute_recovery_attempt,
    finalize_recovery_lifecycle,
    prepare_partial_recovery,
    review_recovery_attempt,
)


class RecoveryLifecycleE2ETests(unittest.TestCase):
    """Required 11-scenario fault, restart, replay, and lifecycle matrix."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        run = self.root / "_workspace" / "orchestration-runs" / "run-1"
        run.mkdir(parents=True)
        values = {
            "package.manifest.json": {"project_id":"p","gate_id":"g","lv_id":"l","run_id":"run-1","canonical_plan_sha256":"a"*64},
            "worker.result.json": {"gate_id":"g","lv_id":"l","run_id":"run-1","attempt":1,"status":"completed"},
            "transition.json": {"project_id":"p","gate_id":"g","lv_id":"l","run_id":"run-1","branch":"main","baseline_head":"b"*40,"current_head":"c"*40},
        }
        self.sources = []
        for name, value in values.items():
            path = run / name; path.write_text(json.dumps(value)); self.sources.append(path)
        self.prepare_args = {"manifest_path":self.sources[0],"worker_path":self.sources[1],"transition_path":self.sources[2],"approval_event_id":"APR-1"}
        recovery = self.root / "_workspace" / "global-gate" / "p" / "recovery"
        self.control = {"recovery_record_path":recovery/"run-1-recovery-02.json","recovery_checkpoint_path":recovery/"run-1-recovery-02.checkpoint.json"}

    def tearDown(self): self.tmp.cleanup()
    def prepare(self): return prepare_partial_recovery(self.root, **self.prepare_args)
    def execute(self, status="completed"):
        return execute_recovery_attempt(self.root, worker=lambda *_:{"status":status}, **self.control)
    def review(self, verdict="PASS"):
        return review_recovery_attempt(self.root, reviewer=lambda *_:{"verdict":verdict}, **self.control)
    def attempt(self): return self.root/"_workspace"/"orchestration-runs"/"run-1"/"attempt-02"

    def test_e2e_01_partial_gate_happy_path(self):
        self.prepare(); self.execute(); self.review()
        out=finalize_recovery_lifecycle(self.root,run_id="run-1",remaining_lvs=["l2"],gate_complete=False)
        self.assertEqual(out["handoff"]["next_lv"],"l2"); self.assertIsNone(out["gate_exit"])

    def test_e2e_02_complete_gate_requires_next_gate_approval(self):
        self.prepare(); self.execute(); self.review()
        out=finalize_recovery_lifecycle(self.root,run_id="run-1",remaining_lvs=[],gate_complete=True)
        self.assertEqual(out["gate_exit"]["next_gate_status"],"USER_APPROVAL_REQUIRED")

    def test_e2e_03_prepare_restart_is_idempotent(self):
        before=[p.read_bytes() for p in self.sources]; self.assertEqual(self.prepare(),self.prepare())
        self.assertEqual(before,[p.read_bytes() for p in self.sources])

    def test_e2e_04_worker_restart_does_not_rerun(self):
        self.prepare(); calls=[]
        first=execute_recovery_attempt(self.root,worker=lambda *_:(calls.append(1) or {"status":"completed"}),**self.control)
        second=execute_recovery_attempt(self.root,worker=lambda *_:self.fail("worker reran"),**self.control)
        self.assertEqual(first,second); self.assertEqual(calls,[1])

    def test_e2e_05_review_restart_does_not_rerun(self):
        self.prepare(); self.execute(); calls=[]
        first=review_recovery_attempt(self.root,reviewer=lambda *_:(calls.append(1) or {"verdict":"PASS"}),**self.control)
        second=review_recovery_attempt(self.root,reviewer=lambda *_:self.fail("review reran"),**self.control)
        self.assertEqual(first,second); self.assertEqual(calls,[1])

    def test_e2e_06_finalize_restart_is_idempotent(self):
        self.prepare(); self.execute(); self.review()
        args={"run_id":"run-1","remaining_lvs":["l2"],"gate_complete":False}
        self.assertEqual(finalize_recovery_lifecycle(self.root,**args),finalize_recovery_lifecycle(self.root,**args))

    def test_e2e_07_failed_review_is_not_consumed(self):
        self.prepare(); self.execute("failed"); out=self.review("FAIL")
        self.assertIsNone(out["consumption"])
        with self.assertRaisesRegex(RecoveryError,"consumption"):
            finalize_recovery_lifecycle(self.root,run_id="run-1",remaining_lvs=["l2"],gate_complete=False)

    def test_e2e_08_package_fault_is_detected(self):
        self.prepare(); self.execute(); path=self.attempt()/"package.json"
        value=json.loads(path.read_text()); value["project_id"]="other"; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RecoveryError,"binding mismatch"): self.review()

    def test_e2e_09_preflight_fault_is_detected(self):
        self.prepare(); self.execute(); path=self.attempt()/"preflight.json"
        value=json.loads(path.read_text()); value["package_sha256"]="0"*64; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RecoveryError,"preflight lineage"): self.review()

    def test_e2e_10_worker_fault_is_detected(self):
        self.prepare(); self.execute(); path=self.attempt()/"worker.result.json"
        value=json.loads(path.read_text()); value["preflight_sha256"]="0"*64; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RecoveryError,"worker lineage"): self.review()

    def test_e2e_11_gate_completeness_fault_is_detected(self):
        self.prepare(); self.execute(); self.review()
        with self.assertRaisesRegex(RecoveryError,"completeness"):
            finalize_recovery_lifecycle(self.root,run_id="run-1",remaining_lvs=[],gate_complete=False)
