import json, tempfile, unittest
from pathlib import Path
from runtime.orchestrator.recovery_contract import RecoveryError, write_recovery_record, write_provenance_rejection, classify_partial_attempt, prepare_partial_recovery, prepare_completion_recovery, execute_recovery_attempt, is_completion_eligible, canonical_recovery_binding, review_recovery_attempt, finalize_recovery_lifecycle
from runtime.orchestrator.production_completion import write_completion_rejection

class RecoveryContractTests(unittest.TestCase):
    def test_provenance_rejection_is_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            kwargs = dict(
                project_id="p", run_id="r", gate_id="g", lv_id="l",
                schema_version="orchestration.lv_preflight.evidence.v1",
                package_sha256="a" * 64, source_preflight_sha256="b" * 64,
                invalid_payload_sha256="c" * 64,
                invalid_sidecar_expected_sha256="d" * 64,
                invalid_sidecar_file_sha256="e" * 64,
                predecessor="f" * 64, provenance_audit_ref="audit-1",
                reason_code="REJECTED_DERIVED_ATTESTATION_INVALID_FROM_CREATION",
                validator_version="v1", attempt=1, recovery_id="r-recovery-01",
            )
            first = write_provenance_rejection(directory, **kwargs)
            second = write_provenance_rejection(directory, **kwargs)
            self.assertEqual(first, second)
            self.assertFalse(first["completion_eligible"])
            path = Path(directory) / "_workspace" / "global-gate" / "p" / "recovery" / "r-provenance-rejection-l.json"
            before = path.read_bytes()
            with self.assertRaisesRegex(RecoveryError, "replay conflict"):
                write_provenance_rejection(directory, **{**kwargs, "invalid_payload_sha256": "0" * 64})
            self.assertEqual(path.read_bytes(), before)

    def test_provenance_rejection_rejects_invalid_digest_or_identity(self):
        kwargs = dict(project_id="p", run_id="r", gate_id="g", lv_id="l",
                      schema_version="v1", package_sha256="a" * 64,
                      source_preflight_sha256="b" * 64, invalid_payload_sha256="c" * 64,
                      invalid_sidecar_expected_sha256="d" * 64,
                      invalid_sidecar_file_sha256="e" * 64, predecessor=None,
                      provenance_audit_ref="audit-1", reason_code="REJECTED_BAD",
                      validator_version="v1")
        with self.assertRaises(RecoveryError):
            write_provenance_rejection(tempfile.mkdtemp(), **{**kwargs, "package_sha256": "bad"})
        with self.assertRaises(RecoveryError):
            write_provenance_rejection(tempfile.mkdtemp(), **{**kwargs, "project_id": "../escape"})

    def test_provenance_rejection_rejects_staging_destination_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "orchestration-preflights" / "run"
            kwargs = dict(project_id="p", run_id="r", gate_id="g", lv_id="l",
                          schema_version="v1", package_sha256="a" * 64,
                          source_preflight_sha256="b" * 64, invalid_payload_sha256="c" * 64,
                          invalid_sidecar_expected_sha256="d" * 64,
                          invalid_sidecar_file_sha256="e" * 64, predecessor=None,
                          provenance_audit_ref="audit-1", reason_code="REJECTED_BAD",
                          validator_version="v1")
            with self.assertRaisesRegex(RecoveryError, "noncanonical"):
                write_provenance_rejection(staging, **kwargs)
            self.assertFalse(staging.exists())

    def test_finalization_connects_checkpoint_exit_next_lv_and_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); args,_=self._prepared_attempt_two(root)
            review_recovery_attempt(root,reviewer=lambda *_:{'verdict':'PASS'},**args)
            first=finalize_recovery_lifecycle(root,run_id='run-1',remaining_lvs=['l2'],gate_complete=False)
            second=finalize_recovery_lifecycle(root,run_id='run-1',remaining_lvs=['l2'],gate_complete=False)
            self.assertEqual(first,second); self.assertEqual(first['handoff']['next_lv'],'l2')
            self.assertIsNone(first['gate_exit'])
            with self.assertRaisesRegex(RecoveryError,'completeness'):
                finalize_recovery_lifecycle(root,run_id='run-1',remaining_lvs=[],gate_complete=False)
    def _prepared_attempt_two(self, root):
        run=root/'_workspace'/'orchestration-runs'/'run-1'; run.mkdir(parents=True)
        values=[('package.manifest.json',{'project_id':'p','gate_id':'g','lv_id':'l','run_id':'run-1','canonical_plan_sha256':'a'*64}),('worker.result.json',{'gate_id':'g','lv_id':'l','run_id':'run-1','attempt':1,'status':'completed'}),('transition.json',{'project_id':'p','gate_id':'g','lv_id':'l','run_id':'run-1','branch':'main','baseline_head':'b'*40,'current_head':'c'*40})]
        paths=[]
        for name,value in values:
            path=run/name; path.write_text(json.dumps(value)); paths.append(path)
        prepare_partial_recovery(root,manifest_path=paths[0],worker_path=paths[1],transition_path=paths[2],approval_event_id='APR-1')
        recovery=root/'_workspace'/'global-gate'/'p'/'recovery'
        args={'recovery_record_path':recovery/'run-1-recovery-02.json','recovery_checkpoint_path':recovery/'run-1-recovery-02.checkpoint.json'}
        execute_recovery_attempt(root,worker=lambda *_:{'status':'completed'},**args)
        return args,paths

    def test_review_validates_and_consumes_attempt_two_recovery_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); args,sources=self._prepared_attempt_two(root); before=[p.read_bytes() for p in sources]
            calls=[]
            reviewer=lambda worker,binding: (calls.append((worker,binding)) or {'verdict':'PASS','findings':[]})
            first=review_recovery_attempt(root,reviewer=reviewer,**args)
            second=review_recovery_attempt(root,reviewer=lambda *_:self.fail('review reran'),**args)
            self.assertEqual(first,second); self.assertEqual(len(calls),1)
            self.assertEqual(first['consumption']['status'],'CONSUMED')
            self.assertEqual(first['review']['attempt'],2)
            self.assertEqual(before,[p.read_bytes() for p in sources])
    def test_canonical_binding_covers_project_plan_approval_transition_and_hard_stop(self):
        record={'project_id':'p','gate_id':'g','lv_id':'l','run_id':'r','recovery_id':'r-recovery-02',
                'recovery_attempt':2,'plan_sha256':'a'*64,'approval_event_id':'APR-1',
                'active_transition_sha256':'b'*64,'record_hash':'c'*64,'hard_stop':True}
        checkpoint={'project_id':'p','gate_id':'g','lv_id':'l','run_id':'r','recovery_id':'r-recovery-02',
                    'next_attempt':2,'checkpoint_sha256':'d'*64,'hard_stop':True}
        binding=canonical_recovery_binding(record,checkpoint)
        self.assertEqual(binding['canonical_plan_sha256'],'a'*64)
        self.assertEqual(binding['approval_event_id'],'APR-1')
        self.assertEqual(binding['active_transition_sha256'],'b'*64)
        self.assertTrue(binding['hard_stop'])
        with self.assertRaisesRegex(RecoveryError,'binding mismatch'):
            canonical_recovery_binding(record,{**checkpoint,'project_id':'other'})
    def test_completion_eligibility_rejects_explicit_and_unbound_legacy(self):
        manifest={'project_id':'p','canonical_plan_sha256':'a'*64,'hard_stop':True}
        self.assertFalse(is_completion_eligible({'status':'REJECTED_UNBOUND_LEGACY'}))
        self.assertFalse(is_completion_eligible({'status':'completed','completion_eligible':False}))
        self.assertFalse(is_completion_eligible({'status':'completed','attempt':1},manifest=manifest))
        self.assertTrue(is_completion_eligible({'status':'completed'}))
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
    def test_completion_rejection_advances_to_attempt_three_and_replays(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            prior=write_recovery_record(root,project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,
                rejected_artifacts={'legacy.json':'a'*64},reason_code='REJECTED_UNBOUND_LEGACY',missing_bindings=['project_id'],
                recovery_attempt=2,approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,
                current_head='d'*40,active_transition_sha256='f'*64,source_shas={'legacy.json':'a'*64},predecessor=None,supersedes='old')
            rejection=write_completion_rejection(root,project_id='p',gate_id='g',lv_id='l',run_id='r',attempt=2,
                reasons=['CHECKPOINT_COMMIT_MISSING'],source_shas={'attempt-02/worker.result.json':'a'*64},next_attempt=3)
            recovery=root/'_workspace'/'global-gate'/'p'/'recovery'
            args=dict(prior_record_path=recovery/'r-recovery-02.json',rejection_path=recovery/'r-attempt-02-completion-rejection.json')
            first=prepare_completion_recovery(root,**args); second=prepare_completion_recovery(root,**args)
            self.assertEqual(first,second); self.assertEqual(first['next_attempt'],3)
            self.assertEqual(first['recovery']['predecessor'],prior['record_hash'])
            calls=[]
            controls=dict(recovery_record_path=recovery/'r-recovery-03.json',recovery_checkpoint_path=recovery/'r-recovery-03.checkpoint.json')
            executed=execute_recovery_attempt(root,worker=lambda *_:(calls.append(1) or {'status':'completed'}),**controls)
            replay=execute_recovery_attempt(root,worker=lambda *_:self.fail('worker reran'),**controls)
            self.assertEqual(executed,replay); self.assertEqual(calls,[1]); self.assertEqual(executed['worker_result']['attempt'],3)
            self.assertEqual(rejection, json.loads(args['rejection_path'].read_text(encoding='utf-8')))
    def test_recovery_record_rejects_attempt_gap(self):
        with self.assertRaisesRegex(RecoveryError,'invalid recovery attempt'):
            write_recovery_record(tempfile.mkdtemp(),project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,
                rejected_artifacts={'a.json':'a'*64},reason_code='x',missing_bindings=[],recovery_attempt=3,
                approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,current_head='d'*40,
                active_transition_sha256='f'*64,source_shas={},predecessor=None,supersedes='old')
    def test_traversal_rejected(self):
        with self.assertRaises(RecoveryError):
            write_recovery_record(tempfile.mkdtemp(),project_id='p',gate_id='g',lv_id='l',run_id='r',rejected_attempt=1,rejected_artifacts={'../x':'a'*64},reason_code='x',missing_bindings=[],recovery_attempt=2,approval_event_id='e',plan_sha256='b'*64,branch='main',baseline_head='c'*40,current_head='d'*40,active_transition_sha256='f'*64,source_shas={},predecessor=None,supersedes='old')

    def test_unbound_partial_is_not_completion(self):
        result = classify_partial_attempt({"project_id":"p"}, {"status":"completed"})
        self.assertEqual(result["status"], "REJECTED_UNBOUND_LEGACY")
        self.assertFalse(result["completion_eligible"])
