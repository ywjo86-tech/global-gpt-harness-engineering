from __future__ import annotations
import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path

from runtime.orchestrator.runtime_migration_handoff import MigrationHandoffError,MigrationPhase,MigrationStore


def valid_spec():
    return {
        'migration_id':'MIG-001','project_id':'P','predecessor_run_id':'R2','successor_run_id':'R3',
        'current_gate':'TASK-014','resume_gate':'TASK-014',
        'approved_plan_sha256':'a'*64,'approved_spec_sha256':'b'*64,'authority_core_sha256':'c'*64,
        'predecessor_state_sha256':'d'*64,'source_head':'e'*40,
        'target_release_head':'f'*40,'target_manifest_sha256':'1'*64,
        'successor_job_spec_sha256':'2'*64,
    }

class RuntimeMigrationHandoffTests(unittest.TestCase):
    def store(self,root): return MigrationStore(Path(root)/'migrations')

    def test_allowed_phase_taxonomy_is_exact(self):
        self.assertEqual([p.value for p in MigrationPhase],[
            'PREPARED','PREDECESSOR_QUIESCED','RUNTIME_ACTIVATED','SUCCESSOR_REGISTERED',
            'SUCCESSOR_VERIFIED','PREDECESSOR_CLOSED','ROLLED_BACK','BLOCKED'])

    def test_duplicate_live_transaction_for_same_predecessor_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); s.create(valid_spec())
            second=valid_spec(); second['migration_id']='MIG-002'; second['successor_run_id']='R4'
            with self.assertRaisesRegex(MigrationHandoffError,'predecessor migration already exists'):
                s.create(second)

    def test_new_transaction_after_rollback_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); first=s.create(valid_spec()); s.rollback(first.migration_id,'retry safely')
            second=valid_spec(); second['migration_id']='MIG-002'; second['successor_run_id']='R4'
            self.assertEqual(s.create(second).migration_id,'MIG-002')

    def test_create_load_round_trip_and_digest_binding(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec()); loaded=s.load(tx.migration_id)
            self.assertEqual(loaded,tx); self.assertEqual(tx.phase,MigrationPhase.PREPARED)
            self.assertRegex(tx.transaction_sha256,r'^[0-9a-f]{64}$')

    def test_cannot_skip_from_prepared_to_runtime_activated(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec())
            with self.assertRaises(MigrationHandoffError): s.advance(tx.migration_id,MigrationPhase.RUNTIME_ACTIVATED)

    def test_forward_sequence_is_one_step_and_idempotent_load(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec())
            q=s.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED,updates={'quiesced_state_sha256':'3'*64})
            self.assertEqual(s.load(tx.migration_id),q); self.assertEqual(s.load(tx.migration_id),q)
            a=s.advance(tx.migration_id,MigrationPhase.RUNTIME_ACTIVATED)
            self.assertEqual(a.phase,MigrationPhase.RUNTIME_ACTIVATED)
            with self.assertRaises(MigrationHandoffError): s.advance(tx.migration_id,MigrationPhase.PREPARED)

    def test_quiesce_requires_write_once_state_sha(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec())
            with self.assertRaises(MigrationHandoffError):
                s.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED)

    def test_tampered_successor_digest_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec()); p=s.path(tx.migration_id)
            payload=json.loads(p.read_text()); payload['successor_job_spec_sha256']='0'*64; p.write_text(json.dumps(payload))
            with self.assertRaises(MigrationHandoffError): s.load(tx.migration_id)

    def test_unknown_create_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            spec=valid_spec(); spec['surprise']='x'
            with self.assertRaises(MigrationHandoffError): self.store(td).create(spec)

    def test_binding_identity_cannot_change(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec())
            with self.assertRaises(MigrationHandoffError): s.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED,updates={'successor_run_id':'R4'})

    def test_symlink_store_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); real=root/'real'; real.mkdir(); link=root/'link'; link.symlink_to(real,target_is_directory=True)
            with self.assertRaises(MigrationHandoffError): MigrationStore(link)

    def test_block_preserves_bindings_and_reason(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec()); blocked=s.block(tx.migration_id,'activation failed')
            self.assertEqual(blocked.phase,MigrationPhase.BLOCKED); self.assertEqual(blocked.block_reason,'activation failed')
            self.assertEqual(blocked.successor_run_id,tx.successor_run_id)

    def test_rollback_is_forbidden_after_predecessor_closed(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec())
            for phase in (MigrationPhase.PREDECESSOR_QUIESCED,MigrationPhase.RUNTIME_ACTIVATED,MigrationPhase.SUCCESSOR_REGISTERED,MigrationPhase.SUCCESSOR_VERIFIED,MigrationPhase.PREDECESSOR_CLOSED):
                tx=s.advance(tx.migration_id,phase,updates={'quiesced_state_sha256':'3'*64} if phase==MigrationPhase.PREDECESSOR_QUIESCED else None)
            with self.assertRaises(MigrationHandoffError): s.rollback(tx.migration_id,'too late')

    def test_successor_job_spec_is_sealed_and_verified_against_durable_state(self):
        from runtime.orchestrator.operator_plan_execution import build_operator_plan_job,seal_successor_operator_job_spec,verify_registered_successor
        from runtime.orchestrator.production_full_plan_entry import load_job,load_registered_job,register_job
        from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); subprocess.run(['git','init','-q',str(root)],check=True); subprocess.run(['git','-C',str(root),'config','user.email','t@example.com'],check=True); subprocess.run(['git','-C',str(root),'config','user.name','T'],check=True)
            spec=root/'spec.md'; plan=root/'plan.md'; spec.write_text('spec'); plan.write_text('plan'); subprocess.run(['git','-C',str(root),'add','.'],check=True); subprocess.run(['git','-C',str(root),'commit','-qm','base'],check=True)
            job=build_operator_plan_job(project_root=root,harness_root=root,runtime_code_root=root,project_id='P',run_id='R3',task_ids=('TASK-014','TASK-015'),approved_plan_path=plan,approved_spec_path=spec,approval_ref='approved')
            sealed=seal_successor_operator_job_spec(job,resume_gate='TASK-014'); self.assertRegex(sealed['successor_job_spec_sha256'],r'^[0-9a-f]{64}$')
            requested=root/'job.json'; requested.write_text(json.dumps(job)); canonical=register_job(load_job(requested)); registered=load_registered_job(canonical)
            sup=DurableFullPlanSupervisor(root,project_id='P',run_id='R3',gates=['TASK-014','TASK-015'],authority_core_sha256=registered['authority_core_sha256'],**registered['policy']); state,_=sup.load(); durable=sup._persist(state,{'event':'SUCCESSOR_REGISTERED_TEST'})
            evidence=verify_registered_successor(canonical,sealed); self.assertEqual(evidence['successor_state_sha256'],durable['state_sha256']); self.assertEqual(evidence['resume_gate'],'TASK-014')

    def test_successor_verification_rejects_digest_drift(self):
        from runtime.orchestrator.operator_plan_execution import build_operator_plan_job,seal_successor_operator_job_spec,verify_registered_successor,OperatorPlanExecutionError
        from runtime.orchestrator.production_full_plan_entry import load_job,load_registered_job,register_job
        from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); subprocess.run(['git','init','-q',str(root)],check=True); subprocess.run(['git','-C',str(root),'config','user.email','t@example.com'],check=True); subprocess.run(['git','-C',str(root),'config','user.name','T'],check=True)
            spec=root/'spec.md'; plan=root/'plan.md'; spec.write_text('spec'); plan.write_text('plan'); subprocess.run(['git','-C',str(root),'add','.'],check=True); subprocess.run(['git','-C',str(root),'commit','-qm','base'],check=True)
            job=build_operator_plan_job(project_root=root,harness_root=root,runtime_code_root=root,project_id='P',run_id='R3',task_ids=('TASK-014',),approved_plan_path=plan,approved_spec_path=spec,approval_ref='approved'); sealed=seal_successor_operator_job_spec(job,resume_gate='TASK-014')
            requested=root/'job.json'; requested.write_text(json.dumps(job)); canonical=register_job(load_job(requested)); registered=load_registered_job(canonical); sup=DurableFullPlanSupervisor(root,project_id='P',run_id='R3',gates=['TASK-014'],authority_core_sha256=registered['authority_core_sha256'],**registered['policy']); state,_=sup.load(); sup._persist(state,{'event':'SUCCESSOR_REGISTERED_TEST'})
            poisoned=dict(sealed); poisoned['approved_plan_sha256']='0'*64
            with self.assertRaises(OperatorPlanExecutionError): verify_registered_successor(canonical,poisoned)

    def test_restart_reloads_same_transaction_at_every_crash_phase(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); store=MigrationStore(root/'migrations'); tx=store.create(valid_spec())
            observed=[tx.phase]
            tx=store.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED,updates={'quiesced_state_sha256':'3'*64}); observed.append(tx.phase)
            for phase in (MigrationPhase.RUNTIME_ACTIVATED,MigrationPhase.SUCCESSOR_REGISTERED,MigrationPhase.SUCCESSOR_VERIFIED,MigrationPhase.PREDECESSOR_CLOSED):
                tx=MigrationStore(root/'migrations').advance(tx.migration_id,phase); observed.append(tx.phase)
                reloaded=MigrationStore(root/'migrations').load(tx.migration_id)
                self.assertEqual(reloaded.transaction_sha256,tx.transaction_sha256); self.assertEqual(reloaded.phase,phase)
            self.assertEqual(observed,[MigrationPhase.PREPARED,MigrationPhase.PREDECESSOR_QUIESCED,MigrationPhase.RUNTIME_ACTIVATED,MigrationPhase.SUCCESSOR_REGISTERED,MigrationPhase.SUCCESSOR_VERIFIED,MigrationPhase.PREDECESSOR_CLOSED])

    def test_arbitrary_successor_run_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            spec=valid_spec(); spec['successor_run_id']='../escape'
            with self.assertRaises(MigrationHandoffError): MigrationStore(Path(td)/'migrations').create(spec)

    def test_rollback_before_close_preserves_authority_bindings(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec()); tx=s.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED,updates={'quiesced_state_sha256':'3'*64})
            rb=s.rollback(tx.migration_id,'activation aborted')
            self.assertEqual(rb.phase,MigrationPhase.ROLLED_BACK); self.assertEqual(rb.approved_plan_sha256,'a'*64)

if __name__=='__main__': unittest.main()

class RuntimeMigrationSupervisorIntegrationTests(unittest.TestCase):
    def test_quiesce_keeps_predecessor_nonterminal_and_binds_successor(self):
        from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
        with tempfile.TemporaryDirectory() as td:
            sup=DurableFullPlanSupervisor(td,project_id='P',run_id='R2',gates=['G1'])
            before,_=sup.load()
            state=sup.quiesce_for_runtime_migration('M1','R3')
            self.assertEqual(state['state'],'WAITING_RESOURCE')
            self.assertEqual(state['last_error'],'RUNTIME_MIGRATION_QUIESCED')
            self.assertEqual(state['migration_handoff'],{'migration_id':'M1','successor_run_id':'R3'})
            self.assertIsNone(state['lease'])
            self.assertNotEqual(state['state'],'CANCELLED')
            self.assertNotEqual(before['state_sha256'],state['state_sha256'])

    def test_close_migrated_predecessor_requires_verified_successor_binding(self):
        from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor,ProductionFullPlanError
        with tempfile.TemporaryDirectory() as td:
            sup=DurableFullPlanSupervisor(td,project_id='P',run_id='R2',gates=['G1'])
            sup.quiesce_for_runtime_migration('M1','R3')
            with self.assertRaises(ProductionFullPlanError):
                sup.close_migrated_predecessor('WRONG','3'*64)
            sup.record_verified_migration_successor('M1','R3','3'*64)
            state=sup.close_migrated_predecessor('M1','3'*64)
            self.assertEqual(state['state'],'CANCELLED')
            self.assertEqual(state['terminal_reason'],'MIGRATED_TO_SUCCESSOR')
            self.assertEqual(state['migration_handoff']['successor_state_sha256'],'3'*64)
