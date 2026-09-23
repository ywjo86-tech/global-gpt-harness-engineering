from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    RemoteControlEnvelopeError,
    decode_remote_control_payload,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_envelope import RemoteOperatorEnvelopeV2
from tests.test_remote_operator_envelope import _payload as legacy_v2_payload


NOW = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)


def inspection_payload(**changes):
    request = HostInspectionRequestV1.from_mapping({
        "schema_version": "orchestration.host-inspection-request.v1",
        "request_id": "INSP-1", "correlation_id": "CORR-1",
        "project_alias": "global-gpt-harness-engineering",
        "operation": "git.status", "arguments": {},
        "state_change_required": False,
    })
    value = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "HOST_INSPECTION",
        "message_id": "MSG-I1", "sequence": 2,
        "issued_at": "2026-09-23T00:00:00+00:00",
        "expires_at": "2026-09-23T00:10:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "PR:7", "source_actor_id": "235775273",
            "source_message_id": "202",
        },
        "payload": request.to_dict(), "payload_digest": "",
        "authorization": {"inspection_policy_ref": "POLICY-1"},
        "envelope_sha256": "",
    }
    value.update(changes)
    return seal_remote_control_envelope(value)


class RemoteControlEnvelopeTests(unittest.TestCase):
    def test_host_inspection_envelope_round_trips(self):
        value = inspection_payload()
        envelope = validate_remote_control_envelope(value, now=NOW)
        self.assertEqual(envelope.request_kind, "HOST_INSPECTION")
        self.assertEqual(envelope.payload.operation, "git.status")
        self.assertEqual(envelope.payload_digest, envelope.payload.request_digest)
        self.assertEqual(decode_remote_control_payload(value, now=NOW), envelope)

    def test_unknown_kind_and_extra_authority_fields_are_rejected(self):
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "request kind"):
            inspection_payload(request_kind="UNKNOWN")
        for field in ("provider", "model", "backend"):
            with self.subTest(field=field):
                value = inspection_payload()
                value[field] = "forbidden"
                with self.assertRaisesRegex(RemoteControlEnvelopeError, "fields"):
                    validate_remote_control_envelope(value, now=NOW)

    def test_payload_digest_and_envelope_digest_drift_fail_closed(self):
        value = inspection_payload()
        value["payload"]["operation"] = "git.branch"
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "payload digest"):
            validate_remote_control_envelope(value, now=NOW)
        value = inspection_payload()
        value["message_id"] = "MSG-TAMPER"
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "envelope digest"):
            validate_remote_control_envelope(value, now=NOW)

    def test_expired_and_state_changing_inspection_are_rejected(self):
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "expired"):
            validate_remote_control_envelope(
                inspection_payload(), now=datetime(2026, 9, 23, 0, 11, tzinfo=timezone.utc)
            )
        raw = inspection_payload()
        raw["payload"]["state_change_required"] = True
        raw["payload_digest"] = "0" * 64
        with self.assertRaises(RemoteControlEnvelopeError):
            seal_remote_control_envelope(raw)

    def test_decoder_preserves_existing_v2_contract(self):
        legacy = legacy_v2_payload()
        decoded = decode_remote_control_payload(
            legacy, now=datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
        )
        self.assertIsInstance(decoded, RemoteOperatorEnvelopeV2)
        self.assertEqual(decoded.envelope_sha256, legacy["envelope_sha256"])

    def test_unknown_schema_is_rejected(self):
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "schema"):
            decode_remote_control_payload({"schema_version": "unknown"}, now=NOW)


if __name__ == "__main__":
    unittest.main()
