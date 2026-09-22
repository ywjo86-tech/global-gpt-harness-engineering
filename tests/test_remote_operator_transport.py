from __future__ import annotations

import inspect
import unittest

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA, OperatorDirectiveV1
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope, RemoteOperatorTransport


class FakeTransport:
    def __init__(self, items=()):
        self._items = tuple(items)
        self.acks = []
        self.projections = []

    def receive(self, *, limit=16):
        return self._items[:limit]

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)

    def publish_projection(self, projection):
        self.projections.append(dict(projection))


class RemoteOperatorTransportTests(unittest.TestCase):
    def test_fake_transport_drives_data_boundary_without_vendor_import(self):
        raw = RawControlEnvelope(
            source_repository_id=987654321,
            source_channel_id="CTRL-PR-1",
            source_actor_id="235775273",
            source_message_id="101",
            content=b'{"schema_version":"example"}',
            received_at="2026-09-21T00:00:00+00:00",
        )
        transport = FakeTransport((raw,))
        self.assertEqual(transport.receive(limit=1), (raw,))
        transport.acknowledge_delivery("MSG-1")
        transport.publish_projection({"projection_id": "PROJ-1"})
        self.assertEqual(transport.acks, ["MSG-1"])
        self.assertEqual(transport.projections, [{"projection_id": "PROJ-1"}])
        self.assertNotIn("github", inspect.getsource(__import__("runtime.orchestrator.remote_operator_transport", fromlist=["*"])).lower())

    def test_no_transport_keeps_existing_local_harness_contract_usable(self):
        directive = OperatorDirectiveV1.from_mapping({
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1",
            "run_id": "R1",
            "task_id": "T1",
            "task_execution_id": "E1",
            "current_stage": "ENTRY",
            "requested_next_stage": "PREPARE",
            "required_capabilities": ["reasoning"],
            "state_change_required": False,
            "input_artifact_digests": [],
            "gate_id": "G1",
            "directive_id": "D1",
        })
        self.assertEqual(directive.requested_next_stage, "PREPARE")

    def test_transport_contract_has_no_canonical_mutation_method(self):
        public = {name for name in RemoteOperatorTransport.__dict__ if not name.startswith("_")}
        self.assertEqual(public, {"receive", "acknowledge_delivery", "publish_projection"})
        forbidden = {
            "execute", "mutate", "advance", "dispatch_action", "select_provider",
            "select_model", "run_shell", "write_file", "commit", "merge",
        }
        self.assertFalse(public.intersection(forbidden))

    def test_raw_envelope_is_immutable_and_transport_only(self):
        raw = RawControlEnvelope(
            source_repository_id=None,
            source_channel_id="LOCAL",
            source_actor_id="GPT_OPERATOR",
            source_message_id="1",
            content=b"{}",
            received_at="2026-09-21T00:00:00+00:00",
        )
        with self.assertRaises(Exception):
            raw.source_message_id = "2"  # type: ignore[misc]
        self.assertEqual(
            tuple(RawControlEnvelope.__dataclass_fields__),
            (
                "source_repository_id", "source_channel_id", "source_actor_id",
                "source_message_id", "content", "received_at",
            ),
        )


if __name__ == "__main__":
    unittest.main()
