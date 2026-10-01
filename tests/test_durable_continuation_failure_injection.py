from __future__ import annotations
import unittest
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

if __name__=="__main__": unittest.main()
