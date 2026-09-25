from __future__ import annotations

import importlib
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import remote_control_envelope as control
from runtime.orchestrator import ocpv2_successor_stage_runtime as stage_runtime
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope
from runtime.orchestrator.successor_release_staging import SuccessorReleaseStageRequest


POLICY_REF = "P2-SUCCESSOR-STAGE"
POLICY_DIGEST = "c" * 64


def _stage_request(*, mode: str = "DRY_RUN", preflight_digest: str | None = None) -> dict:
    return {
        "request_id": "stage-p2-001",
        "schema_version": "orchestration.successor-release-stage-request.v1",
        "project_alias": "successor-p2",
        "expected_branch": "impl/ocp-rdc-independent-primary-path-20260923",
        "expected_head": "a" * 40,
        "target_ref": "refs/heads/impl/ocp-rdc-independent-primary-path-20260923",
        "target_head": "b" * 40,
        "successor_profile": "lifecycle-v2-p2",
        "approval_policy_ref": POLICY_REF,
        "approval_policy_digest": POLICY_DIGEST,
        "mode": mode,
        "preflight_digest": preflight_digest,
    }


def _raw_envelope() -> dict:
    return {
        "schema_version": control.REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": control.SUCCESSOR_RELEASE_STAGE_KIND,
        "message_id": "SUCCESSOR-STAGE-MSG-001",
        "sequence": 1,
        "issued_at": "2026-09-26T00:00:00+00:00",
        "expires_at": "2026-09-26T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "TEST",
            "channel_id": "CTRL",
            "source_actor_id": "235775273",
            "source_message_id": "17",
        },
        "payload": _stage_request(),
        "payload_digest": "0" * 64,
        "authorization": {"successor_release_stage_policy_ref": POLICY_REF},
        "envelope_sha256": "0" * 64,
    }


def _validated_envelope(test: unittest.TestCase):
    try:
        sealed = control.seal_remote_control_envelope(_raw_envelope())
        return control.validate_remote_control_envelope(
            sealed, now=datetime(2026, 9, 26, 0, 5, tzinfo=timezone.utc)
        )
    except Exception as exc:
        test.fail(f"successor stage envelope path is missing: {exc}")


class FakeTransport:
    def __init__(self):
        self.items = (RawControlEnvelope(
            source_repository_id=None,
            source_channel_id="CTRL",
            source_actor_id="235775273",
            source_message_id="17",
            content=b"{}",
            received_at="2026-09-26T00:05:00+00:00",
        ),)
        self.projections: list[dict] = []
        self.acks: list[str] = []

    def receive(self, *, limit=16):
        return self.items[:limit]

    def publish_projection(self, projection):
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)


class SuccessorReleaseStageGatewayTests(unittest.TestCase):
    def _gateway(self):
        spec = importlib.util.find_spec("runtime.orchestrator.successor_release_stage_gateway")
        self.assertIsNotNone(spec, "dedicated successor stage gateway module is missing")
        return importlib.import_module("runtime.orchestrator.successor_release_stage_gateway")

    def test_typed_remote_envelope_binds_stage_policy(self):
        envelope = _validated_envelope(self)
        self.assertEqual(envelope.request_kind, control.SUCCESSOR_RELEASE_STAGE_KIND)
        self.assertEqual(envelope.payload.phase_request_digest, envelope.payload_digest)
        self.assertEqual(envelope.payload.approval_policy_ref, POLICY_REF)
        self.assertIsInstance(envelope.authorization, control.RemoteSuccessorReleaseStageAuthorization)
        self.assertEqual(envelope.authorization.successor_release_stage_policy_ref, POLICY_REF)

    def test_dedicated_gateway_binds_digests_without_raw_command_surface(self):
        gateway = self._gateway()
        request = SuccessorReleaseStageRequest.from_mapping(_stage_request())
        value = gateway.SuccessorReleaseStageGatewayRequest.from_stage_request(request).to_dict()
        self.assertEqual(value["request_kind"], "SUCCESSOR_RELEASE_STAGE")
        self.assertEqual(value["capability_id"], "SUCCESSOR_RELEASE_STAGE")
        self.assertEqual(value["stage_intent_digest"], request.stage_intent_digest)
        self.assertEqual(value["phase_request_digest"], request.phase_request_digest)
        self.assertEqual(value["approval_policy_digest"], POLICY_DIGEST)
        self.assertEqual(len(value["gateway_digest"]), 64)
        forbidden = {"command", "argv", "shell", "systemctl", "refspec"}
        self.assertTrue(forbidden.isdisjoint(value))
        self.assertTrue(forbidden.isdisjoint(value["stage_request"]))

    def test_gateway_rejects_tamper_before_stager(self):
        gateway = self._gateway()
        request = SuccessorReleaseStageRequest.from_mapping(_stage_request())
        value = gateway.SuccessorReleaseStageGatewayRequest.from_stage_request(request).to_dict()
        value["approval_policy_digest"] = "d" * 64
        calls: list[str] = []

        class Stager:
            def execute(self, stage_request):
                calls.append(stage_request.request_id)
                return {"status": "STAGE_READY"}

        with self.assertRaises(gateway.SuccessorReleaseStageGatewayError):
            gateway.dispatch_successor_release_stage(value, stager=Stager())
        self.assertEqual(calls, [])

    def test_dedicated_gateway_is_inside_existing_production_gateway_error_boundary(self):
        from runtime.orchestrator import production_execution_gateway as production_gateway

        gateway = self._gateway()
        self.assertTrue(issubclass(gateway.SuccessorReleaseStageGatewayError, production_gateway.GatewayError))
        self.assertNotIn("SUCCESSOR_RELEASE_STAGE", production_gateway.SUPPORTED_BACKENDS)

    def test_p2_runtime_binds_predecessor_exclusion_to_serving_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "serving"
            repo.mkdir()
            state = root / "state"
            state.mkdir()
            mapping = root / "mapping"
            (mapping / "aliases").mkdir(parents=True)
            config = SimpleNamespace(
                repo_root=repo,
                state_root=state,
                environment={"HARNESS_CONTRACT_MAPPING_ROOT": str(mapping)},
            )
            with patch.object(stage_runtime, "_load_stage_callback", return_value=lambda *args: {}):
                stager = stage_runtime._successor_stager(config)
            identity = stager.lifecycle_identity_provider()
            self.assertEqual(identity.serving_root, repo.resolve())
            self.assertEqual(identity.predecessor_root, repo.resolve())

    def test_remote_service_routes_stage_to_dedicated_callback(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []

        def stage_successor(value):
            calls.append(value.payload.request_id)
            return {
                "schema_version": "orchestration.remote-successor-release-stage-status-projection.v1",
                "message_id": value.message_id,
                "request_id": value.payload.request_id,
                "project_alias": value.payload.project_alias,
                "phase_request_digest": value.payload.phase_request_digest,
                "mode": value.payload.mode,
                "result_class": "STAGE_READY",
            }

        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle successor staging")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle successor staging")),
            stage_successor_authorized=stage_successor,
            successor_release_stage_enabled=True,
            successor_release_stage_policy_ref=POLICY_REF,
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, ["stage-p2-001"])
        self.assertEqual(result.successor_release_staged, 1)
        self.assertEqual(result.blocked, 0)

    def test_remote_service_wrong_configured_policy_fails_closed(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        calls: list[str] = []
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle successor staging")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("generic mutation executor must not handle successor staging")),
            stage_successor_authorized=lambda value: calls.append(value.payload.request_id) or {},
            successor_release_stage_enabled=True,
            successor_release_stage_policy_ref="OTHER-POLICY",
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.blocked, 1)
        self.assertEqual(
            transport.projections[0]["result_class"],
            "SUCCESSOR_RELEASE_STAGE_AUTHORIZATION_MISMATCH",
        )

    def test_runtime_feature_gate_is_explicit_and_fail_closed(self):
        resolver = stage_runtime.successor_release_stage_enabled_from_environment
        self.assertFalse(resolver({}))
        self.assertFalse(resolver({"OCP_SUCCESSOR_RELEASE_STAGE_ENABLED": "true"}))
        self.assertTrue(resolver({"OCP_SUCCESSOR_RELEASE_STAGE_ENABLED": "1"}))


if __name__ == "__main__":
    unittest.main()
