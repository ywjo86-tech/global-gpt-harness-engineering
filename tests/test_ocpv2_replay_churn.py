from __future__ import annotations

import unittest
from types import SimpleNamespace

from runtime.orchestrator.remote_operator_ingress import IngressDecision
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


class FakeTransport:
    def __init__(self) -> None:
        self.projections: list[dict[str, object]] = []
        self.acks: list[str] = []

    def receive(self, *, limit: int = 16):
        return (
            RawControlEnvelope(
                source_repository_id=1,
                source_channel_id="PR:1",
                source_actor_id="235775273",
                source_message_id="1001",
                content=b"{}",
                received_at="2026-09-21T00:00:00+00:00",
            ),
        )

    def acknowledge_delivery(self, message_id: str) -> None:
        self.acks.append(message_id)

    def publish_projection(self, projection) -> None:
        self.projections.append(dict(projection))


def envelope():
    return SimpleNamespace(
        message_id="MSG-1",
        directive_digest="d" * 64,
        project_id="P1",
        run_id="R1",
        gate_id="G1",
        task_id="T1",
    )


def service_for(result_class: str):
    env = envelope()
    transport = FakeTransport()
    service = RemoteOperatorService(
        transport=transport,
        decode_envelope=lambda raw: env,
        ingress=lambda value: IngressDecision(
            accepted=False,
            result_class=result_class,
            message_id=value.message_id,
            directive_digest=value.directive_digest,
            directive=None,
        ),
        execute_authorized=lambda value, directive: {},
    )
    return service, transport


class ReplayChurnRegressionTests(unittest.TestCase):
    def test_idempotent_replay_is_silent_and_acknowledged(self):
        service, transport = service_for("IDEMPOTENT_REPLAY")

        result = service.poll_once(mode=ControlMode.OBSERVE_ONLY)

        self.assertEqual(transport.projections, [])
        self.assertEqual(transport.acks, ["MSG-1"])
        self.assertEqual(result.projected, 0)
        self.assertEqual(result.acknowledged, 1)
        self.assertEqual(result.blocked, 0)

    def test_tamper_detected_remains_visible_and_blocked(self):
        service, transport = service_for("TAMPER_DETECTED")

        result = service.poll_once(mode=ControlMode.OBSERVE_ONLY)

        self.assertEqual(len(transport.projections), 1)
        self.assertEqual(transport.projections[0]["result_class"], "TAMPER_DETECTED")
        self.assertEqual(transport.acks, ["MSG-1"])
        self.assertEqual(result.projected, 1)
        self.assertEqual(result.acknowledged, 1)
        self.assertEqual(result.blocked, 1)

    def test_replay_rejected_remains_visible_and_blocked(self):
        service, transport = service_for("REPLAY_REJECTED")

        result = service.poll_once(mode=ControlMode.OBSERVE_ONLY)

        self.assertEqual(len(transport.projections), 1)
        self.assertEqual(transport.projections[0]["result_class"], "REPLAY_REJECTED")
        self.assertEqual(transport.acks, ["MSG-1"])
        self.assertEqual(result.projected, 1)
        self.assertEqual(result.acknowledged, 1)
        self.assertEqual(result.blocked, 1)


if __name__ == "__main__":
    unittest.main()
