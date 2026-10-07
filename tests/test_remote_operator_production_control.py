import unittest

from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from tests.test_production_control_contract import NOW, envelope_payload
from runtime.orchestrator.remote_control_envelope import validate_remote_control_envelope


class FakeTransport:
    def __init__(self):
        self.acks = []
        self.projections = []

    def receive(self, *, limit=16):
        return (object(),)

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)

    def publish_projection(self, projection):
        self.projections.append(dict(projection))


class RemoteOperatorProductionControlTests(unittest.TestCase):
    def _service(self, *, mode=ControlMode.ACTIVE, enabled=True, policy_ref="OCP-FULL-PLAN-TEST-1"):
        envelope = validate_remote_control_envelope(envelope_payload(), now=NOW)
        transport = FakeTransport()
        calls = []

        def callback(value):
            calls.append(value.payload.request_id)
            return {
                "status": "VERIFIED",
                "result_class": "FAKE_PRODUCTION_CONTROL_VERIFIED",
                "effect_digest": "1" * 64,
                "evidence_refs": ["effect:fake"],
                "evidence_digests": ["2" * 64],
                "approval_ref": "must-not-leak",
            }

        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: None,
            execute_authorized=lambda env, directive: {},
            execute_production_control_authorized=callback,
            production_control_enabled=enabled,
            production_control_policy_ref=policy_ref,
        )
        return service, transport, calls, mode

    def test_active_exact_policy_executes_once(self):
        service, transport, calls, mode = self._service()
        result = service.poll_once(mode=mode)
        self.assertEqual(result.production_control_actions, 1)
        self.assertEqual(calls, ["PC-REQ-1"])
        self.assertEqual(transport.acks, ["MSG-PC-1"])
        self.assertEqual(
            transport.projections[0]["result_class"],
            "FAKE_PRODUCTION_CONTROL_VERIFIED",
        )
        self.assertNotIn("approval_ref", transport.projections[0])

    def test_disabled_feature_blocks_without_callback(self):
        service, transport, calls, mode = self._service(enabled=False)
        result = service.poll_once(mode=mode)
        self.assertEqual(result.production_control_actions, 0)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(calls, [])
        self.assertEqual(
            transport.projections[0]["result_class"],
            "PRODUCTION_CONTROL_ACTION_DISABLED",
        )

    def test_service_policy_mismatch_blocks(self):
        service, transport, calls, mode = self._service(policy_ref="OTHER-POLICY")
        result = service.poll_once(mode=mode)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(calls, [])
        self.assertEqual(
            transport.projections[0]["result_class"],
            "PRODUCTION_CONTROL_AUTHORIZATION_MISMATCH",
        )

    def test_read_only_mode_blocks_state_change(self):
        service, transport, calls, _ = self._service(mode=ControlMode.CONTROL_READ_ONLY)
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(calls, [])
        self.assertEqual(transport.projections[0]["result_class"], "MODE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
