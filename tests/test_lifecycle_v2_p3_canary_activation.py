from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator import remote_control_envelope as control
from runtime.orchestrator.lifecycle_v2_p3_canary_activation import (
    LifecycleV2P3CanaryActivationError,
    LifecycleV2P3CanaryActivationRequest,
    evaluate_p3_canary_activation,
)
from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionEvidence,
    LifecycleV2P3PromotionAdmissionRequest,
    evaluate_p3_promotion_admission,
)
from runtime.orchestrator.ocpv2_runtime_service import finalize_remote_control_projection
from runtime.orchestrator.remote_operator_envelope import TransportBinding
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


POLICY_REF = "LIFECYCLE-V2-P3-CANARY"
POLICY_DIGEST = "d" * 64
CANDIDATE = "p3-canary-20260926-01"
BRANCH = "p2/harness-lifecycle-v2-successor-20260925"
HEAD = "a" * 40


def _admission_request(**changes) -> dict:
    value = {
        "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
        "request_id": "p3-admission-001",
        "project_alias": "harness-lifecycle-v2-successor-20260925",
        "expected_branch": BRANCH,
        "expected_head": HEAD,
        "successor_profile": "lifecycle-v2-p2",
        "current_phase": "P2_SIDE_BY_SIDE",
        "requested_phase": "P3_CANARY",
        "candidate_run_id": CANDIDATE,
        "candidate_run_origin": "FRESH_ACTIVATION",
        "approval_policy_ref": POLICY_REF,
        "approval_policy_digest": POLICY_DIGEST,
        "mode": "DRY_RUN",
        "predecessor_serving_required": True,
        "predecessor_quiesce_requested": False,
        "runtime_current_switch_requested": False,
        "existing_run_migration_requested": False,
        "canary_scope": [CANDIDATE],
    }
    value.update(changes)
    return value


def _evidence(**changes) -> LifecycleV2P3PromotionAdmissionEvidence:
    value = {
        "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1",
        "project_alias": "harness-lifecycle-v2-successor-20260925",
        "observed_branch": BRANCH,
        "observed_head": HEAD,
        "observed_successor_profile": "lifecycle-v2-p2",
        "candidate_run_id": CANDIDATE,
        "candidate_run_registration_state": "ABSENT",
        "predecessor_serving": True,
        "runtime_current_points_to_predecessor": True,
        "approved_policy_ref": POLICY_REF,
        "approved_policy_digest": POLICY_DIGEST,
    }
    value.update(changes)
    return LifecycleV2P3PromotionAdmissionEvidence.from_mapping(value)


def _admission_result():
    request = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_admission_request())
    return evaluate_p3_promotion_admission(request, _evidence())


def _full_plan_activation(**changes) -> dict:
    value = {
        "schema_version": "orchestration.approved-full-plan-activation-request.v1",
        "activation_request_id": CANDIDATE,
        "project_alias": "harness-lifecycle-v2-successor-20260925",
        "approved_plan": {"path": "APPROVED_PLAN.md", "sha256": "1" * 64},
        "approved_spec": {"path": "APPROVED_SPEC.md", "sha256": "2" * 64},
        "expected_branch": BRANCH,
        "expected_head": HEAD,
        "runtime_release_digest": "3" * 64,
        "approval_ref": "APR-P3-CANARY-001",
        "gate_bindings": [
            {
                "gate_id": "GATE-001",
                "approval_evidence": {"path": "approval.json", "sha256": "4" * 64},
                "engine_requirement_evidence": None,
                "project_requirement_evidence_by_lv": [],
            }
        ],
    }
    value.update(changes)
    return value


def _request(**changes) -> dict:
    admission = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_admission_request())
    result = _admission_result()
    value = {
        "schema_version": "orchestration.lifecycle-v2-p3-canary-activation-request.v1",
        "request_id": "p3-canary-activation-001",
        "admission_request": admission.to_dict(),
        "admission_request_digest": admission.request_digest,
        "admission_evidence_digest": result.evidence_digest,
        "admission_digest": result.admission_digest,
        "admission_status": "P3_CANARY_ADMISSION_READY",
        "full_plan_activation": _full_plan_activation(),
    }
    value.update(changes)
    return value


def _raw_envelope() -> dict:
    return {
        "schema_version": control.REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": control.LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND,
        "message_id": "P3-CANARY-ACTIVATION-MSG-001",
        "sequence": 1,
        "issued_at": "2026-09-26T12:00:00+00:00",
        "expires_at": "2026-09-26T13:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "TEST",
            "channel_id": "CTRL",
            "source_actor_id": "235775273",
            "source_message_id": "41",
        },
        "payload": _request(),
        "payload_digest": "0" * 64,
        "authorization": {"lifecycle_v2_p3_canary_activation_policy_ref": POLICY_REF},
        "envelope_sha256": "0" * 64,
    }


def _validated_envelope(test: unittest.TestCase):
    try:
        sealed = control.seal_remote_control_envelope(_raw_envelope())
        return control.validate_remote_control_envelope(
            sealed, now=datetime(2026, 9, 26, 12, 5, tzinfo=timezone.utc)
        )
    except Exception as exc:
        test.fail(f"P3 bounded canary activation envelope path is missing: {exc}")


class FakeTransport:
    def __init__(self):
        self.items = (
            RawControlEnvelope(
                source_repository_id=None,
                source_channel_id="CTRL",
                source_actor_id="235775273",
                source_message_id="41",
                content=b"{}",
                received_at="2026-09-26T12:05:00+00:00",
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


class ExplodingOutbox:
    def mark_published(self, *args, **kwargs):
        raise AssertionError("status-only P3 canary projection must not touch durable result outbox")


class LifecycleV2P3CanaryActivationTests(unittest.TestCase):
    def test_contract_authorizes_only_exact_admitted_candidate(self):
        request = LifecycleV2P3CanaryActivationRequest.from_mapping(_request())
        result = evaluate_p3_canary_activation(request, _admission_result())
        self.assertEqual(result.status, "P3_CANARY_ACTIVATION_AUTHORIZED")
        self.assertEqual(result.canary_run_id, CANDIDATE)
        self.assertTrue(result.candidate_run_registration_authorized)
        self.assertFalse(result.runtime_current_switch_authorized)
        self.assertFalse(result.existing_run_migration_authorized)
        self.assertFalse(result.predecessor_shutdown_authorized)
        self.assertFalse(result.generic_mutation_authorized)

    def test_prior_admission_binding_is_exact_and_fail_closed(self):
        good = _request()
        for field in ("admission_request_digest", "admission_evidence_digest", "admission_digest"):
            with self.subTest(field=field):
                value = dict(good)
                value[field] = "f" * 64
                with self.assertRaises(LifecycleV2P3CanaryActivationError):
                    request = LifecycleV2P3CanaryActivationRequest.from_mapping(value)
                    evaluate_p3_canary_activation(request, _admission_result())
        value = dict(good)
        value["admission_status"] = "BLOCKED"
        with self.assertRaises(LifecycleV2P3CanaryActivationError):
            LifecycleV2P3CanaryActivationRequest.from_mapping(value)

    def test_full_plan_activation_must_be_same_single_fresh_candidate(self):
        bad_inner = (
            {"activation_request_id": "other-run"},
            {"project_alias": "other-project"},
            {"expected_branch": "other/branch"},
            {"expected_head": "b" * 40},
        )
        for changes in bad_inner:
            with self.subTest(changes=changes):
                value = _request(full_plan_activation=_full_plan_activation(**changes))
                with self.assertRaises(LifecycleV2P3CanaryActivationError):
                    LifecycleV2P3CanaryActivationRequest.from_mapping(value)

    def test_request_exposes_no_runtime_switch_quiesce_migration_or_generic_execution_surface(self):
        value = LifecycleV2P3CanaryActivationRequest.from_mapping(_request()).to_dict()
        forbidden = {
            "command", "argv", "shell", "systemctl", "backend", "provider", "model",
            "runtime_current_target", "migration_run_ids", "predecessor_quiesce",
        }
        self.assertTrue(forbidden.isdisjoint(value))

    def test_remote_envelope_uses_distinct_p3_activation_authorization(self):
        envelope = _validated_envelope(self)
        self.assertEqual(envelope.request_kind, control.LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND)
        self.assertIsInstance(envelope.authorization, control.RemoteLifecycleV2P3CanaryActivationAuthorization)
        self.assertEqual(envelope.authorization.lifecycle_v2_p3_canary_activation_policy_ref, POLICY_REF)
        self.assertEqual(envelope.payload.request_digest, envelope.payload_digest)

    def test_envelope_policy_must_match_admission_policy(self):
        raw = _raw_envelope()
        raw["authorization"]["lifecycle_v2_p3_canary_activation_policy_ref"] = "OTHER-POLICY"
        sealed = control.seal_remote_control_envelope(raw)
        with self.assertRaises(control.RemoteControlEnvelopeError):
            control.validate_remote_control_envelope(
                sealed, now=datetime(2026, 9, 26, 12, 5, tzinfo=timezone.utc)
            )

    def test_remote_service_is_disabled_by_default_and_callback_missing_fails_closed(self):
        envelope = _validated_envelope(self)
        for enabled, callback, expected in (
            (False, lambda value: {}, "P3_CANARY_ACTIVATION_DISABLED"),
            (True, None, "P3_CANARY_ACTIVATION_DISABLED"),
        ):
            with self.subTest(enabled=enabled, callback=callback):
                transport = FakeTransport()
                service = RemoteOperatorService(
                    transport=transport,
                    decode_envelope=lambda raw: envelope,
                    ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle P3 activation")),
                    execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle P3 activation")),
                    activate_p3_canary_authorized=callback,
                    lifecycle_v2_p3_canary_activation_enabled=enabled,
                    lifecycle_v2_p3_canary_activation_policy_ref=POLICY_REF,
                )
                result = service.poll_once(mode=ControlMode.LIFECYCLE_V2_P3_CANARY)
                self.assertEqual(result.p3_canary_activated, 0)
                self.assertEqual(result.blocked, 1)
                self.assertEqual(transport.projections[0]["result_class"], expected)

    def test_p3_activation_cannot_run_under_generic_canary_or_active_mode(self):
        envelope = _validated_envelope(self)
        for mode in (ControlMode.CONTROL_MUTATION_CANARY, ControlMode.ACTIVE, ControlMode.CONTROL_READ_ONLY):
            with self.subTest(mode=mode):
                transport = FakeTransport()
                calls: list[str] = []
                service = RemoteOperatorService(
                    transport=transport,
                    decode_envelope=lambda raw: envelope,
                    ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle P3 activation")),
                    execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle P3 activation")),
                    activate_p3_canary_authorized=lambda value: calls.append(value.payload.request_id) or {},
                    lifecycle_v2_p3_canary_activation_enabled=True,
                    lifecycle_v2_p3_canary_activation_policy_ref=POLICY_REF,
                )
                result = service.poll_once(mode=mode)
                self.assertEqual(calls, [])
                self.assertEqual(result.blocked, 1)
                self.assertEqual(transport.projections[0]["result_class"], "MODE_BLOCKED")

    def test_dedicated_mode_routes_only_to_p3_callback(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle P3 activation")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle P3 activation")),
            activate_p3_canary_authorized=lambda value: calls.append(value.payload.request_id) or {
                "schema_version": "orchestration.remote-p3-canary-activation-status-projection.v1",
                "message_id": value.message_id,
                "request_id": value.payload.request_id,
                "project_alias": value.payload.admission_request.project_alias,
                "request_digest": value.payload.request_digest,
                "candidate_run_id": value.payload.admission_request.candidate_run_id,
                "result_class": "P3_CANARY_ACTIVATED",
            },
            lifecycle_v2_p3_canary_activation_enabled=True,
            lifecycle_v2_p3_canary_activation_policy_ref=POLICY_REF,
        )
        result = service.poll_once(mode=ControlMode.LIFECYCLE_V2_P3_CANARY)
        self.assertEqual(calls, ["p3-canary-activation-001"])
        self.assertEqual(result.p3_canary_activated, 1)
        self.assertEqual(result.blocked, 0)
        self.assertEqual(transport.projections[0]["result_class"], "P3_CANARY_ACTIVATED")

    def test_dedicated_mode_leaves_unrelated_remote_controls_unconsumed(self):
        unrelated = control.RemoteControlEnvelopeV1(
            schema_version=control.REMOTE_CONTROL_ENVELOPE_SCHEMA,
            request_kind=control.HOST_INSPECTION_KIND,
            message_id="UNRELATED-CONTROL-001",
            sequence=2,
            issued_at="2026-09-26T12:00:00+00:00",
            expires_at="2026-09-26T13:00:00+00:00",
            actor="GPT_OPERATOR",
            transport=TransportBinding(
                adapter_id="TEST",
                channel_id="CTRL",
                source_actor_id="235775273",
                source_message_id="41",
            ),
            payload=object(),
            payload_digest="a" * 64,
            authorization=control.RemoteControlAuthorization("READ-ONLY"),
            envelope_sha256="b" * 64,
        )
        transport = FakeTransport()
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: unrelated,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not run")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not run")),
            activate_p3_canary_authorized=lambda value: (_ for _ in ()).throw(AssertionError("P3 callback must not run")),
            lifecycle_v2_p3_canary_activation_enabled=True,
            lifecycle_v2_p3_canary_activation_policy_ref=POLICY_REF,
        )
        result = service.poll_once(mode=ControlMode.LIFECYCLE_V2_P3_CANARY)
        self.assertEqual(result.received, 1)
        self.assertEqual(result.validated, 1)
        self.assertEqual(result.blocked, 0)
        self.assertEqual(transport.projections, [])
        self.assertEqual(transport.acks, [])

    def test_p3_canary_status_projection_is_not_reparsed_as_durable_result(self):
        finalize_remote_control_projection(
            ExplodingOutbox(),
            {
                "schema_version": "orchestration.remote-p3-canary-activation-status-projection.v1",
                "message_id": "P3-CANARY-ACTIVATION-MSG-001",
                "request_id": "p3-canary-activation-001",
                "project_alias": "harness-lifecycle-v2-successor-20260925",
                "request_digest": "c" * 64,
                "candidate_run_id": CANDIDATE,
                "result_class": "P3_CANARY_ACTIVATED",
            },
        )

    def test_p3_activation_is_not_a_new_production_execution_backend(self):
        from runtime.orchestrator import production_execution_gateway

        self.assertNotIn(
            "LIFECYCLE_V2_P3_CANARY_ACTIVATION",
            production_execution_gateway.SUPPORTED_BACKENDS,
        )


if __name__ == "__main__":
    unittest.main()
