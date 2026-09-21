from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import datetime, timezone

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    RemoteOperatorEnvelopeError,
    RemoteOperatorEnvelopeV2,
    seal_remote_envelope,
)
from runtime.orchestrator.operator_console_projection import (
    OperatorConsoleProjectionV1,
    build_operator_console_projection,
    normalize_console_control_request,
)


def _console_envelope_payload():
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "MSG-CONSOLE-1",
        "sequence": 1,
        "issued_at": "2026-09-21T06:00:00+00:00",
        "expires_at": "2026-09-21T07:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "CTRL-1",
            "source_actor_id": "235775273",
            "source_message_id": "CONSOLE-501",
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
            "directive_id": "D-CONSOLE-1",
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
    return seal_remote_envelope(payload)


class OperatorConsoleProjectionTests(unittest.TestCase):
    def test_projection_exposes_only_authorized_read_model_fields(self):
        projection = build_operator_console_projection(
            {
                "project_id": "P1",
                "run_id": "R1",
                "task_id": "T1",
                "gate_id": "G1",
                "stage": "VERIFY",
                "execution_readiness": "READY",
                "operator_authority_label": "GPT_OPERATOR",
                "checkpoint_refs": ["checkpoint:R1"],
                "evidence_refs": ["evidence:effect-1"],
                "migration_phase": "ACTIVE_RUNTIME_QUALIFICATION",
                "migration_transaction_sha256": "a" * 64,
                "token": "ghp_SHOULD_NEVER_APPEAR",
                "provider": "FORBIDDEN_PROVIDER_FIELD",
                "model": "FORBIDDEN_MODEL_FIELD",
            },
            transport_state="OBSERVE_ONLY",
            status_flags=("BLOCKED", "STALE_DIRECTIVE"),
        )
        self.assertIsInstance(projection, OperatorConsoleProjectionV1)
        self.assertEqual(projection.project_id, "P1")
        self.assertEqual(projection.stage, "VERIFY")
        self.assertEqual(projection.transport_state, "OBSERVE_ONLY")
        self.assertEqual(projection.checkpoint_refs, ("checkpoint:R1",))
        self.assertEqual(projection.evidence_refs, ("evidence:effect-1",))
        self.assertEqual(projection.migration_phase, "ACTIVE_RUNTIME_QUALIFICATION")
        serialized = json.dumps(projection.to_dict(), sort_keys=True)
        self.assertNotIn("ghp_SHOULD_NEVER_APPEAR", serialized)
        self.assertNotIn("FORBIDDEN_PROVIDER_FIELD", serialized)
        self.assertNotIn("FORBIDDEN_MODEL_FIELD", serialized)
        self.assertNotIn("token", projection.to_dict())
        self.assertNotIn("provider", projection.to_dict())
        self.assertNotIn("model", projection.to_dict())

    def test_projection_is_frozen_non_authoritative_data(self):
        projection = build_operator_console_projection(
            {"project_id": "P1", "run_id": "R1", "task_id": "T1", "gate_id": "G1", "stage": "ENTRY"},
            transport_state="DISABLED",
            status_flags=(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            projection.stage = "ACTION"
        self.assertFalse(hasattr(projection, "complete_gate"))
        self.assertFalse(hasattr(projection, "mutate_canonical_state"))

    def test_console_control_request_reuses_remote_envelope_validation_path(self):
        envelope = normalize_console_control_request(
            _console_envelope_payload(),
            now=datetime(2026, 9, 21, 6, 5, tzinfo=timezone.utc),
        )
        self.assertIsInstance(envelope, RemoteOperatorEnvelopeV2)
        self.assertEqual(envelope.operator_directive.directive_id, "D-CONSOLE-1")
        self.assertFalse(envelope.operator_directive.state_change_required)

    def test_console_request_cannot_add_provider_or_model_authority(self):
        payload = _console_envelope_payload()
        payload["operator_directive"]["provider"] = "nvidia"
        with self.assertRaises(RemoteOperatorEnvelopeError):
            normalize_console_control_request(
                payload,
                now=datetime(2026, 9, 21, 6, 5, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
