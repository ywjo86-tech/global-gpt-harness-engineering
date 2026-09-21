from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.remote_operator_ingress import advance_migration_if_current
from runtime.orchestrator.runtime_migration_handoff import (
    MigrationHandoffError,
    MigrationPhase,
    MigrationStore,
)


def valid_v2_spec():
    return {
        "migration_id": "MIG-001",
        "project_id": "P",
        "predecessor_run_id": "R1",
        "successor_run_id": "R2",
        "current_gate": "C1",
        "resume_gate": "C2",
        "approved_plan_sha256": "a" * 64,
        "approved_spec_sha256": "b" * 64,
        "authority_core_sha256": "c" * 64,
        "predecessor_state_sha256": "d" * 64,
        "source_head": "e" * 40,
        "target_release_head": "f" * 40,
        "target_manifest_sha256": "1" * 64,
        "successor_job_spec_sha256": "2" * 64,
        "source_tree": "4" * 40,
        "source_manifest_sha256": "5" * 64,
    }


def advance_to_successor_verified(store: MigrationStore):
    tx = store.create_v2(valid_v2_spec())
    tx = store.advance(
        tx.migration_id,
        MigrationPhase.PREDECESSOR_QUIESCED,
        updates={"quiesced_state_sha256": "3" * 64},
    )
    for phase in (
        MigrationPhase.RUNTIME_ACTIVATED,
        MigrationPhase.SUCCESSOR_REGISTERED,
        MigrationPhase.SUCCESSOR_VERIFIED,
    ):
        tx = store.advance(tx.migration_id, phase)
    return tx


def advance_to_qualified(store: MigrationStore):
    tx = advance_to_successor_verified(store)
    return store.advance(
        tx.migration_id,
        MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
        updates={"qualification_evidence_sha256": "6" * 64},
    )


class RemoteOperatorMigrationTests(unittest.TestCase):
    def test_wrong_transaction_digest_is_stale_and_does_not_advance(self):
        with tempfile.TemporaryDirectory() as td:
            store = MigrationStore(Path(td) / "migrations")
            tx = advance_to_qualified(store)
            with self.assertRaisesRegex(MigrationHandoffError, "STALE_DIRECTIVE"):
                advance_migration_if_current(
                    store,
                    tx.migration_id,
                    expected_transaction_sha256="0" * 64,
                    expected_phase=MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
                    next_phase=MigrationPhase.PREDECESSOR_CLOSED,
                    expected_qualification_evidence_sha256="6" * 64,
                )
            self.assertEqual(store.load(tx.migration_id).phase, MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION)

    def test_wrong_phase_is_stale_and_does_not_advance(self):
        with tempfile.TemporaryDirectory() as td:
            store = MigrationStore(Path(td) / "migrations")
            tx = advance_to_qualified(store)
            with self.assertRaisesRegex(MigrationHandoffError, "STALE_DIRECTIVE"):
                advance_migration_if_current(
                    store,
                    tx.migration_id,
                    expected_transaction_sha256=tx.transaction_sha256,
                    expected_phase=MigrationPhase.SUCCESSOR_VERIFIED,
                    next_phase=MigrationPhase.PREDECESSOR_CLOSED,
                    expected_qualification_evidence_sha256="6" * 64,
                )
            self.assertEqual(store.load(tx.migration_id).phase, MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION)

    def test_successor_verified_cannot_skip_qualification(self):
        with tempfile.TemporaryDirectory() as td:
            store = MigrationStore(Path(td) / "migrations")
            tx = advance_to_successor_verified(store)
            with self.assertRaisesRegex(MigrationHandoffError, "qualification"):
                advance_migration_if_current(
                    store,
                    tx.migration_id,
                    expected_transaction_sha256=tx.transaction_sha256,
                    expected_phase=MigrationPhase.SUCCESSOR_VERIFIED,
                    next_phase=MigrationPhase.PREDECESSOR_CLOSED,
                )
            self.assertEqual(store.load(tx.migration_id).phase, MigrationPhase.SUCCESSOR_VERIFIED)

    def test_qualified_resume_closes_predecessor_once_without_recreating_anything(self):
        with tempfile.TemporaryDirectory() as td:
            store = MigrationStore(Path(td) / "migrations")
            tx = advance_to_qualified(store)
            create_v2_calls = []
            advance_calls = []
            original_create_v2 = store.create_v2
            original_advance = store.advance

            def counted_create(spec):
                create_v2_calls.append(spec)
                return original_create_v2(spec)

            def counted_advance(migration_id, phase, *, updates=None):
                advance_calls.append((migration_id, MigrationPhase(phase), updates))
                return original_advance(migration_id, phase, updates=updates)

            store.create_v2 = counted_create  # type: ignore[method-assign]
            store.advance = counted_advance  # type: ignore[method-assign]
            closed = advance_migration_if_current(
                store,
                tx.migration_id,
                expected_transaction_sha256=tx.transaction_sha256,
                expected_phase=MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
                next_phase=MigrationPhase.PREDECESSOR_CLOSED,
                expected_qualification_evidence_sha256="6" * 64,
            )
            self.assertEqual(closed.phase, MigrationPhase.PREDECESSOR_CLOSED)
            self.assertEqual(create_v2_calls, [])
            self.assertEqual(advance_calls, [(tx.migration_id, MigrationPhase.PREDECESSOR_CLOSED, None)])
            self.assertEqual(closed.qualification_evidence_sha256, "6" * 64)

    def test_qualification_digest_mismatch_is_stale(self):
        with tempfile.TemporaryDirectory() as td:
            store = MigrationStore(Path(td) / "migrations")
            tx = advance_to_qualified(store)
            with self.assertRaisesRegex(MigrationHandoffError, "STALE_DIRECTIVE"):
                advance_migration_if_current(
                    store,
                    tx.migration_id,
                    expected_transaction_sha256=tx.transaction_sha256,
                    expected_phase=MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
                    next_phase=MigrationPhase.PREDECESSOR_CLOSED,
                    expected_qualification_evidence_sha256="0" * 64,
                )

    def test_post_close_rollback_remains_illegal(self):
        with tempfile.TemporaryDirectory() as td:
            store = MigrationStore(Path(td) / "migrations")
            tx = advance_to_qualified(store)
            closed = advance_migration_if_current(
                store,
                tx.migration_id,
                expected_transaction_sha256=tx.transaction_sha256,
                expected_phase=MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
                next_phase=MigrationPhase.PREDECESSOR_CLOSED,
                expected_qualification_evidence_sha256="6" * 64,
            )
            with self.assertRaises(MigrationHandoffError):
                store.rollback(closed.migration_id, "too late")


if __name__ == "__main__":
    unittest.main()
