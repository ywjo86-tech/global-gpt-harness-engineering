from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    seal_remote_envelope,
    validate_remote_envelope,
)
from runtime.orchestrator.remote_operator_ingress import CanonicalCompletionEvidence
from runtime.orchestrator.remote_operator_outbox import RemoteResultOutbox
from runtime.orchestrator.remote_operator_receipt import RemoteOperatorReceiptStore
from runtime.orchestrator.remote_operator_recovery_binding import (
    RemoteExecutionBindingStore,
)
from runtime.orchestrator.ocpv2_canonical_recovery import (
    recover_pending_canonical_results,
)
from runtime.orchestrator.ocpv2_canonical_resume import (
    execute_registered_full_plan_continuation,
)


def envelope():
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "MSG-LIVE-RECOVERY-1",
        "sequence": 11,
        "issued_at": "2026-09-22T03:00:00+00:00",
        "expires_at": "2026-09-22T15:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "PR:1",
            "source_actor_id": "235775273",
            "source_message_id": "1001",
        },
        "project_id": "P1",
        "run_id": "R1",
        "task_id": "G1",
        "task_execution_id": "R1--g1",
        "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1",
            "run_id": "R1",
            "task_id": "G1",
            "task_execution_id": "R1--g1",
            "current_stage": "PREPARE",
            "requested_next_stage": "ACTION",
            "required_capabilities": ["filesystem_write"],
            "state_change_required": True,
            "input_artifact_digests": ["1" * 64],
            "gate_id": "G1",
            "directive_id": "D-LIVE-RECOVERY-1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "2" * 64,
            "continuation_owner_epoch": 1,
            "canonical_run_state_sha256": "3" * 64,
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": "4" * 40,
            "runtime_release_digest": "5" * 64,
        },
        "authorization": {
            "risk_envelope_ref": "RISK-1",
            "risk_envelope_digest": "6" * 64,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload),
        now=datetime(2026, 9, 22, 3, 5, tzinfo=timezone.utc),
    )


def evidence(env, **changes):
    values = {
        "message_id": env.message_id,
        "directive_digest": env.directive_digest,
        "project_id": env.project_id,
        "run_id": env.run_id,
        "gate_id": env.gate_id,
        "task_id": env.task_id,
        "canonical_state_ref": "full-plan-state:P1/R1",
        "canonical_state_sha256": "7" * 64,
        "effect_evidence_refs": ("full-plan-gate:R1--g1",),
        "checkpoint_ref": "",
        "checkpoint_sha256": "",
        "migration_transaction_sha256": "",
        "result_summary": "canonical gate G1 completed",
        "completed_at": "2026-09-22T03:06:00+00:00",
    }
    values.update(changes)
    return CanonicalCompletionEvidence(**values)


class OCPv2LiveRecoveryCompositionTests(unittest.TestCase):
    def test_execution_binding_is_durable_and_idempotent(self):
        env = envelope()
        with tempfile.TemporaryDirectory() as td:
            store = RemoteExecutionBindingStore(Path(td) / "bindings")
            first = store.record(env)
            second = store.record(env)
            self.assertEqual(first.binding_sha256, second.binding_sha256)
            self.assertEqual(store.pending()[0].message_id, env.message_id)
            self.assertEqual(store.pending()[0].task_execution_id, "R1--g1")
            self.assertEqual(store.pending()[0].expected_owner_epoch, 1)

    def test_publish_failure_retries_outbox_without_any_execution_callback(self):
        env = envelope()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipts = RemoteOperatorReceiptStore(root / "receipts")
            receipts.record_received(env)
            bindings = RemoteExecutionBindingStore(root / "bindings")
            bindings.record(env)
            outbox = RemoteResultOutbox(root / "outbox")

            publish_calls = []

            def fail_publish(projection):
                publish_calls.append(projection.projection_id)
                raise RuntimeError("synthetic publish failure")

            with self.assertRaisesRegex(RuntimeError, "synthetic publish failure"):
                recover_pending_canonical_results(
                    binding_store=bindings,
                    receipt_store=receipts,
                    outbox=outbox,
                    evidence_resolver=lambda binding: evidence(env),
                    publisher=fail_publish,
                    durable_acknowledged=lambda _message_id: False,
                )

            self.assertEqual(len(outbox.pending()), 1)
            self.assertEqual(bindings.pending()[0].status, "OUTBOXED")

            delivered = []
            result = recover_pending_canonical_results(
                binding_store=bindings,
                receipt_store=receipts,
                outbox=outbox,
                evidence_resolver=lambda binding: evidence(env),
                publisher=lambda projection: delivered.append(projection.projection_id),
                durable_acknowledged=lambda _message_id: False,
            )

            self.assertEqual(result["published"], 1)
            self.assertEqual(len(outbox.pending()), 0)
            self.assertEqual(len(delivered), 1)
            self.assertEqual(bindings.pending(), ())

    def test_mismatched_canonical_evidence_fails_closed_without_outbox(self):
        env = envelope()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipts = RemoteOperatorReceiptStore(root / "receipts")
            receipts.record_received(env)
            bindings = RemoteExecutionBindingStore(root / "bindings")
            bindings.record(env)
            outbox = RemoteResultOutbox(root / "outbox")

            result = recover_pending_canonical_results(
                binding_store=bindings,
                receipt_store=receipts,
                outbox=outbox,
                evidence_resolver=lambda binding: evidence(env, message_id="OTHER"),
                publisher=lambda _projection: self.fail("must not publish"),
                durable_acknowledged=lambda _message_id: False,
            )

            self.assertEqual(result["recovered"], 0)
            self.assertEqual(result["unresolved"], (env.message_id,))
            self.assertEqual(outbox.pending(), ())
            self.assertEqual(len(bindings.pending()), 1)

    def test_canonical_resume_accepts_remote_identity_for_owner_claim(self):
        parameters = inspect.signature(execute_registered_full_plan_continuation).parameters
        self.assertIn("remote_message_id", parameters)
        self.assertIn("remote_directive_digest", parameters)

    def test_deployed_runtime_wires_recovery_before_control_poll(self):
        import runtime.orchestrator.ocpv2_runtime_service as module

        source = inspect.getsource(module._compose_service)
        self.assertIn("RemoteExecutionBindingStore", inspect.getsource(module))
        self.assertIn("recover_pending_canonical_results", source)
        self.assertIn("binding_store.record", source)
        self.assertIn("RECONCILIATION_REQUIRED", source)


if __name__ == "__main__":
    unittest.main()
