from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from runtime.ai_office.activation import coordinate_approved_activation
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.orchestrator.approved_work_binding import validate_approved_work_binding
from runtime.orchestrator.gate_orchestrator import REQUIREMENT_IDS
from runtime.orchestrator.plan_activation import PlanActivationStore, activate_approved_work
from runtime.orchestrator.ocpv2_runtime_service import finalize_remote_control_projection
from runtime.orchestrator.production_full_plan_boot import discover_registered_jobs, reconcile_job
from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA, seal_remote_control_envelope, validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_outbox import RemoteActivationProjectionV1, RemoteResultOutbox
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope
from runtime.orchestrator.runtime_release import RuntimeReleaseManifest


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class FakeTransport:
    def __init__(self, item: RawControlEnvelope):
        self.item = item
        self.projections: list[dict] = []
        self.acks: list[str] = []

    def receive(self, *, limit=16):
        return (self.item,) if limit else ()

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)

    def publish_projection(self, projection):
        self.projections.append(dict(projection))


class OCPv2ApprovedWorkActivationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "project"
        self.runtime = self.base / "runtime-release"
        self.state = self.base / "state"
        self.mapping = self.base / "mapping"
        for path in (self.project, self.runtime, self.state):
            path.mkdir()
        self.plan = self.project / "IMPLEMENTATION_PLAN.md"
        self.spec = self.project / "SPEC.md"
        self.plan.write_text("# Plan\n\n### Task G1: first\n\n### Task G2: second\n", encoding="utf-8")
        self.spec.write_text("# Spec\n", encoding="utf-8")
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "Test")
        git(self.project, "config", "user.email", "test@example.invalid")
        git(self.project, "add", ".")
        git(self.project, "commit", "-m", "plan-spec")
        self.requirement = self.project / "requirements.json"
        requirement = {
            "schema_version": "orchestration.requirement-evidence.v1",
            "requirements_sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(),
            "evidence": {rid: {} for rid in REQUIREMENT_IDS},
        }
        self.requirement.write_text(json.dumps(requirement), encoding="utf-8")
        git(self.project, "add", "requirements.json")
        git(self.project, "commit", "-m", "requirements")
        self.registry = OnboardingRegistry(self.mapping / "aliases")
        self.assertEqual(self.registry.register(self.project, "demo")["status"], "REGISTERED")

        runtime_file = self.runtime / "runtime" / "orchestrator" / "production_full_plan_boot.py"
        runtime_file.parent.mkdir(parents=True)
        runtime_file.write_text("# runtime fixture\n", encoding="utf-8")
        git(self.runtime, "init", "-b", "main")
        git(self.runtime, "config", "user.name", "Test")
        git(self.runtime, "config", "user.email", "test@example.invalid")
        git(self.runtime, "add", ".")
        git(self.runtime, "commit", "-m", "runtime")
        runtime_head = git(self.runtime, "rev-parse", "HEAD")
        runtime_tree = git(self.runtime, "rev-parse", "HEAD^{tree}")
        self.release = RuntimeReleaseManifest(
            schema_version="gch.runtime-release.v2", source_head=runtime_head,
            source_tree=runtime_tree, release_path=str(self.runtime),
            runtime_entry="runtime/orchestrator/production_full_plan_boot.py",
            runtime_entry_sha256=hashlib.sha256(runtime_file.read_bytes()).hexdigest(),
            manifest_sha256="d" * 64, publication_head=runtime_head,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def request(self, **changes) -> dict:
        value = {
            "schema_version": "orchestration.approved-work-activation-request.v1",
            "activation_request_id": "ACT-1", "project_alias": "demo",
            "approved_plan_path": "IMPLEMENTATION_PLAN.md",
            "approved_plan_sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(),
            "approved_spec_path": "SPEC.md",
            "approved_spec_sha256": hashlib.sha256(self.spec.read_bytes()).hexdigest(),
            "requirement_artifact_path": "requirements.json",
            "requirement_artifact_sha256": hashlib.sha256(self.requirement.read_bytes()).hexdigest() if self.requirement.exists() else "0" * 64,
            "approval_ref": "USER-APPROVAL-1", "expected_branch": "main",
            "expected_head": git(self.project, "rev-parse", "HEAD"),
            "task_ids": ["G1", "G2"], "runtime_release_digest": self.release.manifest_sha256,
        }
        value.update(changes)
        return value

    def typed_envelope(self, request: dict, *, message_id="MSG-A1"):
        payload = {
            "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
            "request_kind": "APPROVED_WORK_ACTIVATION", "message_id": message_id, "sequence": 1,
            "issued_at": "2026-09-23T00:00:00+00:00", "expires_at": "2026-09-23T00:10:00+00:00",
            "actor": "GPT_OPERATOR",
            "transport": {"adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273", "source_message_id": "77"},
            "payload": request, "payload_digest": "",
            "authorization": {"activation_policy_ref": "ACT-POLICY-1"}, "envelope_sha256": "",
        }
        return validate_remote_control_envelope(
            seal_remote_control_envelope(payload),
            now=datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc),
        )

    def activate_callback(self, outbox: RemoteResultOutbox, store: PlanActivationStore):
        def activate(envelope):
            binding = validate_approved_work_binding(
                envelope.payload, registry=self.registry, runtime_release=self.release,
            )
            office = AIOfficeStateStore(
                self.state, project_id=binding.project_id, run_id=binding.activation_request_id,
            )
            context = coordinate_approved_activation(binding, office_store=office)
            receipt = store.record_or_load(
                request_id=binding.activation_request_id, binding=binding,
                registrar=lambda: activate_approved_work(
                    binding, ai_context=context, harness_state_root=self.state,
                    runtime_code_root=self.runtime,
                ),
            )
            projection = RemoteActivationProjectionV1.from_receipt(receipt, message_id=envelope.message_id)
            outbox.enqueue_projection(projection)
            return projection.to_dict()
        return activate

    def run_remote_activation(self, request: dict, *, message_id="MSG-A1"):
        envelope = self.typed_envelope(request, message_id=message_id)
        raw = RawControlEnvelope(
            source_repository_id=None, source_channel_id="TEST", source_actor_id="235775273",
            source_message_id="77", content=b"{}", received_at="2026-09-23T00:05:00+00:00",
        )
        transport = FakeTransport(raw)
        outbox = RemoteResultOutbox(self.state / "remote-outbox")
        store = PlanActivationStore(self.state)
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: envelope,
            ingress=lambda _: (_ for _ in ()).throw(AssertionError("activation must not enter V2 ingress")),
            execute_authorized=lambda *_: (_ for _ in ()).throw(AssertionError("activation must not resume existing run")),
            activate_authorized=self.activate_callback(outbox, store),
            work_activation_enabled=True, activation_policy_ref="ACT-POLICY-1",
            after_projection_published=lambda _env, projection: finalize_remote_control_projection(outbox, projection),
        )
        return service.poll_once(mode=ControlMode.ACTIVE), transport

    def test_typed_activation_registers_one_job_and_boot_reconciler_discovers_it(self):
        result, transport = self.run_remote_activation(self.request())
        self.assertEqual(result.activated, 1)
        self.assertEqual(len(transport.projections), 1)
        jobs = discover_registered_jobs(self.state)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].name, "ACT-1.job.json")
        with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
            reconcile = reconcile_job(jobs[0], launch=False)
        self.assertEqual(reconcile["action"], "WOULD_RESUME")
        self.assertFalse(reconcile["launched"])

    def test_stale_head_and_missing_requirement_register_zero_jobs(self):
        stale = self.request(expected_head="0" * 40)
        result, _ = self.run_remote_activation(stale, message_id="MSG-STALE")
        self.assertEqual((result.activated, result.blocked), (0, 1))
        self.assertEqual(discover_registered_jobs(self.state), [])

        missing_state = self.base / "missing-state"
        missing_state.mkdir()
        original_state = self.state
        self.state = missing_state
        self.requirement.unlink()
        try:
            result, _ = self.run_remote_activation(self.request(), message_id="MSG-MISSING")
            self.assertEqual((result.activated, result.blocked), (0, 1))
            self.assertEqual(discover_registered_jobs(self.state), [])
        finally:
            self.state = original_state
            git(self.project, "restore", "requirements.json")
            self.requirement = self.project / "requirements.json"

    def test_conflicting_activation_id_does_not_register_second_job(self):
        first, _ = self.run_remote_activation(self.request(), message_id="MSG-FIRST")
        self.assertEqual(first.activated, 1)
        changed = self.request(approval_ref="USER-APPROVAL-CHANGED")
        second, transport = self.run_remote_activation(changed, message_id="MSG-CONFLICT")
        self.assertEqual((second.activated, second.blocked), (0, 1))
        self.assertEqual(transport.projections[0]["result_class"], "WORK_ACTIVATION_ERROR")
        self.assertEqual(len(discover_registered_jobs(self.state)), 1)

    def test_raw_unapproved_instruction_cannot_be_promoted_to_activation(self):
        request = self.request()
        request["instruction"] = "edit whatever is needed"
        with self.assertRaises(Exception):
            self.typed_envelope(request, message_id="MSG-RAW")
        self.assertEqual(discover_registered_jobs(self.state), [])

    def test_plan_activation_module_has_no_launch_or_effect_authority(self):
        import runtime.orchestrator.plan_activation as module
        source = inspect.getsource(module)
        for forbidden in ("subprocess", "systemctl", "FullMCPRuntime", "provider_router"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
