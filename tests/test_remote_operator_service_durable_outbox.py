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
from runtime.orchestrator.remote_operator_ingress import IngressDecision
from runtime.orchestrator.remote_operator_outbox import RemoteResultOutbox
from runtime.orchestrator.remote_operator_service import CanaryScope, ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


def _envelope():
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "MSG-OUTBOX-1",
        "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "TEST",
            "channel_id": "CTRL",
            "source_actor_id": "235775273",
            "source_message_id": "101",
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
            "current_stage": "PREPARE",
            "requested_next_stage": "ACTION",
            "required_capabilities": ["filesystem_write"],
            "state_change_required": True,
            "input_artifact_digests": ["a" * 64],
            "gate_id": "G1",
            "directive_id": "D1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "b" * 64,
            "continuation_owner_epoch": 1,
            "canonical_run_state_sha256": "c" * 64,
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": "e" * 40,
            "runtime_release_digest": "d" * 64,
        },
        "authorization": {
            "risk_envelope_ref": "RISK-1",
            "risk_envelope_digest": "f" * 64,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload),
        now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
    )


def _raw():
    return RawControlEnvelope(
        source_repository_id=None,
        source_channel_id="TEST",
        source_actor_id="235775273",
        source_message_id="101",
        content=b"{}",
        received_at="2026-09-21T00:05:00+00:00",
    )


class Transport:
    def __init__(self, items=(), *, fail_publish=False):
        self.items = tuple(items)
        self.fail_publish = fail_publish
        self.publish_calls = []
        self.acks = []

    def receive(self, *, limit=16):
        return self.items[:limit]

    def publish_projection(self, projection):
        self.publish_calls.append(dict(projection))
        if self.fail_publish:
            raise RuntimeError("transport offline")

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)


class RemoteOperatorServiceDurableOutboxTests(unittest.TestCase):
    def test_publish_failure_survives_restart_and_retries_projection_without_reexecution(self):
        env = _envelope()
        executions = []

        def ingress(value):
            return IngressDecision(
                accepted=True,
                result_class="MESSAGE_RECEIVED",
                message_id=value.message_id,
                directive_digest=value.directive_digest,
                directive=value.operator_directive,
            )

        def execute(value, directive):
            executions.append((value.message_id, directive.directive_id))
            return {
                "result_class": "CANONICAL_ACTION_COMPLETED",
                "canonical_state_ref": "state:R1",
                "canonical_state_sha256": "1" * 64,
                "effect_evidence_refs": ["effect:1"],
                "checkpoint_ref": "checkpoint:R1",
                "checkpoint_sha256": "2" * 64,
                "migration_transaction_sha256": "",
                "result_summary": "done",
            }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outbox1 = RemoteResultOutbox(root)
            first_transport = Transport((_raw(),), fail_publish=True)
            first = RemoteOperatorService(
                transport=first_transport,
                decode_envelope=lambda raw: env,
                ingress=ingress,
                execute_authorized=execute,
                canary_scope=CanaryScope("P1", "R1", "T1", "G1", "D1"),
                result_outbox=outbox1,
            )
            with self.assertRaises(RuntimeError):
                first.poll_once(mode=ControlMode.CONTROL_MUTATION_CANARY)
            self.assertEqual(executions, [(env.message_id, "D1")])
            pending = outbox1.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].result_class, "CANONICAL_ACTION_COMPLETED")

            outbox2 = RemoteResultOutbox(root)
            second_transport = Transport(())
            second = RemoteOperatorService(
                transport=second_transport,
                decode_envelope=lambda raw: env,
                ingress=ingress,
                execute_authorized=execute,
                canary_scope=CanaryScope("P1", "R1", "T1", "G1", "D1"),
                result_outbox=outbox2,
            )
            result = second.poll_once(mode=ControlMode.CONTROL_MUTATION_CANARY)
            self.assertEqual(result.executed, 0)
            self.assertEqual(executions, [(env.message_id, "D1")])
            self.assertEqual(len(second_transport.publish_calls), 1)
            self.assertEqual(second_transport.publish_calls[0]["result_class"], "CANONICAL_ACTION_COMPLETED")
            self.assertEqual(second_transport.acks, [env.message_id])
            self.assertEqual(outbox2.pending(), ())


if __name__ == "__main__":
    unittest.main()
