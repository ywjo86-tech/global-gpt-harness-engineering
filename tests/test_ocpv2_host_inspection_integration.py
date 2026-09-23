from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1
from runtime.orchestrator.host_inspection_port import HostInspectionPort
from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    seal_remote_envelope,
    validate_remote_envelope,
)
from runtime.orchestrator.remote_operator_ingress import IngressDecision
from runtime.orchestrator.remote_operator_outbox import RemoteInspectionProjectionV1, RemoteResultOutbox
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


class _Transport:
    def __init__(self, item):
        self.item = item; self.projections = []; self.acks = []
    def receive(self, *, limit=16): return (self.item,)[:limit]
    def publish_projection(self, value): self.projections.append(dict(value))
    def acknowledge_delivery(self, message_id): self.acks.append(message_id)


def _raw(source_message_id="11"):
    return RawControlEnvelope(
        source_repository_id=None, source_channel_id="TEST", source_actor_id="235775273",
        source_message_id=source_message_id, content=b"{}", received_at="2026-09-21T00:05:00+00:00",
    )


class OCPv2HostInspectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.project = self.base / "demo"; self.project.mkdir()
        (self.project / "IMPLEMENTATION_PLAN.md").write_text("# approved plan\n", encoding="utf-8")
        (self.project / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "baseline"], cwd=self.project, check=True, capture_output=True)
        self.mapping_root = self.base / "mapping"
        report = OnboardingRegistry(self.mapping_root / "aliases").register(self.project, "demo")
        self.assertEqual(report["status"], "REGISTERED")
        self.runner_calls = []
        def runner(argv):
            self.runner_calls.append(tuple(argv))
            return type("Done", (), {"returncode": 0, "stdout": "ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0\n", "stderr": ""})()
        self.port = HostInspectionPort(
            registry_root=self.mapping_root, read_scopes=(".",),
            allowed_service_units=frozenset({"ocpv2.service"}), service_runner=runner,
        )

    def tearDown(self): self.tmp.cleanup()

    @staticmethod
    def request(operation, arguments=None):
        return HostInspectionRequestV1.from_mapping({
            "schema_version": "orchestration.host-inspection-request.v1",
            "request_id": "INSP-1", "correlation_id": "CORR-1", "project_alias": "demo",
            "operation": operation, "arguments": arguments or {}, "state_change_required": False,
        })

    def test_registered_real_git_and_filesystem_reads_are_bounded(self):
        branch = self.port.inspect(self.request("git.branch")); self.assertEqual(branch.data["branch"], "main")
        read = self.port.inspect(self.request("filesystem.read", {"path": "notes.txt", "max_bytes": 64}))
        self.assertEqual(read.data["text"], "alpha\nbeta\n")
        meta = self.port.inspect(self.request("filesystem.metadata", {"path": "notes.txt"}))
        self.assertEqual(meta.data["kind"], "REGULAR_FILE")
        search = self.port.inspect(self.request("filesystem.search", {"root": ".", "query": "beta", "max_matches": 2}))
        self.assertEqual(search.data["match_count"], 1)
        (self.project / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        status = self.port.inspect(self.request("git.status")); self.assertFalse(status.data["clean"])
        diff = self.port.inspect(self.request("git.diff", {"paths": ["notes.txt"], "max_bytes": 4096}))
        self.assertIn("+gamma", diff.data["diff"])

    def test_service_observer_allowlist_and_shared_outbox_retry(self):
        service = self.port.inspect(self.request("user_service.properties", {"unit_id": "ocpv2.service"}))
        self.assertEqual(service.data["ActiveState"], "active")
        blocked = self.port.inspect(self.request("user_service.properties", {"unit_id": "ssh.service"}))
        self.assertEqual((blocked.status, blocked.error_code), ("BLOCKED", "UNIT_NOT_ALLOWED"))
        self.assertEqual(len(self.runner_calls), 1)
        result = self.port.inspect(self.request("git.branch"))
        projection = RemoteInspectionProjectionV1.from_result(result, message_id="MSG-I1")
        outbox = RemoteResultOutbox(self.base / "outbox"); outbox.enqueue_projection(projection)
        with self.assertRaises(RuntimeError): outbox.publish_pending(lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
        published = []; restarted = RemoteResultOutbox(self.base / "outbox")
        self.assertEqual(restarted.publish_pending(lambda value: published.append(value)), 1)
        self.assertEqual(published, [projection])

    def inspection_envelope(self):
        req = self.request("git.branch")
        value = {
            "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA, "request_kind": "HOST_INSPECTION",
            "message_id": "MSG-I1", "sequence": 1, "issued_at": "2026-09-21T00:00:00+00:00",
            "expires_at": "2026-09-21T01:00:00+00:00", "actor": "GPT_OPERATOR",
            "transport": {"adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273", "source_message_id": "11"},
            "payload": req.to_dict(), "payload_digest": "", "authorization": {"inspection_policy_ref": "POLICY-1"}, "envelope_sha256": "",
        }
        return validate_remote_control_envelope(seal_remote_control_envelope(value), now=datetime(2026,9,21,0,5,tzinfo=timezone.utc))

    def mutation_envelope(self):
        value = {
            "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA, "message_id": "MSG-M1", "sequence": 1,
            "issued_at": "2026-09-21T00:00:00+00:00", "expires_at": "2026-09-21T01:00:00+00:00", "actor": "GPT_OPERATOR",
            "transport": {"adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273", "source_message_id": "12"},
            "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1", "gate_id": "G1",
            "operator_directive": {"schema_version": OPERATOR_DIRECTIVE_SCHEMA, "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1", "current_stage": "PREPARE", "requested_next_stage": "ACTION", "required_capabilities": ["filesystem_write"], "state_change_required": True, "input_artifact_digests": ["a"*64], "gate_id": "G1", "directive_id": "D1"},
            "directive_digest": "", "expected": {"continuation_state_sha256": "b"*64, "continuation_owner_epoch": 1, "canonical_run_state_sha256": "c"*64, "migration_id": "", "migration_transaction_sha256": "", "migration_phase": "", "qualification_evidence_sha256": "", "source_head": "d"*40, "runtime_release_digest": "e"*64},
            "authorization": {"risk_envelope_ref": "RISK-1", "risk_envelope_digest": "f"*64, "manual_action_authorization_digest": ""}, "envelope_sha256": "",
        }
        return validate_remote_envelope(seal_remote_envelope(value), now=datetime(2026,9,21,0,5,tzinfo=timezone.utc))

    def test_inspection_has_zero_mutation_and_legacy_v2_mutation_still_executes(self):
        inspected = []; mutated = []
        env = self.inspection_envelope(); transport = _Transport(_raw("11"))
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: env,
            ingress=lambda _: (_ for _ in ()).throw(AssertionError("inspection entered mutation ingress")),
            execute_authorized=lambda *_: mutated.append("wrong"),
            inspect_authorized=lambda e: RemoteInspectionProjectionV1.from_result(self.port.inspect(e.payload), message_id=e.message_id).to_dict(),
            host_inspection_enabled=True,
        )
        result = service.poll_once(mode=ControlMode.ACTIVE); inspected.append(result.inspected)
        self.assertEqual((inspected, mutated, result.executed), ([1], [], 0))

        mutation = self.mutation_envelope(); transport2 = _Transport(_raw("12"))
        def accepted(envelope):
            return IngressDecision(True, "MESSAGE_RECEIVED", envelope.message_id, envelope.directive_digest, envelope.operator_directive)
        service2 = RemoteOperatorService(
            transport=transport2, decode_envelope=lambda _: mutation, ingress=accepted,
            execute_authorized=lambda e, d: mutated.append((e.message_id, d.directive_id)) or {"result_class": "CANONICAL_ACTION_COMPLETED"},
        )
        result2 = service2.poll_once(mode=ControlMode.ACTIVE)
        self.assertEqual((result2.executed, mutated), (1, [("MSG-M1", "D1")]))


if __name__ == "__main__":
    unittest.main()
