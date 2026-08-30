import json, tempfile, unittest
from pathlib import Path
from runtime.orchestrator.recovery_contract import RecoveryError, write_recovery_record, classify_partial_attempt, prepare_partial_recovery, execute_recovery_attempt

class RecoveryContractTests(unittest.TestCase):
    def test_attempt_two_package_preflight_worker_path_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); run=root/'_workspace'/'orchestration-runs'/'run-1'; run.mkdir(parents=True)
            manifest={'project_id':'p','gate_id':'g','lv_id':'l','run_id':'run-1','canonical_plan_sha256':'a'*64}
            worker1={'gate_id':'g','lv_id':'l','run_id':'run-1','attempt':1,'status':'completed'}
            transition={'project_id':'p','gate_id':'g','lv_id':'l','run_id':'run-1','branch':'main','baseline_head':'b'*40,'current_head':'c'*40}
            paths=[]
            for name,value in [('package.manifest.json',manifest),('worker.result.json',worker1),('transition.json',transition)]:
                path=run/name; path.write_text(json.dumps(value)); paths.append(path)
            before=[path.read_bytes() for path in paths]
            prepared=prepare_partial_recovery(root,manifest_path=paths[0],worker_path=paths[1],transition_path=paths[2],approval_event_id='APR-1')
            recovery_root=root/'_workspace'/'global-gate'/'p'/'recovery'
            args=dict(recovery_record_path=recovery_root/'run-1-recovery-02.json',recovery_checkpoint_path=recovery_root/'run-1-recovery-02.checkpoint.json')
            calls=[]
            def worker(package,preflight):
                calls.append((package,preflight)); return {'status':'completed','changed_files':['x.py']}
            first=execute_recovery_attempt(root,worker=worker,**args)
            second=execute_recovery_attempt(root,worker=lambda *_: self.fail('worker reran'),**args)
            self.assertEqual(first,second); self.assertEqual(len(calls),1)
            self.assertEqual(first['worker_result']['attempt'],2)
            self.assertEqual(first['worker_result']['run_id'],'run-1')
            self.assertEqual(before,[path.read_bytes() for path in paths])

    def test_controller_prepares_and_replays_rejected_legacy_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); run=root/'_workspace'/'orchestration-runs'/'run-1'; run.mkdir(parents=True)
            manifest={'project_id':'p','gate_id':'g','lv_id':'l','run_id':'run-1','canonical_plan_sha256':'a'*64}
            worker={'gate_id':'g','lv_id':'l','run_id':'run-1','attempt':1,'status':'completed'}
            transition={'project_id':'p','gate_id':'g','lv_id':'l','run_id':'run-1','branch':'main','baseline_head':'b'*40,'current_head':'c'*40}
            paths=[]
            for name,value in [('package.manifest.json',manifest),('worker.result.json',worker),('transition.json',transition)]:
                path=run/name; path.write_text(json.dumps(value)); paths.append(path)
            before=[path.read_bytes() for path in paths]
            args=dict(manifest_path=paths[0],worker_path=paths[1],transition_path=paths[2],approval_event_id='APR-1')
            first=prepare_partial_recovery(root,**args); second=prepare_partial_recovery(root,**args)
            self.assertEqual(first,second); self.assertEqual(first['next_attempt'],2)
            self.assertEqual(first['classification']['status'],'REJECTED_UNBOUND_LEGACY')
            self.assertEqual(first['completion_evidence'],[])
            self.assertEqual(before,[path.read_bytes() for path in paths])
    def test_append_only_replay(self):
        with tempfile.TemporaryDirectory() as d:
            kw=dict(project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,rejected_artifacts={'a.json':'a'*64},reason_code='REJECTED_UNBOUND_LEGACY',missing_bindings=['project_id'],recovery_attempt=2,approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,current_head='d'*40,active_transition_sha256='f'*64,source_shas={'a.json':'a'*64},predecessor=None,supersedes='old')
            first=write_recovery_record(d,**kw); second=write_recovery_record(d,**kw)
            self.assertEqual(first,second); self.assertEqual(first['hard_stop'],True)
    def test_traversal_rejected(self):
        with self.assertRaises(RecoveryError):
            write_recovery_record(tempfile.mkdtemp(),project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,rejected_artifacts={'../x':'a'*64},reason_code='x',missing_bindings=[],recovery_attempt=2,approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,current_head='d'*40,active_transition_sha256='f'*64,source_shas={},predecessor=None,supersedes='old')

    def test_unbound_partial_is_not_completion(self):
        result = classify_partial_attempt({"project_id":"p"}, {"status":"completed"})
        self.assertEqual(result["status"], "REJECTED_UNBOUND_LEGACY")
        self.assertFalse(result["completion_eligible"])
