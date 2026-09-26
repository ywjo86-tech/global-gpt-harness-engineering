from __future__ import annotations

import importlib
import importlib.util
import unittest
from datetime import datetime, timezone

from runtime.orchestrator import remote_control_envelope as control
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


POLICY_REF = "LIFECYCLE-V2-P3-PROMOTION"
POLICY_DIGEST = "d" * 64
EXPECTED_HEAD = "a" * 40


def _promotion_request(**overrides) -> dict:
    value = {
        "request_id": "p3-promotion-001",
        "schema_version": "orchestration.lifecycle-v2-p3-promotion-request.v1",
        "project_alias": "successor-p3",
        "lifecycle_profile": "lifecycle-v2",
        "expected_phase": "P2",
        "target_phase": "P3",
        "expected_head": EXPECTED_HEAD,
        "approval_policy_ref": POLICY_REF,
        "approval_policy_digest": POLICY_DIGEST,
        "mode": "DRY_RUN",
        "fresh_run": True,
        "existing_run_migration_allowed": False,
        "predecessor_serving_required": True,
        "runtime_current_mutation_allowed": False,
        "canary_scope": {
            "project_id": "HARNESS-LIFECYCLE-V2-SUCCESSOR-20260925",
            "run_id": "P3-CANARY-FRESH-001",
            "task_id": "P3-CANARY-TASK-001",
            "gate_id": "P3-CANARY",
            "directive_id": "P3-CANARY-DIRECTIVE-001",
        },
    }
    value.update(overrides)
    return value


def _raw_envelope() -> dict:
    return {
        "schema_version": control.REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": control.LIFECYCLE_V2_P3_PROMOTION_KIND,
        "message_id": "P3-PROMOTION-MSG-001",
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
        "payload": _promotion_request(),
        "payload_digest": "0" * 64,
        "authorization": {"lifecycle_v2_p3_promotion_policy_ref": POLICY_REF},
        "envelope_sha256": "0" * 64,
    }


def _validated_envelope(test: unittest.TestCase):
    try:
        sealed = control.seal_remote_control_envelope(_raw_envelope())
        return control.validate_remote_control_envelope(
            sealed,
            now=datetime(2026, 9, 26, 3, 5, tzinfo=timezone.utc),
        )
    except Exception as exc:
        test.fail(f"P3 promotion envelope path is missing: {exc}")


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
    def _contract(self):
        spec = importlib.util.find_spec("runtime.orchestrator.lifecycle_v2_p3_promotion")
        self.assertIsNotNone(spec, "P3 promotion contract module is missing")
        return importlib.import_module("runtime.orchestrator.lifecycle_v2_p3_promotion")

    def _gateway(self):
        spec = importlib.util.find_spec("runtime.orchestrator.lifecycle_v2_p3_promotion_gateway")
        self.assertIsNotNone(spec, "P3 promotion gateway module is missing")
        return importlib.import_module("runtime.orchestrator.lifecycle_v2_p3_promotion_gateway")

    def test_request_is_dry_run_only_and_binds_p2_to_p3(self):
        contract = self._contract()
        request = contract.LifecycleV2P3PromotionRequest.from_mapping(_promotion_request())
        self.assertEqual(request.expected_phase, "P2")
        self.assertEqual(request.target_phase, "P3")
        self.assertEqual(request.mode, "DRY_RUN")
        self.assertTrue(request.fresh_run)
        self.assertFalse(request.existing_run_migration_allowed)
        self.assertTrue(request.predecessor_serving_required)
        self.assertFalse(request.runtime_current_mutation_allowed)
        self.assertEqual(len(request.request_digest), 64)

    def test_request_rejects_any_effectful_or_migration_shape(self):
        contract = self._contract()
        invalid = (
            {"mode": "STAGE"},
            {"fresh_run": False},
            {"existing_run_migration_allowed": True},
            {"predecessor_serving_required": False},
            {"runtime_current_mutation_allowed": True},
            {"expected_phase": "P3"},
            {"target_phase": "P4"},
        )
        for override in invalid:
            with self.subTest(override=override):
                with self.assertRaises(contract.LifecycleV2P3PromotionError):
                    contract.LifecycleV2P3PromotionRequest.from_mapping(
                        _promotion_request(**override)
                    )

    def test_request_rejects_incomplete_canary_scope(self):
        contract = self._contract()
        value = _promotion_request()
        value["canary_scope"] = dict(value["canary_scope"])
        value["canary_scope"].pop("directive_id")
        with self.assertRaises(contract.LifecycleV2P3PromotionError):
            contract.LifecycleV2P3PromotionRequest.from_mapping(value)

    def test_remote_envelope_binds_independent_p3_policy(self):
        envelope = _validated_envelope(self)
        self.assertEqual(envelope.request_kind, control.LIFECYCLE_V2_P3_PROMOTION_KIND)
        self.assertEqual(envelope.payload.request_digest, envelope.payload_digest)
        self.assertIsInstance(
            envelope.authorization,
            control.RemoteLifecycleV2P3PromotionAuthorization,
        )
        self.assertEqual(
            envelope.authorization.lifecycle_v2_p3_promotion_policy_ref,
            POLICY_REF,
        )

    def test_gateway_has_no_execution_or_service_manager_surface(self):
        contract = self._contract()
        gateway = self._gateway()
        request = contract.LifecycleV2P3PromotionRequest.from_mapping(_promotion_request())
        value = gateway.LifecycleV2P3PromotionGatewayRequest.from_promotion_request(
            request
        ).to_dict()
        self.assertEqual(value["request_kind"], "LIFECYCLE_V2_P3_PROMOTION")
        self.assertEqual(value["capability_id"], "LIFECYCLE_V2_P3_PROMOTION_DRY_RUN")
        self.assertEqual(value["request_digest"], request.request_digest)
        forbidden = {
            "command",
            "argv",
            "shell",
            "systemctl",
            "service",
            "timer",
            "runtime_current",
            "migration",
            "activate",
        }
        self.assertTrue(forbidden.isdisjoint(value))
        self.assertTrue(forbidden.isdisjoint(value["promotion_request"]))

    def test_remote_service_routes_only_enabled_matching_policy(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []

        def check_promotion(value):
            calls.append(value.payload.request_id)
            return {
                "schema_version": "orchestration.remote-lifecycle-v2-p3-promotion-status-projection.v1",
                "message_id": value.message_id,
                "request_id": value.payload.request_id,
                "project_alias": value.payload.project_alias,
                "request_digest": value.payload.request_digest,
                "mode": value.payload.mode,
                "result_class": "PROMOTION_READY",
                "mutation_performed": False,
            }

        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(
                AssertionError("legacy ingress must not handle P3 promotion")
            ),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(
                AssertionError("generic mutation executor must not handle P3 promotion")
            ),
            check_lifecycle_v2_p3_promotion_authorized=check_promotion,
            lifecycle_v2_p3_promotion_enabled=True,
            lifecycle_v2_p3_promotion_policy_ref=POLICY_REF,
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, ["p3-promotion-001"])
        self.assertEqual(result.lifecycle_v2_p3_promotion_checked, 1)
        self.assertEqual(result.blocked, 0)
        self.assertEqual(transport.projections[0]["result_class"], "PROMOTION_READY")

    def test_remote_service_is_disabled_by_default(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress called")),
            execute_authorized=lambda env, directive: {},
            check_lifecycle_v2_p3_promotion_authorized=lambda value: calls.append(
                value.payload.request_id
            ) or {},
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.blocked, 1)
        self.assertEqual(result.lifecycle_v2_p3_promotion_checked, 0)
        self.assertEqual(
            transport.projections[0]["result_class"],
            "LIFECYCLE_V2_P3_PROMOTION_DISABLED",
        )


if __name__ == "__main__":
    unittest.main()
