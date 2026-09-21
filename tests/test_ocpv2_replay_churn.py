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


class ReplayChurnRegressionTests(unittest.TestCase):
    def test_idempotent_replay_is_silent_and_acknowledged(self):
        envelope = SimpleNamespace(
            message_id="MSG-1",
            directive_digest="d" * 64,
            project_id="P1",
            run_id="R1",
            gate_id="G1",
            task_id="T1",
        )
        transport = FakeTransport()
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: IngressDecision(
                accepted=False,
                result_class="IDEMPOTENT_REPLAY",
                message_id=env.message_id,
                directive_digest=env.directive_digest,
                directive=None,
            ),
            execute_authorized=lambda env, directive: {},
        )

        result = service.poll_once(mode=ControlMode.OBSERVE_ONLY)

        self.assertEqual(transport.projections, [])
        self.assertEqual(transport.acks, ["MSG-1"])
        self.assertEqual(result.projected, 0)
        self.assertEqual(result.acknowledged, 1)
        self.assertEqual(result.blocked, 0)


if __name__ == "__main__":
    unittest.main()
