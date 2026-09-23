from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA,
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    RemoteOperatorEnvelopeError,
    RemoteOperatorEnvelopeV2,
    RemoteOperatorEnvelopeV3,
    canonical_envelope_bytes,
    seal_remote_control_envelope,
    seal_remote_envelope,
    validate_remote_control_envelope,
    validate_remote_envelope,
)


def _payload(**changes):
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": "MSG-0001",
        "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T00:10:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "CTRL-1",
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
            "continuation_owner_epoch": 3,
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
    payload.update(changes)
    return seal_remote_envelope(payload)


def _diagnostic_payload(**changes):
    payload = _payload()
    payload["schema_version"] = REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA
    payload["operator_directive"].update({
        "current_stage": "PREPARE",
        "requested_next_stage": "VERIFY",
        "required_capabilities": ["read_only_host_diagnostic"],
        "state_change_required": False,
        "input_artifact_digests": [],
    })
    payload["read_only_request"] = {
        "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
        "request_id": "REQ-1",
        "operation": "repo.snapshot",
        "root_id": "project",
        "relative_path": "",
        "start_line": 0,
        "line_count": 0,
        "service_id": "",
    }
    payload["read_only_request_digest"] = ""
    payload.update(changes)
    return seal_remote_control_envelope(payload)


class RemoteOperatorEnvelopeTests(unittest.TestCase):
    def test_valid_envelope_round_trips_and_binds_existing_directive(self):
        env = validate_remote_envelope(
            _payload(), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(env.message_id, "MSG-0001")
        self.assertEqual(env.operator_directive.directive_id, "D1")
        self.assertEqual(env.directive_digest, env.operator_directive.directive_digest)
        self.assertEqual(env.envelope_sha256, seal_remote_envelope(env.to_dict())["envelope_sha256"])
        self.assertTrue(canonical_envelope_bytes(env.to_dict()))

    def test_unknown_top_level_field_is_rejected(self):
        payload = _payload()
        payload["extra"] = "forbidden"
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "SCHEMA_REJECTED"):
            validate_remote_envelope(payload, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))

    def test_expired_envelope_is_rejected(self):
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "DIRECTIVE_EXPIRED"):
            validate_remote_envelope(_payload(), now=datetime(2026, 9, 21, 0, 11, tzinfo=timezone.utc))

    def test_invalid_time_order_and_sequence_are_rejected(self):
        with self.assertRaises(RemoteOperatorEnvelopeError):
            validate_remote_envelope(
                _payload(sequence=0), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
            )
        bad = _payload(expires_at="2026-09-20T23:59:00+00:00")
        with self.assertRaises(RemoteOperatorEnvelopeError):
            validate_remote_envelope(bad, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))

    def test_actor_must_be_gpt_operator(self):
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "ACTOR_NOT_ALLOWED"):
            validate_remote_envelope(
                _payload(actor="OTHER"), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
            )

    def test_directive_identity_mismatch_is_rejected(self):
        payload = _payload()
        payload["operator_directive"]["run_id"] = "OTHER"
        payload = seal_remote_envelope(payload)
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "OPERATOR_DIRECTIVE_BLOCKED"):
            validate_remote_envelope(payload, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))

    def test_provider_and_model_fields_stay_forbidden(self):
        for field in ("provider", "model", "provider_ref", "model_ref"):
            with self.subTest(field=field):
                payload = _payload()
                payload["operator_directive"][field] = "forbidden"
                with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "OPERATOR_DIRECTIVE_BLOCKED"):
                    seal_remote_envelope(payload)

    def test_state_change_requires_continuation_digest_and_epoch(self):
        payload = _payload()
        payload["expected"]["continuation_state_sha256"] = ""
        payload = seal_remote_envelope(payload)
        with self.assertRaises(RemoteOperatorEnvelopeError):
            validate_remote_envelope(payload, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))

    def test_digest_tamper_is_rejected(self):
        payload = _payload()
        payload["message_id"] = "MSG-TAMPERED"
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "DIGEST_MISMATCH"):
            validate_remote_envelope(payload, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))

    def test_v2_api_remains_v2_and_round_trips_unchanged(self):
        env = validate_remote_envelope(
            _payload(), now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
        )
        self.assertIsInstance(env, RemoteOperatorEnvelopeV2)
        self.assertEqual(seal_remote_control_envelope(env.to_dict()), seal_remote_envelope(env.to_dict()))

    def test_v3_diagnostic_envelope_round_trips_with_typed_request(self):
        payload = _diagnostic_payload()
        env = validate_remote_control_envelope(
            payload, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
        )
        self.assertIsInstance(env, RemoteOperatorEnvelopeV3)
        self.assertEqual(env.read_only_request.request_id, "REQ-1")
        self.assertEqual(env.read_only_request_digest, env.read_only_request.request_digest)
        self.assertFalse(env.operator_directive.state_change_required)
        self.assertEqual(env.operator_directive.required_capabilities, ("read_only_host_diagnostic",))
        self.assertEqual(seal_remote_control_envelope(env.to_dict())["envelope_sha256"], env.envelope_sha256)

    def test_v3_request_digest_drift_is_rejected(self):
        payload = _diagnostic_payload()
        payload["read_only_request"]["request_id"] = "REQ-TAMPERED"
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "DIGEST_MISMATCH"):
            validate_remote_control_envelope(payload, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc))

    def test_v3_requires_non_mutating_exact_diagnostic_capability(self):
        payload = _diagnostic_payload()
        payload["operator_directive"]["required_capabilities"] = []
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "diagnostic capability"):
            seal_remote_control_envelope(payload)

        payload = _diagnostic_payload()
        payload["operator_directive"].update({
            "current_stage": "ENTRY", "requested_next_stage": "PREPARE",
            "state_change_required": True,
        })
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "state change"):
            seal_remote_control_envelope(payload)

    def test_v3_requires_literal_false_and_exact_capability_list(self):
        for value in (0, "", None):
            payload = _diagnostic_payload()
            payload["operator_directive"]["state_change_required"] = value
            payload["envelope_sha256"] = ""
            with self.subTest(state_change_required=value), self.assertRaisesRegex(RemoteOperatorEnvelopeError, "literal false"):
                seal_remote_control_envelope(payload)

        payload = _diagnostic_payload()
        payload["operator_directive"]["required_capabilities"] = [
            "read_only_host_diagnostic", "read_only_host_diagnostic"
        ]
        payload["envelope_sha256"] = ""
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "capability.*exact"):
            seal_remote_control_envelope(payload)

    def test_v3_rejects_provider_fields_and_absolute_root_id(self):
        payload = _diagnostic_payload()
        payload["operator_directive"]["provider"] = "forbidden"
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "OPERATOR_DIRECTIVE_BLOCKED"):
            seal_remote_control_envelope(payload)

        payload = _diagnostic_payload()
        payload["read_only_request"]["root_id"] = "/home/ywjo/project"
        with self.assertRaisesRegex(RemoteOperatorEnvelopeError, "diagnostic request"):
            seal_remote_control_envelope(payload)


if __name__ == "__main__":
    unittest.main()
