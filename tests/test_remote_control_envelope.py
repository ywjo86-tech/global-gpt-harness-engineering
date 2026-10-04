from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.approved_full_plan_activation_contract import ApprovedFullPlanActivationRequestV1
from runtime.orchestrator.approved_work_binding import ApprovedWorkActivationRequestV1
from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1
from runtime.orchestrator.remote_control_envelope import (
    APPROVED_FULL_PLAN_ACTIVATION_KIND,
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    RemoteFullPlanActivationAuthorization,
    RemoteWorkActivationAuthorization,
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


def activation_payload(**changes):
    request = ApprovedWorkActivationRequestV1.from_mapping({
        "schema_version": "orchestration.approved-work-activation-request.v1",
        "activation_request_id": "ACT-1", "project_alias": "global-gpt-harness-engineering",
        "approved_plan_path": "docs/PLAN.md", "approved_plan_sha256": "a" * 64,
        "approved_spec_path": "docs/SPEC.md", "approved_spec_sha256": "b" * 64,
        "requirement_artifact_path": "docs/requirements.json", "requirement_artifact_sha256": "c" * 64,
        "approval_ref": "approval:user", "expected_branch": "main", "expected_head": "d" * 40,
        "task_ids": ["T1", "T2"], "runtime_release_digest": "e" * 64,
    })
    value = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA, "request_kind": "APPROVED_WORK_ACTIVATION",
        "message_id": "MSG-A1", "sequence": 3,
        "issued_at": "2026-09-23T00:00:00+00:00", "expires_at": "2026-09-23T00:10:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {"adapter_id": "GITHUB_CONTROL_V1", "channel_id": "PR:7", "source_actor_id": "235775273", "source_message_id": "203"},
        "payload": request.to_dict(), "payload_digest": "",
        "authorization": {"activation_policy_ref": "ACTIVATION-POLICY-1"}, "envelope_sha256": "",
    }
    value.update(changes)
    return seal_remote_control_envelope(value)


def full_plan_activation_payload(**changes):
    request = ApprovedFullPlanActivationRequestV1.from_mapping({
        "schema_version": "orchestration.approved-full-plan-activation-request.v1",
        "activation_request_id": "FP-ACT-1", "project_alias": "global-gpt-harness-engineering",
        "approved_plan": {"path": "docs/PLAN.md", "sha256": "1" * 64},
        "approved_spec": {"path": "docs/SPEC.md", "sha256": "2" * 64},
        "expected_branch": "main", "expected_head": "3" * 40,
        "runtime_release_digest": "4" * 64, "approval_ref": "approval:user:full-plan",
        "gate_bindings": [{
            "gate_id": "GATE-001",
            "approval_evidence": {"path": "gate-001.json", "sha256": "5" * 64},
            "engine_requirement_evidence": {"path": "engine-001.json", "sha256": "6" * 64},
            "project_requirement_evidence_by_lv": [{
                "lv_id": "TASK-001", "path": "docs/task-001.requirements.json", "sha256": "7" * 64,
            }],
        }],
    })
    value = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "APPROVED_FULL_PLAN_ACTIVATION",
        "message_id": "MSG-FP1", "sequence": 4,
        "issued_at": "2026-09-23T00:00:00+00:00", "expires_at": "2026-09-23T00:10:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {"adapter_id": "GITHUB_CONTROL_V1", "channel_id": "PR:7", "source_actor_id": "235775273", "source_message_id": "204"},
        "payload": request.to_dict(), "payload_digest": "",
        "authorization": {"full_plan_activation_policy_ref": "FP-POLICY-1"}, "envelope_sha256": "",
    }
    value.update(changes)
    return seal_remote_control_envelope(value)


class RemoteControlEnvelopeTests(unittest.TestCase):
    def test_executable_full_plan_activation_has_distinct_kind_and_policy_ref(self):
        sealed = full_plan_activation_payload()
        value = validate_remote_control_envelope(sealed, now=NOW)
        self.assertEqual(value.request_kind, APPROVED_FULL_PLAN_ACTIVATION_KIND)
        self.assertIsInstance(value.authorization, RemoteFullPlanActivationAuthorization)
        self.assertEqual(value.authorization.full_plan_activation_policy_ref, "FP-POLICY-1")
        self.assertEqual(value.payload.activation_request_id, "FP-ACT-1")

    def test_v1_activation_authorization_class_remains_unchanged(self):
        value = validate_remote_control_envelope(activation_payload(), now=NOW)
        self.assertEqual(value.request_kind, "APPROVED_WORK_ACTIVATION")
        self.assertIsInstance(value.authorization, RemoteWorkActivationAuthorization)
        self.assertEqual(value.authorization.activation_policy_ref, "ACTIVATION-POLICY-1")

    def test_host_inspection_envelope_round_trips(self):
        value = inspection_payload()
        envelope = validate_remote_control_envelope(value, now=NOW)
        self.assertEqual(envelope.request_kind, "HOST_INSPECTION")
        self.assertEqual(envelope.payload.operation, "git.status")
        self.assertEqual(envelope.payload_digest, envelope.payload.request_digest)
        self.assertEqual(decode_remote_control_payload(value, now=NOW), envelope)


    def test_approved_work_activation_envelope_round_trips(self):
        value = activation_payload()
        envelope = validate_remote_control_envelope(value, now=NOW)
        self.assertEqual(envelope.request_kind, "APPROVED_WORK_ACTIVATION")
        self.assertEqual(envelope.payload.activation_request_id, "ACT-1")
        self.assertEqual(envelope.payload_digest, envelope.payload.request_digest)
        self.assertEqual(decode_remote_control_payload(value, now=NOW), envelope)

    def test_activation_rejects_ambiguous_or_authority_bearing_payload(self):
        for field in ("provider", "model", "backend", "state_change_required"):
            with self.subTest(field=field):
                raw = activation_payload()
                raw["payload"][field] = True if field == "state_change_required" else "forbidden"
                with self.assertRaises(RemoteControlEnvelopeError):
                    seal_remote_control_envelope(raw)
        raw = activation_payload()
        raw["payload"]["approval_ref"] = ""
        with self.assertRaises(RemoteControlEnvelopeError):
            seal_remote_control_envelope(raw)

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
