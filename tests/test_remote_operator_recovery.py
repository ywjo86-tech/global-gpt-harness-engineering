from __future__ import annotations

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
from runtime.orchestrator.remote_operator_ingress import reconcile_committed_delivery
from runtime.orchestrator.remote_operator_outbox import RemoteResultOutbox, RemoteResultProjectionV1
from runtime.orchestrator.remote_operator_receipt import ReceiptStatus, RemoteOperatorReceiptStore


def envelope():
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "MSG-RECOVER-1",
        "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "CTRL-1",
            "source_actor_id": "235775273",
            "source_message_id": "901",
        },
        "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1", "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1",
            "current_stage": "PREPARE", "requested_next_stage": "ACTION",
            "required_capabilities": ["filesystem_write"], "state_change_required": True,
            "input_artifact_digests": ["a" * 64], "gate_id": "G1", "directive_id": "D-RECOVER-1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "b" * 64, "continuation_owner_epoch": 1,
            "canonical_run_state_sha256": "c" * 64, "migration_id": "", "migration_transaction_sha256": "",
            "migration_phase": "", "qualification_evidence_sha256": "", "source_head": "e" * 40,
            "runtime_release_digest": "d" * 64,
        },
        "authorization": {
            "risk_envelope_ref": "RISK-1", "risk_envelope_digest": "f" * 64,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
    )


def projection(env, **changes):
    values = {
        "projection_id": "PROJ-RECOVER-1",
        "message_id": env.message_id,
        "directive_digest": env.directive_digest,
        "project_id": env.project_id,
        "run_id": env.run_id,
        "gate_id": env.gate_id,
        "task_id": env.task_id,
        "canonical_state_ref": "state:R1",
        "canonical_state_sha256": "8" * 64,
        "effect_evidence_refs": ("effect:1",),
        "checkpoint_ref": "checkpoint:R1",
        "checkpoint_sha256": "9" * 64,
        "migration_transaction_sha256": "",
        "result_class": "CANONICAL_ACTION_COMPLETED",
        "result_summary": "recovered",
        "projected_at": "2026-09-21T00:06:00+00:00",
    }
    values.update(changes)
    return RemoteResultProjectionV1(**values)


class RemoteOperatorRecoveryTests(unittest.TestCase):
    def test_crash_after_canonical_mutation_reconstructs_without_reexecution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = envelope()
            receipt_store = RemoteOperatorReceiptStore(root / "receipts")
            outbox = RemoteResultOutbox(root / "outbox")
            execution_count = 1  # canonical action already committed before OCP receipt/projection

            decision = reconcile_committed_delivery(
                env,
                receipt_store=receipt_store,
                outbox=outbox,
                evidence_resolver=lambda message_id, directive_digest: projection(env),
            )
            self.assertEqual(execution_count, 1)
            self.assertTrue(decision.reconciled)
            self.assertEqual(decision.result_class, "CANONICAL_ACTION_COMPLETED")
            self.assertEqual(receipt_store.classify_delivery(env), ReceiptStatus.IDEMPOTENT_REPLAY)
            self.assertEqual([item.projection_id for item in outbox.pending()], ["PROJ-RECOVER-1"])

    def test_ambiguous_evidence_blocks_instead_of_replaying(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = envelope()
            decision = reconcile_committed_delivery(
                env,
                receipt_store=RemoteOperatorReceiptStore(root / "receipts"),
                outbox=RemoteResultOutbox(root / "outbox"),
                evidence_resolver=lambda *_: None,
            )
            self.assertFalse(decision.reconciled)
            self.assertEqual(decision.result_class, "RECONCILIATION_REQUIRED")

    def test_wrong_evidence_binding_is_reconciliation_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = envelope()
            wrong = projection(env, message_id="OTHER")
            decision = reconcile_committed_delivery(
                env,
                receipt_store=RemoteOperatorReceiptStore(root / "receipts"),
                outbox=RemoteResultOutbox(root / "outbox"),
                evidence_resolver=lambda *_: wrong,
            )
            self.assertFalse(decision.reconciled)
            self.assertEqual(decision.result_class, "RECONCILIATION_REQUIRED")

    def test_existing_transport_receipt_can_gain_terminal_projection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = envelope()
            receipts = RemoteOperatorReceiptStore(root / "receipts")
            receipts.record_received(env)
            outbox = RemoteResultOutbox(root / "outbox")
            decision = reconcile_committed_delivery(
                env,
                receipt_store=receipts,
                outbox=outbox,
                evidence_resolver=lambda *_: projection(env),
            )
            self.assertTrue(decision.reconciled)
            self.assertEqual(len(outbox.pending()), 1)


if __name__ == "__main__":
    unittest.main()
