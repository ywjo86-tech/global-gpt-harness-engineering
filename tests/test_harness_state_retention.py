from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.gate_continuation_transaction import GateContinuationTransactionStore
from runtime.orchestrator.harness_state_root import job_state_root
from runtime.orchestrator.operator_plan_execution import OperatorPlanReceiptStore
from runtime.orchestrator.operator_turn_checkpoint import OperatorTurnCheckpoint, OperatorTurnCheckpointStore
from runtime.orchestrator.production_attention import AttentionOutbox
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.orchestrator.runtime_migration_handoff import MigrationStore, migration_store_root
from runtime.orchestrator.verified_gate_attestation import VerifiedGateAttestation, VerifiedGateAttestationStore


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HarnessStateRetentionTests(unittest.TestCase):
    def test_operator_resume_lock_uses_modern_state_root_not_legacy_alias(self):
        from runtime.orchestrator import production_full_plan_operator_resume as module

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            legacy = base / "disposable-worktree"; legacy.mkdir()
            stable = base / "stable-state"; stable.mkdir()
            canonical = stable / "_workspace/production-full-plan-jobs/P/R.job.json"
            job = {
                "project_id": "P", "run_id": "R",
                "harness_root": str(legacy), "harness_state_root": str(stable),
            }
            observed: dict[str, Path] = {}

            @contextmanager
            def capture_lock(path: Path):
                observed["base"] = path
                yield

            with patch.object(module, "_canonical_registered_job", return_value=(canonical, job)), \
                 patch.object(module, "_operator_resume_lock", side_effect=capture_lock), \
                 patch.object(module, "_bind_manual_action_and_resume_locked", return_value={"status": "TEST"}):
                module.bind_manual_action_and_resume(
                    job_path=canonical, gate_id="G1", lv_id="LV1",
                    action_path=base / "action.json", authorization_path=base / "auth.json",
                )

            self.assertEqual(
                observed["base"],
                stable.resolve() / "_workspace/production-full-plan/P/R",
            )

    def test_worktree_cleanup_preserves_canonical_durable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project-worktree"; project.mkdir()
            stable = base / "state"; stable.mkdir()
            project_id, run_id, gate_id = "P", "R", "G1"

            # Registered job namespace.
            job_path = stable / "_workspace/production-full-plan-jobs/P/R.job.json"
            job_path.parent.mkdir(parents=True)
            job_path.write_text(json.dumps({
                "project_id": project_id, "run_id": run_id,
                "project_root": str(project), "harness_root": str(stable),
                "harness_state_root": str(stable),
            }, sort_keys=True), encoding="utf-8")

            # Full Plan run state + Attention.
            supervisor = DurableFullPlanSupervisor(
                stable, project_id=project_id, run_id=run_id, gates=(gate_id,),
                min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
            )
            state, _ = supervisor.load()
            supervisor._persist(state, {"event": "RETENTION_FIXTURE"})
            attention = supervisor.attention_outbox.publish(
                kind="RETENTION_TEST", state="READY", reason="fixture", gate_id=gate_id,
            )
            attention_path = supervisor.attention_outbox.pending_dir / f"{attention['event_id']}.json"

            # Operator receipt.
            receipt_store = OperatorPlanReceiptStore(stable, project_id=project_id, run_id=run_id)
            receipt_store.create_pass_receipt(
                gate_id=gate_id, plan_sha256="1" * 64, spec_sha256="2" * 64,
                branch="main", source_head="3" * 40, tests=("unit",),
            )
            receipt_path = receipt_store._path(gate_id)

            # Runtime migration evidence.
            migration_store = MigrationStore(migration_store_root(stable, project_id))
            migration = migration_store.create({
                "migration_id":"M1", "project_id":project_id,
                "predecessor_run_id":run_id, "successor_run_id":"R2",
                "current_gate":gate_id, "resume_gate":gate_id,
                "approved_plan_sha256":"4"*64, "approved_spec_sha256":"5"*64,
                "authority_core_sha256":"6"*64, "predecessor_state_sha256":"7"*64,
                "source_head":"8"*40, "target_release_head":"9"*40,
                "target_manifest_sha256":"a"*64, "successor_job_spec_sha256":"b"*64,
            })
            migration_path = migration_store.path(migration.migration_id)

            # DCC transaction + attestation.
            transaction_store = GateContinuationTransactionStore(stable, project_id=project_id, run_id=run_id)
            transaction_store.create(gate_id=gate_id, authority_core_sha256="c"*64, contract_sha256="d"*64)
            transaction_path = transaction_store.path(gate_id)

            attestation_store = VerifiedGateAttestationStore(stable)
            attestation = VerifiedGateAttestation.create(
                project_id=project_id, run_id=run_id, gate_id=gate_id,
                authority_core_sha256="c"*64, contract_sha256="d"*64,
                source_head="e"*40, source_tree_sha256="f"*40, changed_paths_sha256="0"*64,
                verifier_results={"UNIT":{"status":"PASS","evidence_sha256":"1"*64}},
                evidence_digests={"TEST_RESULT":"2"*64},
            )
            attestation_store.create(attestation)
            attestation_path = attestation_store.path(project_id, run_id, gate_id)

            # Operator safe-yield checkpoint.
            checkpoint_store = OperatorTurnCheckpointStore(stable, project_id=project_id, run_id=run_id)
            checkpoint = OperatorTurnCheckpoint.create(
                project_id=project_id, run_id=run_id, gate_id_or_stage=gate_id,
                authority_core_sha256="3"*64, checkpoint_kind="AUTONOMOUS_OWNER_BOUND",
                owner_kind="FULL_PLAN", owner_ref="owner:R:1", resume_contract_sha256="4"*64,
                last_semantic_progress_at="2026-09-21T00:00:00+00:00",
            )
            checkpoint_store.save(checkpoint)
            checkpoint_path = checkpoint_store.base / f"{checkpoint.checkpoint_sha256}.json"

            paths = (
                job_path, supervisor.state_path, receipt_path, migration_path,
                attention_path, transaction_path, attestation_path, checkpoint_path,
            )
            before = {path: digest(path) for path in paths}
            shutil.rmtree(project)

            self.assertFalse(project.exists())
            for path in paths:
                self.assertTrue(path.is_file(), path)
                self.assertEqual(digest(path), before[path])
                self.assertTrue(path.is_relative_to(stable.resolve()))

    def test_modern_state_root_precedes_legacy_root_without_rewriting_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); legacy = base / "legacy"; stable = base / "stable"
            legacy.mkdir(); stable.mkdir()
            legacy_file = legacy / "legacy.json"
            legacy_file.write_text('{"mode":"MANUAL_OPERATOR"}', encoding="utf-8")
            before = digest(legacy_file)
            job = {"harness_root": str(legacy), "harness_state_root": str(stable)}
            self.assertEqual(job_state_root(job), stable.resolve())
            self.assertEqual(digest(legacy_file), before)
            self.assertEqual(legacy_file.read_text(encoding="utf-8"), '{"mode":"MANUAL_OPERATOR"}')


if __name__ == "__main__":
    unittest.main()
