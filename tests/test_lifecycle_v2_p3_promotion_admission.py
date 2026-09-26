from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator import remote_control_envelope as control
from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionError,
    LifecycleV2P3PromotionAdmissionEvidence,
    LifecycleV2P3PromotionAdmissionRequest,
    evaluate_p3_promotion_admission,
)
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


POLICY_REF = "LIFECYCLE-V2-P3-CANARY"
POLICY_DIGEST = "d" * 64


def _request(**changes) -> dict:
    value = {
        "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
        "request_id": "p3-admission-001",
        "project_alias": "harness-lifecycle-v2-successor-20260925",
        "expected_branch": "p2/harness-lifecycle-v2-successor-20260925",
        "expected_head": "a" * 40,
        "successor_profile": "lifecycle-v2-p2",
        "current_phase": "P2_SIDE_BY_SIDE",
        "requested_phase": "P3_CANARY",
        "candidate_run_id": "fresh-canary-run-001",
        "candidate_run_origin": "FRESH_ACTIVATION",
        "approval_policy_ref": POLICY_REF,
        "approval_policy_digest": POLICY_DIGEST,
        "mode": "DRY_RUN",
        "predecessor_serving_required": True,
        "predecessor_quiesce_requested": False,
        "runtime_current_switch_requested": False,
        "existing_run_migration_requested": False,
        "canary_scope": ["fresh-canary-run-001"],
    }
    value.update(changes)
    return value


def _evidence(**changes) -> dict:
    value = {
        "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1",
        "project_alias": "harness-lifecycle-v2-successor-20260925",
        "observed_branch": "p2/harness-lifecycle-v2-successor-20260925",
        "observed_head": "a" * 40,
        "observed_successor_profile": "lifecycle-v2-p2",
        "candidate_run_id": "fresh-canary-run-001",
        "candidate_run_registration_state": "ABSENT",
        "predecessor_serving": True,
        "runtime_current_points_to_predecessor": True,
        "approved_policy_ref": POLICY_REF,
        "approved_policy_digest": POLICY_DIGEST,
    }
    value.update(changes)
    return value


def _validated_evidence(**changes) -> LifecycleV2P3PromotionAdmissionEvidence:
    return LifecycleV2P3PromotionAdmissionEvidence.from_mapping(_evidence(**changes))


def _raw_envelope() -> dict:
    return {
        "schema_version": control.REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": control.LIFECYCLE_V2_P3_PROMOTION_ADMISSION_KIND,
        "message_id": "P3-ADMISSION-MSG-001",
        "sequence": 1,
        "issued_at": "2026-09-26T03:00:00+00:00",
        "expires_at": "2026-09-26T04:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "TEST",
            "channel_id": "CTRL",
            "source_actor_id": "235775273",
            "source_message_id": "31",
        },
        "payload": _request(),
        "payload_digest": "0" * 64,
        "authorization": {"lifecycle_v2_p3_promotion_policy_ref": POLICY_REF},
        "envelope_sha256": "0" * 64,
    }


def _validated_envelope(test: unittest.TestCase):
    try:
        sealed = control.seal_remote_control_envelope(_raw_envelope())
        return control.validate_remote_control_envelope(
            sealed, now=datetime(2026, 9, 26, 3, 5, tzinfo=timezone.utc)
        )
    except Exception as exc:
        test.fail(f"P3 promotion admission envelope path is missing: {exc}")


class FakeTransport:
    def __init__(self):
        self.items = (
            RawControlEnvelope(
                source_repository_id=None,
                source_channel_id="CTRL",
                source_actor_id="235775273",
                source_message_id="31",
                content=b"{}",
                received_at="2026-09-26T03:05:00+00:00",
            ),
        )
        self.projections: list[dict] = []
        self.acks: list[str] = []

    def receive(self, *, limit=16):
        return self.items[:limit]

    def publish_projection(self, projection):
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)


class LifecycleV2P3PromotionAdmissionTests(unittest.TestCase):
    def test_valid_dry_run_requires_observed_evidence_and_is_non_mutating(self):
        request = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_request())
        evidence = _validated_evidence()
        result = evaluate_p3_promotion_admission(request, evidence)
        self.assertEqual(result.status, "P3_CANARY_ADMISSION_READY")
        self.assertEqual(result.canary_run_id, "fresh-canary-run-001")
        self.assertFalse(result.mutation_authorized)
        self.assertFalse(result.runtime_current_switch_authorized)
        self.assertFalse(result.existing_run_migration_authorized)
        self.assertFalse(result.predecessor_shutdown_authorized)
        self.assertEqual(len(result.evidence_digest), 64)
        self.assertEqual(len(result.admission_digest), 64)
        self.assertEqual(
            result.admission_digest,
            evaluate_p3_promotion_admission(request, evidence).admission_digest,
        )

    def test_missing_observed_evidence_fails_closed(self):
        request = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_request())
        with self.assertRaises(LifecycleV2P3PromotionAdmissionError):
            evaluate_p3_promotion_admission(request, None)

    def test_observed_identity_policy_and_fresh_run_must_match_request(self):
        request = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_request())
        bad_evidence = (
            {"project_alias": "other-project"},
            {"observed_branch": "other/branch"},
            {"observed_head": "b" * 40},
            {"observed_successor_profile": "other-profile"},
            {"candidate_run_id": "other-run"},
            {"candidate_run_registration_state": "REGISTERED"},
            {"predecessor_serving": False},
            {"runtime_current_points_to_predecessor": False},
            {"approved_policy_ref": "OTHER-POLICY"},
            {"approved_policy_digest": "e" * 64},
        )
        for changes in bad_evidence:
            with self.subTest(changes=changes):
                evidence = _validated_evidence(**changes)
                with self.assertRaises(LifecycleV2P3PromotionAdmissionError):
                    evaluate_p3_promotion_admission(request, evidence)

    def test_only_p2_to_p3_dry_run_is_accepted(self):
        bad_values = (
            {"mode": "PROMOTE"},
            {"current_phase": "P3_CANARY"},
            {"requested_phase": "P4_RUNTIME_CURRENT"},
            {"successor_profile": "lifecycle-v2-p3"},
        )
        for changes in bad_values:
            with self.subTest(changes=changes):
                with self.assertRaises(LifecycleV2P3PromotionAdmissionError):
                    LifecycleV2P3PromotionAdmissionRequest.from_mapping(_request(**changes))

    def test_existing_run_migration_runtime_switch_and_predecessor_shutdown_fail_closed(self):
        bad_values = (
            {"candidate_run_origin": "EXISTING_RUN"},
            {"candidate_run_origin": "IN_PROGRESS_RUN"},
            {"existing_run_migration_requested": True},
            {"runtime_current_switch_requested": True},
            {"predecessor_serving_required": False},
            {"predecessor_quiesce_requested": True},
        )
        for changes in bad_values:
            with self.subTest(changes=changes):
                with self.assertRaises(LifecycleV2P3PromotionAdmissionError):
                    LifecycleV2P3PromotionAdmissionRequest.from_mapping(_request(**changes))

    def test_request_has_no_generic_execution_surface(self):
        value = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_request()).to_dict()
        forbidden = {
            "command",
            "argv",
            "shell",
            "systemctl",
            "backend",
            "provider",
            "model",
            "runtime_current_target",
            "migration_run_ids",
        }
        self.assertTrue(forbidden.isdisjoint(value))

    def test_typed_remote_envelope_binds_distinct_p3_policy(self):
        envelope = _validated_envelope(self)
        self.assertEqual(
            envelope.request_kind,
            control.LIFECYCLE_V2_P3_PROMOTION_ADMISSION_KIND,
        )
        self.assertEqual(envelope.payload.request_digest, envelope.payload_digest)
        self.assertIsInstance(
            envelope.authorization,
            control.RemoteLifecycleV2P3PromotionAuthorization,
        )
        self.assertEqual(
            envelope.authorization.lifecycle_v2_p3_promotion_policy_ref,
            POLICY_REF,
        )

    def test_envelope_policy_must_match_payload_policy(self):
        raw = _raw_envelope()
        raw["authorization"]["lifecycle_v2_p3_promotion_policy_ref"] = "OTHER-POLICY"
        sealed = control.seal_remote_control_envelope(raw)
        with self.assertRaises(control.RemoteControlEnvelopeError):
            control.validate_remote_control_envelope(
                sealed, now=datetime(2026, 9, 26, 3, 5, tzinfo=timezone.utc)
            )

    def test_remote_service_is_disabled_by_default(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle P3 admission")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle P3 admission")),
            admit_p3_promotion_authorized=lambda value: calls.append(value.payload.request_id) or {},
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.p3_promotion_admitted, 0)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(transport.projections[0]["result_class"], "P3_PROMOTION_ADMISSION_DISABLED")

    def test_remote_service_routes_only_to_read_only_admission_callback(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []

        def admit(value):
            calls.append(value.payload.request_id)
            result = evaluate_p3_promotion_admission(value.payload, _validated_evidence())
            return {
                "schema_version": "orchestration.remote-p3-promotion-admission-status-projection.v1",
                "message_id": value.message_id,
                "request_id": value.payload.request_id,
                "request_digest": value.payload.request_digest,
                "mode": value.payload.mode,
                "result_class": result.status,
                "evidence_digest": result.evidence_digest,
                "admission_digest": result.admission_digest,
            }

        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle P3 admission")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle P3 admission")),
            admit_p3_promotion_authorized=admit,
            lifecycle_v2_p3_promotion_enabled=True,
            lifecycle_v2_p3_promotion_policy_ref=POLICY_REF,
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, ["p3-admission-001"])
        self.assertEqual(result.p3_promotion_admitted, 1)
        self.assertEqual(result.blocked, 0)
        self.assertEqual(transport.projections[0]["result_class"], "P3_CANARY_ADMISSION_READY")

    def test_remote_service_wrong_policy_fails_closed(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle P3 admission")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle P3 admission")),
            admit_p3_promotion_authorized=lambda value: calls.append(value.payload.request_id) or {},
            lifecycle_v2_p3_promotion_enabled=True,
            lifecycle_v2_p3_promotion_policy_ref="OTHER-POLICY",
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.blocked, 1)
        self.assertEqual(
            transport.projections[0]["result_class"],
            "P3_PROMOTION_ADMISSION_AUTHORIZATION_MISMATCH",
        )

    def test_p3_admission_is_not_a_production_execution_backend(self):
        from runtime.orchestrator import production_execution_gateway

        self.assertNotIn(
            "LIFECYCLE_V2_P3_PROMOTION_ADMISSION",
            production_execution_gateway.SUPPORTED_BACKENDS,
        )


if __name__ == "__main__":
    unittest.main()
