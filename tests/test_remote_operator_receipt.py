from __future__ import annotations

import json
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
from runtime.orchestrator.remote_operator_receipt import (
    ReceiptStatus,
    RemoteOperatorReceiptError,
    RemoteOperatorReceiptStore,
)


def _envelope(*, message_id="MSG-1", sequence=1, source_message_id="101"):
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": message_id,
        "sequence": sequence,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "CTRL-1",
            "source_actor_id": "235775273",
            "source_message_id": source_message_id,
        },
        "project_id": "P1",
        "run_id": "R1",
        "task_id": "T1",
        "task_execution_id": "E1",
        "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1",
            "run_id": "R1",
            "task_id": "T1",
            "task_execution_id": "E1",
            "current_stage": "ENTRY",
            "requested_next_stage": "PREPARE",
            "required_capabilities": ["reasoning"],
            "state_change_required": False,
            "input_artifact_digests": [],
            "gate_id": "G1",
            "directive_id": f"D-{message_id}",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "",
            "continuation_owner_epoch": 0,
            "canonical_run_state_sha256": "",
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": "",
            "runtime_release_digest": "",
        },
        "authorization": {
            "risk_envelope_ref": "",
            "risk_envelope_digest": "",
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload),
        now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
    )


class RemoteOperatorReceiptTests(unittest.TestCase):
    def test_new_delivery_then_same_digest_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            env = _envelope()
            self.assertEqual(store.classify_delivery(env), ReceiptStatus.NEW)
            store.record_received(env)
            self.assertEqual(store.classify_delivery(env), ReceiptStatus.IDEMPOTENT_REPLAY)

    def test_same_message_id_with_changed_digest_is_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            first = _envelope(message_id="MSG-1", sequence=1, source_message_id="101")
            store.record_received(first)
            second = _envelope(message_id="MSG-1", sequence=2, source_message_id="102")
            self.assertEqual(store.classify_delivery(second), ReceiptStatus.TAMPER_DETECTED)

    def test_lower_sequence_and_same_sequence_different_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            store.record_received(_envelope(message_id="MSG-2", sequence=2, source_message_id="202"))
            self.assertEqual(
                store.classify_delivery(_envelope(message_id="MSG-1", sequence=1, source_message_id="101")),
                ReceiptStatus.REPLAY_REJECTED,
            )
            self.assertEqual(
                store.classify_delivery(_envelope(message_id="MSG-X", sequence=2, source_message_id="DIFFERENT")),
                ReceiptStatus.REPLAY_REJECTED,
            )

    def test_receipt_does_not_own_canonical_task_or_migration_truth(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = RemoteOperatorReceiptStore(root)
            store.record_received(_envelope())
            receipt = json.loads(next((root / "GITHUB_CONTROL_V1" / "CTRL-1").glob("MSG-1.json")).read_text())
            forbidden = {"current_stage", "migration_phase", "execution_state", "task_status", "gate_status"}
            self.assertFalse(forbidden.intersection(receipt))
            self.assertIn("envelope_sha256", receipt)
            self.assertIn("directive_digest", receipt)

    def test_symlink_root_or_receipt_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td) / "receipts"
            root.symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaises(RemoteOperatorReceiptError):
                RemoteOperatorReceiptStore(root)
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            store = RemoteOperatorReceiptStore(root)
            channel = root / "GITHUB_CONTROL_V1" / "CTRL-1"
            channel.mkdir(parents=True)
            (channel / "MSG-1.json").symlink_to(Path(outside) / "target.json")
            with self.assertRaises(RemoteOperatorReceiptError):
                store.classify_delivery(_envelope())

    def test_sequence_previous_generation_recovers_after_primary_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = RemoteOperatorReceiptStore(root)
            store.record_received(_envelope(message_id="MSG-1", sequence=1, source_message_id="101"))
            store.record_received(_envelope(message_id="MSG-2", sequence=2, source_message_id="102"))
            sequence_path = root / "GITHUB_CONTROL_V1" / "CTRL-1" / ".sequence.json"
            sequence_path.write_text("{corrupt", encoding="utf-8")
            recovered = RemoteOperatorReceiptStore(root)
            self.assertEqual(
                recovered.classify_delivery(_envelope(message_id="MSG-OLD", sequence=1, source_message_id="OLD")),
                ReceiptStatus.REPLAY_REJECTED,
            )


if __name__ == "__main__":
    unittest.main()
