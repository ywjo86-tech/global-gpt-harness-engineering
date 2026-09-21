from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA, OperatorDirectiveV1
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    seal_remote_envelope,
    validate_remote_envelope,
)
from runtime.orchestrator.remote_operator_ingress import (
    prepare_existing_operator_directive,
    validate_ingress,
)
from runtime.orchestrator.remote_operator_receipt import RemoteOperatorReceiptStore


def _env(*, adapter="GITHUB_CONTROL_V1", channel="CTRL-1", actor="235775273", risk="f" * 64):
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "MSG-INGRESS-1",
        "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": adapter,
            "channel_id": channel,
            "source_actor_id": actor,
            "source_message_id": "501",
        },
        "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1", "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1",
            "current_stage": "ENTRY", "requested_next_stage": "PREPARE",
            "required_capabilities": ["reasoning"], "state_change_required": False,
            "input_artifact_digests": [], "gate_id": "G1", "directive_id": "D-INGRESS-1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "", "continuation_owner_epoch": 0,
            "canonical_run_state_sha256": "", "migration_id": "", "migration_transaction_sha256": "",
            "migration_phase": "", "qualification_evidence_sha256": "", "source_head": "", "runtime_release_digest": "",
        },
        "authorization": {
            "risk_envelope_ref": "RISK-1" if risk else "", "risk_envelope_digest": risk,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(seal_remote_envelope(payload), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))


class RemoteOperatorIngressTests(unittest.TestCase):
    def test_valid_envelope_returns_existing_operator_directive(self):
        with tempfile.TemporaryDirectory() as td:
            env = _env()
            directive = prepare_existing_operator_directive(env)
            self.assertIsInstance(directive, OperatorDirectiveV1)
            decision = validate_ingress(
                env,
                receipt_store=RemoteOperatorReceiptStore(Path(td)),
                allowed_adapter_id="GITHUB_CONTROL_V1",
                allowed_channel_id="CTRL-1",
                allowed_source_actor_ids=("235775273",),
                expected_risk_envelope_digest="f" * 64,
            )
            self.assertTrue(decision.accepted)
            self.assertEqual(decision.result_class, "MESSAGE_RECEIVED")
            self.assertEqual(decision.directive.directive_id, "D-INGRESS-1")

    def test_adapter_channel_and_source_allowlists_fail_closed(self):
        cases = [
            (_env(adapter="BAD"), "GITHUB_CONTROL_V1", "CTRL-1", ("235775273",)),
            (_env(channel="BAD"), "GITHUB_CONTROL_V1", "CTRL-1", ("235775273",)),
            (_env(actor="999"), "GITHUB_CONTROL_V1", "CTRL-1", ("235775273",)),
        ]
        for env, adapter, channel, actors in cases:
            with self.subTest(env=env.transport):
                with tempfile.TemporaryDirectory() as td:
                    decision = validate_ingress(
                        env, receipt_store=RemoteOperatorReceiptStore(Path(td)),
                        allowed_adapter_id=adapter, allowed_channel_id=channel,
                        allowed_source_actor_ids=actors, expected_risk_envelope_digest="f" * 64,
                    )
                    self.assertFalse(decision.accepted)
                    self.assertEqual(decision.result_class, "SOURCE_NOT_ALLOWED")

    def test_risk_envelope_mismatch_fails_before_receipt_commit(self):
        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            env = _env()
            decision = validate_ingress(
                env, receipt_store=store, allowed_adapter_id="GITHUB_CONTROL_V1", allowed_channel_id="CTRL-1",
                allowed_source_actor_ids=("235775273",), expected_risk_envelope_digest="0" * 64,
            )
            self.assertFalse(decision.accepted)
            self.assertEqual(decision.result_class, "AUTHORIZATION_SCOPE_MISMATCH")
            self.assertEqual(store.classify_delivery(env).value, "NEW")

    def test_duplicate_is_idempotent_and_never_reaccepted_for_execution(self):
        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            env = _env()
            first = validate_ingress(
                env, receipt_store=store, allowed_adapter_id="GITHUB_CONTROL_V1", allowed_channel_id="CTRL-1",
                allowed_source_actor_ids=("235775273",), expected_risk_envelope_digest="f" * 64,
            )
            second = validate_ingress(
                env, receipt_store=store, allowed_adapter_id="GITHUB_CONTROL_V1", allowed_channel_id="CTRL-1",
                allowed_source_actor_ids=("235775273",), expected_risk_envelope_digest="f" * 64,
            )
            self.assertTrue(first.accepted)
            self.assertFalse(second.accepted)
            self.assertEqual(second.result_class, "IDEMPOTENT_REPLAY")

    def test_tamper_is_blocked_before_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            first = _env()
            store.record_received(first)
            payload = first.to_dict()
            payload["transport"]["source_message_id"] = "DIFFERENT"
            payload["sequence"] = 2
            tampered = validate_remote_envelope(seal_remote_envelope(payload), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))
            decision = validate_ingress(
                tampered, receipt_store=store, allowed_adapter_id="GITHUB_CONTROL_V1", allowed_channel_id="CTRL-1",
                allowed_source_actor_ids=("235775273",), expected_risk_envelope_digest="f" * 64,
            )
            self.assertFalse(decision.accepted)
            self.assertEqual(decision.result_class, "TAMPER_DETECTED")


if __name__ == "__main__":
    unittest.main()
