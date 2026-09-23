from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.approved_full_plan_activation_contract import (
    ApprovedFullPlanActivationRequestV1, ArtifactRefV1,
)
from runtime.orchestrator.approved_full_plan_binding import (
    ApprovedFullPlanBindingError,
    resolve_executable_authority_roots,
    resolve_harness_authority_file,
    validate_approved_full_plan_binding,
)
from runtime.orchestrator.gate_approval import seal_approval_evidence
from runtime.orchestrator.gate_orchestrator import REQUIREMENT_IDS, namespace_root
from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.runtime_release import RuntimeReleaseManifest
from runtime.orchestrator.task_contract_compat import resolve_task_project_requirement_contract


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


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


def projection(plan_sha: str) -> dict:
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


class ApprovedFullPlanBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.root = self.base / "project"; self.root.mkdir()
        self.docs = self.root / "docs"; self.docs.mkdir()
        self.plan = self.docs / "DEVELOPMENT_PLAN.txt"; self.plan.write_text(PLAN, encoding="utf-8")
        self.spec = self.docs / "spec.md"; self.spec.write_text("# Spec\n", encoding="utf-8")
        self.projection = self.docs / "projection.json"
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
            target=self.root/rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(body, encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "approved authority"], cwd=self.root, check=True, capture_output=True)

        self.authority = self.base / "authority"; (self.authority / "aliases").mkdir(parents=True); (self.authority / "mappings").mkdir()
        self.registry = OnboardingRegistry(self.authority / "aliases")
        self.assertEqual(self.registry.register(self.root, "demo")["status"], "REGISTERED")
        self.mapping_path = self.authority / "mappings" / "project.json"; self._write_mapping()

        self.harness = self.base / "harness"; self.harness.mkdir()
        self.approval_root = namespace_root(self.harness, "project", "approval"); self.approval_root.mkdir(parents=True)
        self.artifact_root = namespace_root(self.harness, "project", "artifact"); self.artifact_root.mkdir(parents=True)
        self.requirements_sha = "a" * 64
        self.approval = self.approval_root / "approval-g1.json"; self.engine = self.artifact_root / "engine-g1.json"
        self._write_approval(); self._write_engine()

        self.runtime = self.base / "runtime-release"; self.runtime.mkdir()
        self.release = RuntimeReleaseManifest(
            schema_version="gch.runtime-release.v2", source_head="b"*40, source_tree="c"*40,
            release_path=str(self.runtime), runtime_entry="runtime/orchestrator/production_full_plan_boot.py",
            runtime_entry_sha256="d"*64, manifest_sha256="e"*64, publication_head="b"*40,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_mapping(self, *, projection_enabled: bool = True, plan_sha: str | None = None) -> None:
        psha = plan_sha or sha(self.plan)
        value = {
            "project_id": "project",
            "contract_paths": {"development_plan": "docs/DEVELOPMENT_PLAN.txt", "changelog": "CHANGELOG.txt", "app_log": "logs/app.log", "orchestration_state_md": "docs/harness/orchestration-state.md"},
            "required_contract_keys": ["development_plan", "changelog", "app_log", "orchestration_state_md"],
            "canonical_implementation_source": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": psha},
            "approved_source_reference": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": psha},
            "static_validation": {"business_lv_approval": "docs/APPROVAL_LOG.md", "gate_state": "docs/GATE_STATE.md", "gate_state_ledger": "docs/GATE_STATE.md"},
            "canonical_transition": {}, "interpreter_policy_id": "IMMUTABLE_EXTERNAL_INTERPRETER",
        }
        if projection_enabled:
            value["task_lv_authority_projection"] = {"path": "docs/projection.json", "sha256": sha(self.projection)}
        self.mapping_path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def _write_approval(self, *, expires_delta: timedelta = timedelta(hours=1), owned: list[str] | None = None, path: Path | None = None) -> Path:
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": "orchestration.gate-approval.v1", "approval_id": "APR-1", "project_id": "project", "gate_id": "GATE-001",
            "requirements_sha256": self.requirements_sha, "plan_sha256": sha(self.plan), "branch": "main", "head": git(self.root, "rev-parse", "HEAD"),
            "scope": {"lv_order": ["TASK-001"], "owned_files_by_lv": {"TASK-001": owned or ["app/"]}},
            "issued_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (now + expires_delta).isoformat().replace("+00:00", "Z"), "status": "ACTIVE",
        }
        target = path or self.approval; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(seal_approval_evidence(payload), sort_keys=True), encoding="utf-8"); return target

    def _write_engine(self, path: Path | None = None) -> Path:
        target = path or self.engine; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"schema_version": "orchestration.requirement-evidence.v1", "requirements_sha256": self.requirements_sha, "evidence": {rid: {} for rid in REQUIREMENT_IDS}}, sort_keys=True), encoding="utf-8"); return target

    def request(self, **changes) -> dict:
        value = {
            "schema_version": "orchestration.approved-full-plan-activation-request.v1", "activation_request_id": "FP-ACT-1", "project_alias": "demo",
            "approved_plan": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": sha(self.plan)}, "approved_spec": {"path": "docs/spec.md", "sha256": sha(self.spec)},
            "expected_branch": "main", "expected_head": git(self.root, "rev-parse", "HEAD"), "runtime_release_digest": self.release.manifest_sha256,
            "approval_ref": "USER-APPROVAL-1", "gate_bindings": [{"gate_id": "GATE-001", "approval_evidence": {"path": "approval-g1.json", "sha256": sha(self.approval)},
            "engine_requirement_evidence": {"path": "engine-g1.json", "sha256": sha(self.engine)}, "project_requirement_evidence_by_lv": [{"lv_id": "TASK-001", "path": "docs/req-task-001.json", "sha256": sha(self.requirement)}]}],
        }
        value.update(changes); return value

    def validate(self, request=None):
        return validate_approved_full_plan_binding(request or self.request(), authority_root=self.authority, runtime_release=self.release, harness_state_root=self.harness)

    def test_valid_binding_separates_project_and_harness_authority_domains(self):
        bundle = self.validate(); gate = bundle.gates[0]
        self.assertEqual(bundle.project_id, "project"); self.assertEqual(bundle.mapping_root, str(self.authority / "mappings"))
        self.assertEqual(gate.approval_evidence_path, str(self.approval)); self.assertEqual(gate.engine_requirement_evidence_path, str(self.engine))
        self.assertEqual(gate.project_requirement_evidence_paths_by_lv[0][1], str(self.requirement)); self.assertEqual(gate.lv_order, ("TASK-001",))
        self.assertRegex(bundle.bundle_digest, r"^[0-9a-f]{64}$")

    def test_alias_without_mappings_directory_blocks_and_creates_nothing(self):
        self.mapping_path.unlink(); (self.authority / "mappings").rmdir(); before = sorted(path.relative_to(self.authority) for path in self.authority.rglob("*"))
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_FULL_PLAN_REQUIRED"): self.validate()
        self.assertEqual(sorted(path.relative_to(self.authority) for path in self.authority.rglob("*")), before)

    def test_alias_mapping_plan_identity_mismatch_blocks(self):
        self._write_mapping(plan_sha="0" * 64)
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_MAPPING_MISMATCH"): self.validate()

    def test_missing_task_projection_blocks(self):
        self._write_mapping(projection_enabled=False)
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_FULL_PLAN_REQUIRED"): self.validate()

    def test_expired_or_wrong_scope_gate_approval_blocks(self):
        self._write_approval(expires_delta=timedelta(seconds=-1)); req=self.request(); req["gate_bindings"][0]["approval_evidence"]["sha256"] = sha(self.approval)
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(req)
        self._write_approval(owned=["other/"]); req=self.request(); req["gate_bindings"][0]["approval_evidence"]["sha256"] = sha(self.approval)
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(req)

    def test_approval_namespace_rejects_traversal_absolute_symlink_and_wrong_namespace(self):
        parsed = ApprovedFullPlanActivationRequestV1.from_mapping(self.request()); gate = parsed.gate_bindings[0]
        for raw in ("../escape.json", "/etc/passwd"):
            bad = replace(parsed, gate_bindings=(replace(gate, approval_evidence=ArtifactRefV1(raw, gate.approval_evidence.sha256)),))
            with self.subTest(raw=raw), self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(bad)
        target=self.approval_root/"real.json"; target.write_bytes(self.approval.read_bytes()); link=self.approval_root/"link.json"; link.symlink_to(target.name)
        bad=replace(parsed, gate_bindings=(replace(gate, approval_evidence=ArtifactRefV1("link.json", sha(target))),))
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(bad)
        req = self.request()
        wrong=self.artifact_root/"approval-g1.json"; wrong.write_bytes(self.approval.read_bytes()); self.approval.unlink()
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(req)

    def test_project_git_approval_is_not_a_harness_authority_substitute(self):
        req=self.request()
        project_approval=self.docs/"approval-g1.json"; project_approval.write_bytes(self.approval.read_bytes()); subprocess.run(["git","add","docs/approval-g1.json"],cwd=self.root,check=True)
        subprocess.run(["git","-c","user.name=Test","-c","user.email=test@localhost","commit","-m","wrong approval domain"],cwd=self.root,check=True,capture_output=True); self.approval.unlink()
        req["expected_head"] = git(self.root,"rev-parse","HEAD"); req["gate_bindings"][0]["approval_evidence"]={"path":"docs/approval-g1.json","sha256":sha(project_approval)}
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(req)

    def test_production_approval_v2_is_not_gate_approval(self):
        self.approval.write_text(json.dumps({"schema_version":"orchestration.production-approval-log.v2","events":[]}),encoding="utf-8"); req=self.request(); req["gate_bindings"][0]["approval_evidence"]["sha256"]=sha(self.approval)
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"): self.validate(req)

    def test_engine_evidence_must_come_from_artifact_namespace(self):
        parsed=ApprovedFullPlanActivationRequestV1.from_mapping(self.request()); gate=parsed.gate_bindings[0]
        project_engine=self.docs/"engine-g1.json"; project_engine.write_bytes(self.engine.read_bytes()); self.engine.unlink()
        bad=replace(parsed, gate_bindings=(replace(gate, engine_requirement_evidence=ArtifactRefV1("docs/engine-g1.json", sha(project_engine))),))
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_REQUIREMENT_BINDING_MISMATCH"): self.validate(bad)
        self._write_engine(self.approval_root/"engine-g1.json"); bad=replace(parsed, gate_bindings=(replace(gate, engine_requirement_evidence=ArtifactRefV1("engine-g1.json", sha(self.approval_root/"engine-g1.json"))),))
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_REQUIREMENT_BINDING_MISMATCH"): self.validate(bad)

    def test_wrong_project_requirement_profile_blocks(self):
        self.requirement.write_bytes(self.engine.read_bytes()); subprocess.run(["git","add","docs/req-task-001.json"],cwd=self.root,check=True)
        subprocess.run(["git","-c","user.name=Test","-c","user.email=test@localhost","commit","-m","wrong req profile"],cwd=self.root,check=True,capture_output=True); self._write_approval()
        req=self.request(expected_head=git(self.root,"rev-parse","HEAD")); req["gate_bindings"][0]["approval_evidence"]["sha256"] = sha(self.approval)
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_REQUIREMENT_BINDING_MISMATCH"): self.validate(req)

    def test_namespace_resolver_never_creates_or_accepts_unknown_kind(self):
        missing=self.base/"missing-harness"
        with self.assertRaises(ApprovedFullPlanBindingError): resolve_harness_authority_file(harness_state_root=missing,project_id="project",kind="approval",raw="a.json",label="EXECUTABLE_APPROVAL_REQUIRED")
        self.assertFalse(missing.exists())
        with self.assertRaises(ApprovedFullPlanBindingError): resolve_harness_authority_file(harness_state_root=self.harness,project_id="project",kind="run",raw="a.json",label="BAD")

    def test_authority_root_resolver_has_no_fallback(self):
        self.assertEqual(resolve_executable_authority_roots(self.authority),(self.authority,self.authority/"aliases",self.authority/"mappings"))


if __name__ == "__main__": unittest.main()
