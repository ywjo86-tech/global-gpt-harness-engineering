from __future__ import annotations
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

class DurableContinuationFailureInjectionTests(unittest.TestCase):
    def test_stale_epoch_blocks_resume(self):
        try:
            from runtime.orchestrator.durable_continuation import evaluate_continuation_eligibility
        except ModuleNotFoundError as exc:
            self.fail(f"durable continuation module missing: {exc}")
        state={"state":"WAITING_RESOURCE","last_error":"CONTINUATION_RECOVERY_PENDING"}
        ctx={"continuation_policy":"AUTO_WITHIN_APPROVED_CONTRACT","contract_valid":True,
             "attestation_valid":True,"transaction_phase":"RECEIPT_SEALED","owner_epoch_current":False}
        result=evaluate_continuation_eligibility(state,ctx)
        self.assertFalse(result.eligible)
        self.assertEqual(result.reason,"STALE_OWNER_EPOCH")

    def test_committed_generation_recovers_stale_latest_pointer(self):
        from runtime.orchestrator.implementation_continuation import GenerationalContinuationStore
        with TemporaryDirectory() as directory:
            store = GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
            first = store.commit_generation(
                generation_id="G1",
                previous_generation_id=None,
                phase="GREEN_RUNNING",
                checkpoint={"state": "intent"},
                approval_digest="a" * 64,
                spec_digest="b" * 64,
                source_digest="c" * 64,
                environment_digest="d" * 64,
                effect_intent_id="intent-1",
                effect_receipt_ref=None,
            )
            second = store.commit_generation(
                generation_id="G2",
                previous_generation_id="G1",
                phase="FOCUSED_VALIDATION",
                checkpoint={"state": "receipt"},
                approval_digest="a" * 64,
                spec_digest="b" * 64,
                source_digest="c" * 64,
                environment_digest="d" * 64,
                effect_intent_id="intent-1",
                effect_receipt_ref="receipt:1",
            )
            store.latest_path.write_text(
                '{"schema_version":"orchestration.tdd-continuation-latest.v1","generation_id":"G1"}',
                encoding="utf-8",
            )

            recovered = store.recover_latest()

            self.assertEqual(first["status"], "COMMITTED")
            self.assertEqual(second["status"], "COMMITTED")
            self.assertEqual(recovered["status"], "COMMITTED_RECOVERED")
            self.assertEqual(recovered["generation_id"], "G2")
            self.assertEqual(store.load_latest()["generation_id"], "G2")

    def test_v1_checkpoint_promotes_to_single_v2_generation_without_rewriting_legacy(self):
        from runtime.orchestrator.implementation_continuation import (
            ExpectedRedContractV1,
            GenerationalContinuationStore,
            TDDContinuationStore,
            promote_legacy_checkpoint_generation,
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            contract = ExpectedRedContractV1.create(
                project_id="P",
                run_id="R",
                task_id="TASK-001",
                tdd_cycle_id="TDD-001",
                source_sha="a" * 40,
                authority_digest="b" * 64,
                test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red",
                test_command_digest="c" * 64,
                dependency_environment_digest="d" * 64,
                expected_failure_semantic_signature="e" * 64,
                expected_failure_count=1,
                allowed_error_count=0,
                valid_until="2026-10-01T01:00:00+00:00",
                allowed_change_paths=("runtime/orchestrator/",),
                max_remediation_attempts=1,
            )
            legacy = TDDContinuationStore(root, project_id="P", run_id="R")
            checkpoint = legacy.arm(contract)
            before = legacy.pointer_path.read_bytes()
            generation = GenerationalContinuationStore(
                root, project_id="P", run_id="R", task_id="TASK-001", cycle_id="TDD-001"
            )

            promoted = promote_legacy_checkpoint_generation(
                legacy,
                generation,
                generation_id="legacy-0001",
                approval_digest="1" * 64,
                spec_digest="2" * 64,
            )
            promoted_again = promote_legacy_checkpoint_generation(
                legacy,
                generation,
                generation_id="legacy-0001",
                approval_digest="1" * 64,
                spec_digest="2" * 64,
            )

            self.assertIn(promoted["status"], {"COMMITTED", "COMMITTED_POINTER_STALE"})
            self.assertEqual(promoted_again["status"], "ALREADY_PROMOTED")
            self.assertEqual(generation.load_latest()["generation_id"], "legacy-0001")
            self.assertEqual(legacy.pointer_path.read_bytes(), before)
            self.assertEqual(checkpoint.phase, "RED_ARMED")

    def test_damaged_v1_pointer_blocks_generation_promotion(self):
        from runtime.orchestrator.implementation_continuation import (
            GenerationalContinuationStore,
            TDDContinuationError,
            TDDContinuationStore,
            promote_legacy_checkpoint_generation,
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = TDDContinuationStore(root, project_id="P", run_id="R")
            legacy.pointer_path.parent.mkdir(parents=True, exist_ok=True)
            legacy.pointer_path.write_text("{}", encoding="utf-8")
            generation = GenerationalContinuationStore(
                root, project_id="P", run_id="R", task_id="TASK-001", cycle_id="TDD-001"
            )

            with self.assertRaisesRegex(TDDContinuationError, "legacy checkpoint promotion blocked"):
                promote_legacy_checkpoint_generation(
                    legacy,
                    generation,
                    generation_id="legacy-0001",
                    approval_digest="1" * 64,
                    spec_digest="2" * 64,
                )


    def _commit(self, store, generation_id, previous_generation_id=None, *, phase="GREEN_RUNNING", receipt=None):
        return store.commit_generation(
            generation_id=generation_id,
            previous_generation_id=previous_generation_id,
            phase=phase,
            checkpoint={"state": generation_id},
            approval_digest="a" * 64,
            spec_digest="b" * 64,
            source_digest="c" * 64,
            environment_digest="d" * 64,
            effect_intent_id="intent-1",
            effect_receipt_ref=receipt,
        )

    def test_precommit_fault_matrix_preserves_last_committed_tip(self):
        from runtime.orchestrator import implementation_continuation as module
        from runtime.orchestrator.durable_io import DurableIOError, durable_json_save as real_save
        for fault in ("checkpoint", "manifest", "commit"):
            with self.subTest(fault=fault), TemporaryDirectory() as directory:
                store = module.GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
                self._commit(store, "G1", phase="FOCUSED_VALIDATION", receipt="receipt:1")
                targets = {
                    "checkpoint": store._generation_dir("G2") / "checkpoint.json",
                    "manifest": store._generation_dir("G2") / "manifest.json",
                    "commit": store._commit_path("G2"),
                }
                def fail_boundary(path, payload):
                    if Path(path) == targets[fault]:
                        raise DurableIOError(f"injected {fault} failure")
                    return real_save(path, payload)
                with patch.object(module, "durable_json_save", side_effect=fail_boundary):
                    with self.assertRaises(DurableIOError):
                        self._commit(store, "G2", "G1", phase="REGRESSION_VALIDATION", receipt="receipt:1")
                state = store.inspect_state()
                self.assertEqual(state["status"], "COMMITTED")
                self.assertEqual(state["generation_id"], "G1")

    def test_commit_record_revalidation_failure_returns_pointer_stale_then_recovers(self):
        from runtime.orchestrator import implementation_continuation as module
        with TemporaryDirectory() as directory:
            store = module.GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
            self._commit(store, "G1", phase="FOCUSED_VALIDATION", receipt="receipt:1")
            original = store._load_commit
            failed = {"done": False}
            def fail_once(generation_id):
                if generation_id == "G2" and not failed["done"]:
                    failed["done"] = True
                    raise module.TDDContinuationError("injected commit revalidation failure")
                return original(generation_id)
            with patch.object(store, "_load_commit", side_effect=fail_once):
                result = self._commit(store, "G2", "G1", phase="REGRESSION_VALIDATION", receipt="receipt:1")
            self.assertEqual(result["status"], "COMMITTED_POINTER_STALE")
            self.assertEqual(store.inspect_state()["status"], "POINTER_STALE")
            recovered = store.recover_latest()
            self.assertEqual(recovered["generation_id"], "G2")

    def test_latest_revalidation_failure_returns_pointer_stale_then_recovers(self):
        from runtime.orchestrator import implementation_continuation as module
        with TemporaryDirectory() as directory:
            store = module.GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
            self._commit(store, "G1", phase="FOCUSED_VALIDATION", receipt="receipt:1")
            with patch.object(store, "load_latest", side_effect=module.TDDContinuationError("injected latest revalidation failure")):
                result = self._commit(store, "G2", "G1", phase="REGRESSION_VALIDATION", receipt="receipt:1")
            self.assertEqual(result["status"], "COMMITTED_POINTER_STALE")
            recovered = store.recover_latest()
            self.assertEqual(recovered["generation_id"], "G2")

    def test_latest_write_failure_returns_pointer_stale_then_recovers(self):
        from runtime.orchestrator import implementation_continuation as module
        from runtime.orchestrator.durable_io import DurableIOError, durable_json_save as real_save
        with TemporaryDirectory() as directory:
            store = module.GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
            failed = {"done": False}
            def fail_latest_once(path, payload):
                if Path(path) == store.latest_path and not failed["done"]:
                    failed["done"] = True
                    raise DurableIOError("injected latest replacement failure")
                return real_save(path, payload)
            with patch.object(module, "durable_json_save", side_effect=fail_latest_once):
                result = self._commit(store, "G1", phase="FOCUSED_VALIDATION", receipt="receipt:1")
            self.assertEqual(result["status"], "COMMITTED_POINTER_STALE")
            recovered = store.recover_latest()
            self.assertEqual(recovered["status"], "COMMITTED_RECOVERED")
            self.assertEqual(store.load_latest()["generation_id"], "G1")

    def test_state_classifier_covers_prepared_committed_and_pointer_stale(self):
        from runtime.orchestrator.implementation_continuation import GenerationalContinuationStore
        from runtime.orchestrator.durable_io import durable_json_save
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = GenerationalContinuationStore(root, project_id="P", run_id="RP", task_id="T", cycle_id="C")
            checkpoint = prepared._checkpoint_payload("G1", {"state": "prepared"})
            durable_json_save(prepared._generation_dir("G1") / "checkpoint.json", checkpoint)
            manifest = prepared._manifest_payload(
                generation_id="G1", previous_generation_id=None, phase="GREEN_RUNNING",
                checkpoint_digest=checkpoint["checkpoint_digest"], approval_digest="a" * 64,
                spec_digest="b" * 64, source_digest="c" * 64, environment_digest="d" * 64,
                effect_intent_id="intent-1", effect_receipt_ref=None,
            )
            durable_json_save(prepared._generation_dir("G1") / "manifest.json", manifest)
            self.assertEqual(prepared.inspect_state()["status"], "PREPARED")

            committed = GenerationalContinuationStore(root, project_id="P", run_id="RC", task_id="T", cycle_id="C")
            self._commit(committed, "G1")
            latest_g1 = committed.latest_path.read_bytes()
            self.assertEqual(committed.inspect_state()["status"], "COMMITTED")
            self._commit(committed, "G2", "G1", phase="FOCUSED_VALIDATION", receipt="receipt:1")
            committed.latest_path.write_bytes(latest_g1)
            self.assertEqual(committed.inspect_state()["status"], "POINTER_STALE")
            with self.assertRaisesRegex(Exception, "RECOVERY"):
                self._commit(committed, "G3", "G2", phase="REGRESSION_VALIDATION", receipt="receipt:1")

    def test_state_classifier_blocks_orphan_and_forked_chains(self):
        from runtime.orchestrator.implementation_continuation import GenerationalContinuationStore
        with TemporaryDirectory() as directory:
            root = Path(directory)
            orphan = GenerationalContinuationStore(root, project_id="P", run_id="RO", task_id="T", cycle_id="C")
            self._commit(orphan, "G1")
            self._commit(orphan, "G2", "G1", phase="FOCUSED_VALIDATION", receipt="receipt:1")
            orphan._commit_path("G1").unlink()
            self.assertEqual(orphan.inspect_state()["status"], "ORPHAN")
            with self.assertRaisesRegex(Exception, "CONTINUATION_RECOVERY_BLOCKED"):
                orphan.recover_latest()

            from runtime.orchestrator import implementation_continuation as module
            from runtime.orchestrator.durable_io import durable_json_save
            forked = GenerationalContinuationStore(root, project_id="P", run_id="RF", task_id="T", cycle_id="C")
            self._commit(forked, "G1")
            self._commit(forked, "G2", "G1")
            with self.assertRaisesRegex(Exception, "fork"):
                self._commit(forked, "G3", "G1")
            checkpoint = forked._checkpoint_payload("G3", {"state": "fault-injected-fork"})
            durable_json_save(forked._generation_dir("G3") / "checkpoint.json", checkpoint)
            manifest = forked._manifest_payload(
                generation_id="G3", previous_generation_id="G1", phase="GREEN_RUNNING",
                checkpoint_digest=checkpoint["checkpoint_digest"], approval_digest="a" * 64,
                spec_digest="b" * 64, source_digest="c" * 64, environment_digest="d" * 64,
                effect_intent_id="intent-fork", effect_receipt_ref=None,
            )
            durable_json_save(forked._generation_dir("G3") / "manifest.json", manifest)
            parent = forked._load_commit("G1")
            commit = {
                "schema_version": module.GENERATION_COMMIT_SCHEMA, "project_id": "P", "run_id": "RF",
                "task_id": "T", "cycle_id": "C", "generation_id": "G3",
                "previous_committed_generation_id": "G1", "manifest_digest": manifest["manifest_digest"],
                "checkpoint_digest": checkpoint["checkpoint_digest"], "previous_commit_digest": parent["commit_digest"],
            }
            commit["commit_digest"] = module._digest(commit)
            durable_json_save(forked._commit_path("G3"), commit)
            self.assertEqual(forked.inspect_state()["status"], "FORKED")
            with self.assertRaisesRegex(Exception, "CONTINUATION_RECOVERY_BLOCKED"):
                forked.recover_latest()

    def test_green_running_recovery_requires_effect_reconciliation(self):
        from runtime.orchestrator.implementation_continuation import GenerationalContinuationStore
        with TemporaryDirectory() as directory:
            store = GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
            self._commit(store, "G1", phase="GREEN_RUNNING", receipt=None)
            store.latest_path.unlink()
            with self.assertRaisesRegex(Exception, "EFFECT_RECONCILIATION_REQUIRED"):
                store.recover_latest()
            self.assertEqual(store.load_latest()["generation_id"], "G1")

    def test_recovery_blocks_tampered_committed_manifest(self):
        from runtime.orchestrator.implementation_continuation import GenerationalContinuationStore
        with TemporaryDirectory() as directory:
            store = GenerationalContinuationStore(Path(directory), project_id="P", run_id="R", task_id="T", cycle_id="C")
            self._commit(store, "G1")
            manifest_path = store._generation_dir("G1") / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["phase"] = "COMPLETED"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "CONTINUATION_RECOVERY_BLOCKED"):
                store.recover_latest()

    def test_inconsistent_legacy_pair_blocks_without_generation_overwrite(self):
        from runtime.orchestrator.implementation_continuation import (
            ExpectedRedContractV1, GenerationalContinuationStore, TDDContinuationError,
            TDDContinuationStore, promote_legacy_checkpoint_generation,
        )
        with TemporaryDirectory() as directory:
            root=Path(directory)
            now=datetime(2026,10,1,1,0,tzinfo=timezone.utc)
            contract=ExpectedRedContractV1.create(
                project_id="P", run_id="R", task_id="TASK-001", tdd_cycle_id="TDD-001",
                source_sha="a"*40, authority_digest="b"*64, test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
                dependency_environment_digest="d"*64, expected_failure_semantic_signature="e"*64,
                expected_failure_count=1, allowed_error_count=0,
                valid_until=(now+timedelta(hours=1)).isoformat(), allowed_change_paths=("runtime/orchestrator/",),
                max_remediation_attempts=1,
            )
            legacy=TDDContinuationStore(root, project_id="P", run_id="R")
            legacy.arm(contract)
            pointer_before=legacy.pointer_path.read_bytes()
            checkpoint_path=legacy._path("TASK-001", "TDD-001")
            checkpoint=json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["phase"]="BLOCKED"
            checkpoint_path.write_text(json.dumps(checkpoint),encoding="utf-8")
            generation=GenerationalContinuationStore(root, project_id="P", run_id="R", task_id="TASK-001", cycle_id="TDD-001")
            with self.assertRaisesRegex(TDDContinuationError,"legacy checkpoint promotion blocked"):
                promote_legacy_checkpoint_generation(legacy,generation,generation_id="legacy-0001",approval_digest="1"*64,spec_digest="2"*64)
            self.assertEqual(legacy.pointer_path.read_bytes(),pointer_before)
            self.assertFalse(generation.commits.exists())

    def test_duplicate_resume_same_effect_intent_never_allows_second_effect(self):
        from runtime.orchestrator.implementation_continuation import ExpectedRedContractV1, FailureObservationV1, TDDContinuationStore
        with TemporaryDirectory() as directory:
            root=Path(directory); now=datetime(2026,10,1,1,0,tzinfo=timezone.utc)
            contract=ExpectedRedContractV1.create(
                project_id="P", run_id="R", task_id="TASK-001", tdd_cycle_id="TDD-001",
                source_sha="a"*40, authority_digest="b"*64, test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
                dependency_environment_digest="d"*64, expected_failure_semantic_signature="e"*64,
                expected_failure_count=1, allowed_error_count=0,
                valid_until=(now+timedelta(hours=1)).isoformat(), allowed_change_paths=("runtime/orchestrator/",), max_remediation_attempts=1,
            )
            observation=FailureObservationV1.create(
                project_id="P", run_id="R", task_id="TASK-001", tdd_cycle_id="TDD-001", source_sha="a"*40,
                authority_digest="b"*64, test_kind="FOCUSED_TDD", test_selector="tests.test_x.X.test_red",
                test_command_digest="c"*64, dependency_environment_digest="d"*64, outcome="FAILED",
                failure_semantic_signature="e"*64, failure_count=1, error_count=0, receipt_digest="f"*64,
            )
            store=TDDContinuationStore(root,project_id="P",run_id="R")
            store.arm(contract); store.begin_red(contract.contract_digest); store.record_red_observation(contract,observation,now=now)
            running=store.begin_green(contract)
            effects=1
            for _ in range(2):
                restarted=TDDContinuationStore(root,project_id="P",run_id="R")
                decision=restarted.resume(contract,current_source_sha="a"*40,current_authority_digest="b"*64,current_dependency_environment_digest="d"*64,approval_valid=True,now=now)
                self.assertEqual(decision.action,"BLOCKED_RECONCILIATION_REQUIRED")
                self.assertEqual(restarted.load().effect_step_id,running.effect_step_id)
            self.assertEqual(effects,1)

if __name__=="__main__": unittest.main()
