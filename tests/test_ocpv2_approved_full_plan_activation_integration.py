from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from runtime.ai_office.full_plan_activation import coordinate_approved_full_plan_activation
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.orchestrator.approved_full_plan_binding import validate_approved_full_plan_binding
from runtime.orchestrator.full_plan_activation import FullPlanActivationStore, activate_approved_full_plan
from runtime.orchestrator.gate_approval import seal_approval_evidence
from runtime.orchestrator.gate_orchestrator import REQUIREMENT_IDS, namespace_root
from runtime.orchestrator.ocpv2_canonical_resume import execute_registered_full_plan_continuation
from runtime.orchestrator.ocpv2_runtime_service import finalize_remote_control_projection
from runtime.orchestrator.production_full_plan_boot import discover_registered_jobs, reconcile_job
from runtime.orchestrator.production_full_plan_entry import load_registered_job
from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_outbox import RemoteFullPlanActivationProjectionV1, RemoteResultOutbox
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope
from runtime.orchestrator.runtime_release import RuntimeReleaseManifest
from runtime.orchestrator.task_contract_compat import resolve_task_project_requirement_contract


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_obj(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


PLAN = '''# Contract

## TASK-001 — bootstrap
Purpose: Bootstrap safely.
Related Requirements: NFR-008
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write, shell, test, git, implementation
Validation: TEST-001
Completion Condition: Bootstrap passes.

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | `app/` | CREATE | TASK-001 | PLANNED_NEW |

## SOURCE Task Dependencies
| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Entry |

## GATE-001 — first
Required Tasks: TASK-001

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| NFR-008 | Keep architecture extensible. | No user-specific core logic. | MUST |
'''


def projection(plan_sha: str) -> dict[str, object]:
    return {
        "schema_version": "orchestration.task-lv-authority-projection.v1",
        "project_id": "project",
        "canonical_plan_sha256": plan_sha,
        "contract_shape": "TASK_STAGE_GATE",
        "projection_policy": {
            "lv_identity": "TASK_ID",
            "gate_membership": "CANONICAL_GATE_REQUIRED_TASKS",
            "dependencies": "CANONICAL_TASK_DEPENDENCIES",
            "execution": "CANONICAL_TASK_DEPENDENCY_TYPE",
            "completion_criteria": "CANONICAL_TASK_COMPLETION_CONDITION_PLUS_VALIDATION",
            "provider_capabilities": "CANONICAL_TASK_REQUIRED_CAPABILITIES",
            "operational_capability": "DECLARED_NONE",
        },
        "change_targets": {"CT-001": {"source_expression": "app/", "owned_files": ["app/"]}},
    }


class FakeTransport:
    def __init__(self, item: RawControlEnvelope, *, fail_publish: bool = False) -> None:
        self.item = item
        self.fail_publish = fail_publish
        self.projections: list[dict] = []
        self.acks: list[str] = []

    def receive(self, *, limit=16):
        return (self.item,) if limit else ()

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)

    def publish_projection(self, projection):
        if self.fail_publish:
            raise RuntimeError("simulated publish failure")
        self.projections.append(dict(projection))


class OCPv2ApprovedFullPlanActivationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "project"
        self.docs = self.project / "docs"
        (self.docs / "harness").mkdir(parents=True)
        self.plan = self.docs / "DEVELOPMENT_PLAN.txt"
        self.plan.write_text(PLAN, encoding="utf-8")
        self.spec = self.docs / "spec.md"
        self.spec.write_text("# Spec\n", encoding="utf-8")
        self.projection = self.docs / "harness" / "task-lv-authority-projection.json"
        self.projection.write_text(json.dumps(projection(sha(self.plan)), sort_keys=True), encoding="utf-8")
        self.requirement = self.docs / "req-task-001.json"
        contract = resolve_task_project_requirement_contract(
            PLAN, project_id="project", canonical_plan_sha256=sha(self.plan), gate_id="GATE-001",
            task_id="TASK-001", owned_files=["app/"],
        )
        self.requirement.write_text(json.dumps(contract, sort_keys=True), encoding="utf-8")
        for rel, body in (
            ("CHANGELOG.txt", "# Changelog\n"), ("logs/app.log", ""),
            ("docs/harness/orchestration-state.md", "# State\n"),
            ("docs/APPROVAL_LOG.md", "# Approval\n"), ("docs/GATE_STATE.md", "# Gate State\n"),
        ):
            target = self.project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "Test")
        git(self.project, "config", "user.email", "test@example.invalid")
        git(self.project, "add", ".")
        git(self.project, "commit", "-m", "fixture authority")
        self.head = git(self.project, "rev-parse", "HEAD")

        self.authority = self.base / "authority"
        (self.authority / "aliases").mkdir(parents=True)
        (self.authority / "mappings").mkdir()
        self.registry = OnboardingRegistry(self.authority / "aliases")
        self.assertEqual(self.registry.register(self.project, "demo")["status"], "REGISTERED")
        self.mapping_path = self.authority / "mappings" / "project.json"
        self._write_mapping()

        self.harness = self.base / "harness"
        self.harness.mkdir()
        self.now = datetime(2026, 9, 23, 0, 5, tzinfo=timezone.utc)
        self.approval_root = namespace_root(self.harness, "project", "approval")
        self.artifact_root = namespace_root(self.harness, "project", "artifact")
        self.approval_root.mkdir(parents=True)
        self.artifact_root.mkdir(parents=True)
        self.requirements_sha = "a" * 64
        self.approval = self.approval_root / "approval-g1.json"
        self.engine = self.artifact_root / "engine-g1.json"
        self._write_approval()
        self._write_engine()

        self.runtime = self.base / "runtime-release"
        entry = self.runtime / "runtime" / "orchestrator" / "production_full_plan_boot.py"
        entry.parent.mkdir(parents=True)
        entry.write_text("# boot fixture\n", encoding="utf-8")
        unsigned = {
            "schema_version": "gch.runtime-release.v2",
            "source_head": "b" * 40,
            "source_tree": "c" * 40,
            "release_path": str(self.runtime),
            "runtime_entry": "runtime/orchestrator/production_full_plan_boot.py",
            "runtime_entry_sha256": sha(entry),
            "publication_head": "b" * 40,
        }
        manifest_digest = digest_obj(unsigned)
        (self.runtime / "RUNTIME_RELEASE_MANIFEST.json").write_text(
            json.dumps({**unsigned, "manifest_sha256": manifest_digest}, sort_keys=True), encoding="utf-8",
        )
        self.release = RuntimeReleaseManifest(**unsigned, manifest_sha256=manifest_digest)
        self.outbox = RemoteResultOutbox(self.harness / "remote-outbox")
        self.store = FullPlanActivationStore(self.harness)
        self.registrar_calls = 0
        self.valid_request_payload = self.request()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_mapping(self, *, plan_sha: str | None = None, projection_sha: str | None = None) -> None:
        psha = plan_sha or sha(self.plan)
        value = {
            "project_id": "project",
            "contract_paths": {
                "development_plan": "docs/DEVELOPMENT_PLAN.txt", "changelog": "CHANGELOG.txt",
                "app_log": "logs/app.log", "orchestration_state_md": "docs/harness/orchestration-state.md",
            },
            "required_contract_keys": ["development_plan", "changelog", "app_log", "orchestration_state_md"],
            "canonical_implementation_source": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": psha},
            "approved_source_reference": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": psha},
            "static_validation": {
                "business_lv_approval": "docs/APPROVAL_LOG.md", "gate_state": "docs/GATE_STATE.md",
                "gate_state_ledger": "docs/GATE_STATE.md",
            },
            "canonical_transition": {}, "interpreter_policy_id": "IMMUTABLE_EXTERNAL_INTERPRETER",
            "task_lv_authority_projection": {
                "path": "docs/harness/task-lv-authority-projection.json",
                "sha256": projection_sha or sha(self.projection),
            },
        }
        self.mapping_path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def _write_approval(self, *, expires_delta: timedelta = timedelta(hours=1)) -> None:
        approval_now = datetime.now(timezone.utc)
        payload = {
            "schema_version": "orchestration.gate-approval.v1", "approval_id": "APR-1",
            "project_id": "project", "gate_id": "GATE-001", "requirements_sha256": self.requirements_sha,
            "plan_sha256": sha(self.plan), "branch": "main", "head": self.head,
            "scope": {"lv_order": ["TASK-001"], "owned_files_by_lv": {"TASK-001": ["app/"]}},
            "issued_at": (approval_now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (approval_now + expires_delta).isoformat().replace("+00:00", "Z"), "status": "ACTIVE",
        }
        self.approval.write_text(json.dumps(seal_approval_evidence(payload), sort_keys=True), encoding="utf-8")

    def _write_engine(self) -> None:
        value = {
            "schema_version": "orchestration.requirement-evidence.v1",
            "requirements_sha256": self.requirements_sha,
            "evidence": {rid: {} for rid in REQUIREMENT_IDS},
        }
        self.engine.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def request(self, **changes) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "orchestration.approved-full-plan-activation-request.v1",
            "activation_request_id": "FP-ACT-1", "project_alias": "demo",
            "approved_plan": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": sha(self.plan)},
            "approved_spec": {"path": "docs/spec.md", "sha256": sha(self.spec)},
            "expected_branch": "main", "expected_head": self.head,
            "runtime_release_digest": self.release.manifest_sha256,
            "approval_ref": "USER-APPROVAL-1",
            "gate_bindings": [{
                "gate_id": "GATE-001",
                "approval_evidence": {"path": "approval-g1.json", "sha256": sha(self.approval)},
                "engine_requirement_evidence": {"path": "engine-g1.json", "sha256": sha(self.engine)},
                "project_requirement_evidence_by_lv": [{
                    "lv_id": "TASK-001", "path": "docs/req-task-001.json", "sha256": sha(self.requirement),
                }],
            }],
        }
        value.update(changes)
        return value

    def remote_envelope_payload(self, request: dict[str, object], *, message_id: str) -> dict[str, object]:
        return {
            "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
            "request_kind": "APPROVED_FULL_PLAN_ACTIVATION", "message_id": message_id, "sequence": 1,
            "issued_at": "2026-09-23T00:00:00+00:00", "expires_at": "2026-09-23T00:10:00+00:00",
            "actor": "GPT_OPERATOR",
            "transport": {
                "adapter_id": "TEST", "channel_id": "CTRL", "source_actor_id": "235775273",
                "source_message_id": "77",
            },
            "payload": request, "payload_digest": "",
            "authorization": {"full_plan_activation_policy_ref": "FP-POLICY-1"}, "envelope_sha256": "",
        }

    def typed_envelope(self, request: dict[str, object], *, message_id: str):
        payload = self.remote_envelope_payload(request, message_id=message_id)
        return validate_remote_control_envelope(seal_remote_control_envelope(payload), now=self.now)

    def _activate_callback(self):
        def activate(envelope):
            bundle = validate_approved_full_plan_binding(
                envelope.payload, authority_root=self.authority,
                runtime_release=self.release, harness_state_root=self.harness,
            )
            office = AIOfficeStateStore(
                self.harness, project_id=bundle.project_id, run_id=bundle.activation_request_id,
            )
            context = coordinate_approved_full_plan_activation(bundle, office_store=office)

            def registrar():
                self.registrar_calls += 1
                return activate_approved_full_plan(bundle, ai_context=context, harness_state_root=self.harness)

            receipt = self.store.record_or_load(
                request_id=bundle.activation_request_id, bundle=bundle, registrar=registrar,
            )
            projection = RemoteFullPlanActivationProjectionV1.from_receipt(receipt, message_id=envelope.message_id)
            self.outbox.enqueue_projection(projection)
            return projection.to_dict()
        return activate

    def compose_test_service(self, envelope, *, fail_publish: bool = False):
        raw = RawControlEnvelope(
            source_repository_id=None, source_channel_id="TEST", source_actor_id="235775273",
            source_message_id="77", content=b"{}", received_at="2026-09-23T00:05:00+00:00",
        )
        transport = FakeTransport(raw, fail_publish=fail_publish)
        service = RemoteOperatorService(
            transport=transport, decode_envelope=lambda _: envelope,
            ingress=lambda _: (_ for _ in ()).throw(AssertionError("Full Plan activation must not enter V2 ingress")),
            execute_authorized=lambda *_: (_ for _ in ()).throw(AssertionError("Full Plan activation must not resume OCP-owned run")),
            activate_full_plan_authorized=self._activate_callback(),
            full_plan_activation_enabled=True, full_plan_activation_policy_ref="FP-POLICY-1",
            after_projection_published=lambda _env, result: finalize_remote_control_projection(self.outbox, result),
        )
        return service, transport

    def run_remote_full_plan_activation(self, request: dict[str, object], *, message_id: str = "MSG-FP-1", fail_publish: bool = False):
        envelope = self.typed_envelope(request, message_id=message_id)
        service, transport = self.compose_test_service(envelope, fail_publish=fail_publish)
        return service.poll_once(mode=ControlMode.ACTIVE), transport

    def assert_no_registered_jobs(self) -> None:
        self.assertEqual(discover_registered_jobs(self.harness), [])
        self.assertEqual(self.registrar_calls, 0)

    def test_remote_executable_activation_registers_one_auto_reconcile_job(self):
        result, transport = self.run_remote_full_plan_activation(self.valid_request_payload)
        self.assertEqual(result.full_plan_activated, 1)
        jobs = discover_registered_jobs(self.harness)
        self.assertEqual(len(jobs), 1)
        job = load_registered_job(jobs[0])
        self.assertEqual(job["execution_owner"], "AUTO_RECONCILE")
        self.assertNotIn("executor_kind", job)
        self.assertEqual(job["mapping_root"], str((self.authority / "mappings").resolve()))
        self.assertEqual(transport.projections[0]["activation_profile"], "AUTO_RECONCILE_FULL_PLAN")

    def test_publish_failure_replay_does_not_register_second_job(self):
        with self.assertRaisesRegex(RuntimeError, "publish failure"):
            self.run_remote_full_plan_activation(self.valid_request_payload, fail_publish=True)
        self.assertEqual(self.registrar_calls, 1)
        self.assertEqual(len(discover_registered_jobs(self.harness)), 1)
        replay, transport = self.run_remote_full_plan_activation(self.valid_request_payload)
        self.assertEqual(replay.full_plan_activated, 1)
        self.assertEqual(self.registrar_calls, 1)
        self.assertEqual(len(discover_registered_jobs(self.harness)), 1)
        self.assertEqual(transport.projections[0]["activation_profile"], "AUTO_RECONCILE_FULL_PLAN")

    def test_boot_accepts_auto_reconcile_while_ocp_resume_rejects_owner(self):
        self.run_remote_full_plan_activation(self.valid_request_payload)
        job_path = discover_registered_jobs(self.harness)[0]
        job = load_registered_job(job_path)
        with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
            boot = reconcile_job(job_path, launch=False)
        self.assertEqual(boot["action"], "WOULD_RESUME")
        with self.assertRaisesRegex(Exception, "EXECUTION_OWNER_MISMATCH"):
            execute_registered_full_plan_continuation(
                harness_state_root=self.harness, project_id=job["project_id"], run_id=job["run_id"],
                gate_id=job["gates"][0]["gate_id"], task_id=job["gates"][0]["gate_id"],
                task_execution_id="OWNER-CHECK", expected_state_sha256="0" * 64,
                expected_owner_epoch=1, expected_source_head=job["expected_head"],
                expected_runtime_release_digest=job["runtime_release_digest"],
                remote_message_id="MSG-OWNER-CHECK", remote_directive_digest="a" * 64,
            )

    def test_aliases_present_mappings_absent_registers_zero_jobs(self):
        self.mapping_path.unlink()
        (self.authority / "mappings").rmdir()
        result, _ = self.run_remote_full_plan_activation(self.valid_request_payload, message_id="MSG-NOMAP")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_mapping_plan_sha_drift_registers_zero_jobs(self):
        self._write_mapping(plan_sha="0" * 64)
        result, _ = self.run_remote_full_plan_activation(self.valid_request_payload, message_id="MSG-MAPDRIFT")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_projection_sha_drift_registers_zero_jobs(self):
        self._write_mapping(projection_sha="0" * 64)
        result, _ = self.run_remote_full_plan_activation(self.valid_request_payload, message_id="MSG-PROJDRIFT")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_expired_gate_approval_registers_zero_jobs(self):
        self._write_approval(expires_delta=timedelta(seconds=-1))
        request = self.request()
        result, _ = self.run_remote_full_plan_activation(request, message_id="MSG-EXPIRED")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_production_approval_v2_in_gate_slot_registers_zero_jobs(self):
        self.approval.write_text(json.dumps({"schema_version": "orchestration.production-approval-log.v2", "events": []}), encoding="utf-8")
        request = self.request()
        result, _ = self.run_remote_full_plan_activation(request, message_id="MSG-WRONGAPP")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_missing_project_requirement_lv_artifact_registers_zero_jobs(self):
        self.requirement.unlink()
        result, _ = self.run_remote_full_plan_activation(self.valid_request_payload, message_id="MSG-NOREQ")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_runtime_release_digest_drift_registers_zero_jobs(self):
        request = self.request(runtime_release_digest="0" * 64)
        result, _ = self.run_remote_full_plan_activation(request, message_id="MSG-RUNTIME")
        self.assertEqual((result.full_plan_activated, result.blocked), (0, 1))
        self.assert_no_registered_jobs()

    def test_same_request_id_different_bundle_registers_no_second_job(self):
        first, _ = self.run_remote_full_plan_activation(self.valid_request_payload, message_id="MSG-FIRST")
        self.assertEqual(first.full_plan_activated, 1)
        changed = self.request(approval_ref="USER-APPROVAL-CHANGED")
        second, transport = self.run_remote_full_plan_activation(changed, message_id="MSG-CONFLICT")
        self.assertEqual((second.full_plan_activated, second.blocked), (0, 1))
        self.assertEqual(len(discover_registered_jobs(self.harness)), 1)
        self.assertEqual(self.registrar_calls, 1)
        self.assertEqual(transport.projections[0]["result_class"], "FULL_PLAN_ACTIVATION_ERROR")


if __name__ == "__main__":
    unittest.main()
