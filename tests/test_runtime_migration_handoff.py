from __future__ import annotations
import json,tempfile,unittest
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
            q=s.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED)
            self.assertEqual(s.load(tx.migration_id),q); self.assertEqual(s.load(tx.migration_id),q)
            a=s.advance(tx.migration_id,MigrationPhase.RUNTIME_ACTIVATED)
            self.assertEqual(a.phase,MigrationPhase.RUNTIME_ACTIVATED)
            with self.assertRaises(MigrationHandoffError): s.advance(tx.migration_id,MigrationPhase.PREPARED)

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
                tx=s.advance(tx.migration_id,phase)
            with self.assertRaises(MigrationHandoffError): s.rollback(tx.migration_id,'too late')

    def test_rollback_before_close_preserves_authority_bindings(self):
        with tempfile.TemporaryDirectory() as td:
            s=self.store(td); tx=s.create(valid_spec()); tx=s.advance(tx.migration_id,MigrationPhase.PREDECESSOR_QUIESCED)
            rb=s.rollback(tx.migration_id,'activation aborted')
            self.assertEqual(rb.phase,MigrationPhase.ROLLED_BACK); self.assertEqual(rb.approved_plan_sha256,'a'*64)

if __name__=='__main__': unittest.main()
