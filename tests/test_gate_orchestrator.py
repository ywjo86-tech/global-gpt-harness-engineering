from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import (
    FULL_PLAN, GATE_BY_GATE, RESUME, GateAuthorization, GateOrchestrationError,
    advance_lifecycle, compatibility_dry_run, create_gate_authorization, derive_transition,
    gate_exit_action, initial_ledger, load_gate_plan, namespace_root, onboarding_dry_run, recovery_checkpoint,
    resume_from_checkpoint, select_assets, structured_handoff, validate_authorization,
    validate_capability_handoff_projection, validate_concurrent_ownership, validate_handoff, validate_ledger, validate_owned_access,
)
from runtime.orchestrator.gate_controller import GateControllerAdapters
from runtime.orchestrator.gate_approval import seal_approval_evidence
from runtime.orchestrator.completeness import REQUIREMENT_IDS

PLAN = '''# Plan

### Gate 1 — Core

| ID | 작업 | 대상 | 완료조건 |
| --- | --- | --- | --- |
| G1-LV3-1 | model | `app/model.py` | model tests |
| G1-LV3-2 | service | `app/service.py` | service tests |
| G1-LV3-3 | Gate Exit Review | result report | all verified |

| ID | depends_on | execution | owned_files | input → output / exit_check |
| --- | --- | --- | --- | --- |
| G1-LV3-1 | Gate 0 | sequential | `app/model.py`, 관련 테스트 | input → model / focused pass |
| G1-LV3-2 | G1-LV3-1 | sequential | `app/service.py`, 관련 테스트 | model → service / focused pass |
| G1-LV3-3 | G1-LV3-2 | sequential |  | evidence → Exit / Gate review |
'''


class GateOrchestratorTests(unittest.TestCase):
    def test_capability_crash_failpoint_is_disabled_by_default_and_explicit_only(self) -> None:
        from runtime.orchestrator.gate_orchestrator import _test_only_crash_after_capability_stage
        from runtime.orchestrator.operational_capability import InjectedCrash
        with patch.dict("os.environ", {}, clear=True):
            _test_only_crash_after_capability_stage("DISCOVERY_COMPLETED")
        with patch.dict("os.environ", {"HARNESS_TEST_CRASH_AFTER_CAPABILITY_STAGE": "DISCOVERY_COMPLETED"}):
            with self.assertRaises(InjectedCrash):
                _test_only_crash_after_capability_stage("DISCOVERY_COMPLETED")

    def test_production_crash_failpoint_is_disabled_by_default_and_explicit_only(self) -> None:
        from runtime.orchestrator.gate_orchestrator import _test_only_crash_after_production_stage
        from runtime.orchestrator.operational_capability import InjectedCrash
        with patch.dict("os.environ", {}, clear=True):
            _test_only_crash_after_production_stage("WORKER")
        with patch.dict("os.environ", {"HARNESS_TEST_CRASH_AFTER_PRODUCTION_STAGE": "WORKER"}):
            with self.assertRaises(InjectedCrash):
                _test_only_crash_after_production_stage("WORKER")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "project-one"; self.root.mkdir()
        self.plan_path = self.root / "PLAN.md"; self.plan_path.write_text(PLAN)
        self.plan_hash = hashlib.sha256(self.plan_path.read_bytes()).hexdigest()
        self.mapping = SimpleNamespace(canonical_source=self.plan_path, canonical_sha256=self.plan_hash)
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=self.mapping):
            self.plan = load_gate_plan(self.root, "GATE-1")
        self.auth = create_gate_authorization(self.plan, "AUTH-G1")

    def test_capability_handoff_projection_mismatch_is_blocked(self) -> None:
        projection = {"used_assets": ["candidate-a"], "candidate_use_authorized": True}
        handoff = {"review": {"capability": {"used_assets": [], "candidate_use_authorized": True}}}
        with self.assertRaisesRegex(GateOrchestrationError, "projection mismatch"):
            validate_capability_handoff_projection(projection, handoff)

    def test_resumed_capability_filesystem_mutation_is_blocked(self) -> None:
        from runtime.orchestrator.gate_orchestrator import _validate_resume_capability_filesystem
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "installed"; target.mkdir()
            skill = target / "SKILL.md"; skill.write_text("safe", encoding="utf-8")
            digest = hashlib.sha256(skill.read_bytes()).hexdigest()
            (target / ".codex-install-manifest.json").write_text(json.dumps({"skill_md_digest": digest, "aggregate_digest": digest}), encoding="utf-8")
            handoff = {"review": {"capability_runtime_selection": {"installed_target": str(target), "artifact_digest": digest}}}
            _validate_resume_capability_filesystem(handoff)
            skill.write_text("mutated", encoding="utf-8")
            with self.assertRaisesRegex(GateOrchestrationError, "digest drift"):
                _validate_resume_capability_filesystem(handoff)

    def tearDown(self) -> None: self.temp.cleanup()

    def approval_evidence(self, name: str = "approval.json") -> Path:
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": "orchestration.gate-approval.v1", "approval_id": "APR-G1-TEST",
            "project_id": self.plan.project_id, "gate_id": self.plan.gate_id,
            "requirements_sha256": "b" * 64, "plan_sha256": self.plan.canonical_plan_sha256,
            "branch": "main", "head": "c" * 40,
            "scope": {"lv_order": [item.lv_id for item in self.plan.lvs],
                      "owned_files_by_lv": {item.lv_id: item.owned_files for item in self.plan.lvs}},
            "issued_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "status": "ACTIVE",
        }
        path = self.root.parent / name
        path.write_text(json.dumps(seal_approval_evidence(payload)), encoding="utf-8")
        return path

    def canonical_capability_plan(self, first_contract, *, others_none=True):
        none={"version":"v1","mode":"DECLARED_NONE","requirements":[]}
        lvs=[replace(item,capability_contract=(first_contract if index == 0 else (none if others_none else None)))
             for index,item in enumerate(self.plan.lvs)]
        return replace(self.plan,lvs=lvs)

    def lifecycle_adapters(self, calls, *, worker_status="COMPLETED"):
        def result(stage,status):
            def invoke(context):
                calls.append((stage,context["lv_id"]))
                return {"status":status,"exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True}
            return invoke
        return GateControllerAdapters(result("PACKAGE","SEALED"),result("PREFLIGHT","READY"),
            result("WORKER",worker_status),result("REVIEW","PASS"),result("REMEDIATION","PASS"),
            result("CHECKPOINT","CHECKPOINTED"),result("EXIT","EXITED"),result("HANDOFF","SEALED"))

    def requirement_evidence(self, lv_evidence_sha256: str = "a" * 64) -> dict[str, dict[str, object]]:
        evidence: dict[str, dict[str, object]] = {}
        for requirement_id in REQUIREMENT_IDS:
            implementation = f"requirement-evidence/{requirement_id}/implementation.json"
            test_ref = f"requirement-evidence/{requirement_id}/test.json"
            selected = ["harness-runtime"]
            implementation_data = json.dumps({"requirement_id":requirement_id,"lv_evidence_sha256":lv_evidence_sha256,"evidence_type":"implementation"},sort_keys=True,separators=(",",":")).encode()
            test_data = json.dumps({"requirement_id":requirement_id,"lv_evidence_sha256":lv_evidence_sha256,"evidence_type":"test"},sort_keys=True,separators=(",",":")).encode()
            implementation_sha = hashlib.sha256(implementation_data).hexdigest(); test_sha = hashlib.sha256(test_data).hexdigest()
            metadata={"excluded_assets":[f"excluded-{requirement_id}"],"selection_rationale":f"exact evidence for {requirement_id}","gate_id":"GATE-1","lv_id":"G1-LV3-1","owned_files":[],"tests":[f"test:{requirement_id}"]}
            payload = {"requirement_id": requirement_id, "lv_evidence_sha256": lv_evidence_sha256, **metadata,
                       "implementation_ref": implementation, "implementation_sha256": implementation_sha,
                       "test_ref": test_ref, "test_sha256": test_sha, "selected_assets": selected}
            data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            refs = {}
            for kind in ("checkpoint", "exit", "handoff"):
                relative = f"requirement-evidence/{requirement_id}/{kind}.json"
                path = self.root.parent / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
                refs[f"{kind}_ref"] = relative
            for relative, content in ((implementation, implementation_data), (test_ref, test_data)):
                path=self.root.parent/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(content)
            evidence[requirement_id] = {"artifact_sha256": hashlib.sha256(data).hexdigest(),
                "lv_evidence_sha256":lv_evidence_sha256,"selected_assets":selected,**metadata,"implementation_ref":implementation,
                "implementation_sha256":implementation_sha,"test_ref":test_ref,"test_sha256":test_sha,**refs}
        return evidence

    def test_plan_loads_complete_order_owned_files_and_tests(self) -> None:
        self.assertEqual([x.lv_id for x in self.plan.lvs], ["G1-LV3-1", "G1-LV3-2", "G1-LV3-3"])
        self.assertEqual(self.plan.lvs[0].owned_files, ["app/model.py", "tests/test_model.py"])
        self.assertEqual(self.plan.lvs[2].owned_files, [])

    def test_gate_approval_once_drives_multiple_system_transitions(self) -> None:
        first = derive_transition(self.plan, self.auth, None, [])
        second = derive_transition(self.plan, self.auth, "G1-LV3-1", ["G1-LV3-1"])
        third = derive_transition(self.plan, self.auth, "G1-LV3-2", ["G1-LV3-1", "G1-LV3-2"])
        self.assertEqual([first["to_lv"], second["to_lv"], third["to_lv"]], ["G1-LV3-1", "G1-LV3-2", "G1-LV3-3"])
        self.assertFalse(any(item["user_approval_renewal"] for item in (first, second, third)))
        self.assertTrue(all(item["event_type"] == "SYSTEM_TRANSITION" for item in (first, second, third)))

    def test_out_of_gate_lv_is_blocked(self) -> None:
        with self.assertRaises(GateOrchestrationError): derive_transition(self.plan, self.auth, "G2-LV3-1", [])

    def test_missing_or_reordered_lv_history_is_blocked(self) -> None:
        with self.assertRaises(GateOrchestrationError): derive_transition(self.plan, self.auth, None, ["G1-LV3-2"])

    def test_authorization_plan_sha_drift_is_blocked(self) -> None:
        bad = GateAuthorization(**dict(self.auth.to_dict(), canonical_plan_sha256="0" * 64))
        with self.assertRaises(GateOrchestrationError): validate_authorization(self.plan, bad)

    def test_out_of_scope_owned_file_is_blocked(self) -> None:
        with self.assertRaises(GateOrchestrationError): validate_owned_access(self.auth, "G1-LV3-1", ["app/other.py"])

    def test_owned_file_access_passes(self) -> None:
        validate_owned_access(self.auth, "G1-LV3-1", ["app/model.py", "tests/test_model.py"])

    def test_concurrent_same_file_ownership_is_blocked(self) -> None:
        with self.assertRaises(GateOrchestrationError): validate_concurrent_ownership({"LV1": ["app/x.py"], "LV2": ["app/x.py"]})

    def test_directory_owned_scope_allows_descendant_and_blocks_other(self) -> None:
        validate_owned_access(self.auth, "G1-LV3-1", ["app/model.py"])
        directory_auth = GateAuthorization(**dict(self.auth.to_dict(), owned_files_by_lv=dict(self.auth.owned_files_by_lv, **{"G1-LV3-3": ["tests/"]})))
        validate_owned_access(directory_auth, "G1-LV3-3", ["tests/test_integration.py"])
        with self.assertRaises(GateOrchestrationError): validate_owned_access(directory_auth, "G1-LV3-3", ["app/other.py"])

    def test_directory_and_descendant_concurrent_ownership_conflicts(self) -> None:
        with self.assertRaises(GateOrchestrationError): validate_concurrent_ownership({"LV1": ["tests/"], "LV2": ["tests/test_x.py"]})

    def test_lifecycle_hard_stops_and_same_lv_remediation(self) -> None:
        self.assertTrue(advance_lifecycle("PACKAGE", "PASS")["hard_stop"])
        self.assertEqual(advance_lifecycle("REVIEW", "FAIL")["stage"], "REMEDIATION")
        self.assertTrue(advance_lifecycle("REVIEW", "FAIL")["same_lv"])
        self.assertTrue(advance_lifecycle("PREFLIGHT", "BLOCKED")["user_handoff"])

    def test_gate_by_gate_is_default(self) -> None:
        self.assertEqual(self.auth.mode, GATE_BY_GATE)
        final = derive_transition(self.plan, self.auth, "G1-LV3-3", [x.lv_id for x in self.plan.lvs])
        self.assertTrue(final["gate_exit_ready"])

    def test_gate_by_gate_stops_for_next_gate_user_approval(self) -> None:
        action = gate_exit_action(self.auth, "GATE-2")
        self.assertEqual(action["action"], "WAIT_FOR_NEXT_GATE_USER_APPROVAL"); self.assertFalse(action["automatic"])

    def test_full_plan_is_blocked_without_validation_and_opt_in(self) -> None:
        with self.assertRaises(GateOrchestrationError): create_gate_authorization(self.plan, "AUTH", mode=FULL_PLAN)
        allowed = create_gate_authorization(self.plan, "AUTH", mode=FULL_PLAN, full_plan_opt_in=True, project_final_validation=True)
        self.assertEqual(allowed.mode, FULL_PLAN)
        self.assertEqual(gate_exit_action(allowed, "GATE-2")["action"], "SYSTEM_TRANSITION")

    def test_resume_checkpoint_prevents_namespace_reuse(self) -> None:
        cp = recovery_checkpoint(self.plan.project_id, "GATE-1", "G1-LV3-1", "run-1", {"completed_lvs": ["G1-LV3-1"]})
        self.assertEqual(resume_from_checkpoint(cp, project_id=self.plan.project_id, gate_id="GATE-1", run_id="run-1")["completed_lvs"], ["G1-LV3-1"])
        with self.assertRaises(GateOrchestrationError): resume_from_checkpoint(cp, project_id="other", gate_id="GATE-1", run_id="run-1")

    def test_resume_tamper_is_blocked(self) -> None:
        cp = recovery_checkpoint(self.plan.project_id, "GATE-1", "G1-LV3-1", "run-1", {"completed_lvs": []}); cp["payload"]["state"] = {}
        with self.assertRaises(GateOrchestrationError): resume_from_checkpoint(cp, project_id=self.plan.project_id, gate_id="GATE-1", run_id="run-1")

    def test_ledger_complete_mapping_and_exit_guard(self) -> None:
        ledger = initial_ledger(self.plan); validate_ledger(self.plan, ledger)
        with self.assertRaises(GateOrchestrationError): validate_ledger(self.plan, ledger, exit_required=True)
        for item in ledger: item.status = "EXITED"; item.evidence_sha256 = "a" * 64
        validate_ledger(self.plan, ledger, exit_required=True)

    def test_ledger_missing_reordered_or_evidence_missing_is_blocked(self) -> None:
        ledger = initial_ledger(self.plan)
        with self.assertRaises(GateOrchestrationError): validate_ledger(self.plan, ledger[:-1])
        with self.assertRaises(GateOrchestrationError): validate_ledger(self.plan, list(reversed(ledger)))
        ledger[0].status = "VERIFIED"
        with self.assertRaises(GateOrchestrationError): validate_ledger(self.plan, ledger)

    def test_structured_handoff_fields_sha_and_owned_scope(self) -> None:
        cp = recovery_checkpoint(self.plan.project_id, "GATE-1", "G1-LV3-1", "run-1", {})
        handoff = structured_handoff(self.plan, self.auth, lv_id="G1-LV3-1", run_id="run-1", branch="main", head="a"*40, completed_plan_items=["G1-LV3-1"], remaining_plan_items=["G1-LV3-2","G1-LV3-3"], changed_files=["app/model.py"], tests=[{"status":"PASS"}], review={"verdict":"PASS","hard_stop":True}, artifact_sha256="b"*64, used_assets=["project-orchestrator"], recovery=cp)
        validate_handoff(handoff, self.plan, self.auth)
        handoff["changed_files"] = ["app/other.py"]
        with self.assertRaises(GateOrchestrationError): validate_handoff(handoff, self.plan, self.auth)

    def test_handoff_missing_field_or_sha_tamper_is_blocked(self) -> None:
        cp = recovery_checkpoint(self.plan.project_id, "GATE-1", "G1-LV3-1", "run-1", {})
        handoff = structured_handoff(self.plan, self.auth, lv_id="G1-LV3-1", run_id="run-1", branch="main", head="a"*40, completed_plan_items=[], remaining_plan_items=[], changed_files=[], tests=[], review={}, artifact_sha256="b"*64, used_assets=[], recovery=cp)
        del handoff["tests"]
        with self.assertRaises(GateOrchestrationError): validate_handoff(handoff, self.plan, self.auth)

    def test_project_namespaces_are_isolated(self) -> None:
        one = namespace_root(self.root.parent / "harness", "project-one", "state")
        two = namespace_root(self.root.parent / "harness", "project-two", "state")
        self.assertNotEqual(one, two); self.assertNotEqual(one.parent, two.parent)
        with self.assertRaises(GateOrchestrationError): namespace_root(self.root.parent / "harness", "../escape", "state")

    def test_asset_routing_prefers_global_then_project_and_reports_gap(self) -> None:
        manifest = lambda asset, scope, caps: {"asset_id":asset,"scope":scope,"capabilities":caps,"permissions":["execute"],"owned_files":["app/"]}
        result = select_assets([manifest("global-project-orchestrator","global",["orchestrate"])],
                               [manifest("project-specialist","project",["orchestrate"])], ["orchestrate"],
                               permissions=["execute"], owned_files=["app/model.py"])
        self.assertEqual(result["selected"], ["project-specialist", "global-project-orchestrator"])
        self.assertFalse(result["substring_matching_used"]); self.assertFalse(result["global_creation_authorized"])

    def test_onboarding_fixture_fails_closed_until_contract_complete(self) -> None:
        result = onboarding_dry_run(self.root, "fixture")
        self.assertTrue(result["fail_closed"]); self.assertFalse(result["mutation_performed"])
        for relative in ["AGENTS.md","docs/DEVELOPMENT_PLAN.txt","CHANGELOG.txt","logs/app.log"]:
            path=self.root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text("fixture")
        result = onboarding_dry_run(self.root, "fixture"); self.assertFalse(result["fail_closed"]); self.assertTrue(result["mapping_ready"])

    def test_compatibility_dry_run_is_read_only(self) -> None:
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=self.mapping):
            result = compatibility_dry_run(self.root, "GATE-1")
        self.assertEqual(result["status"], "COMPATIBLE"); self.assertFalse(result["mutation_performed"]); self.assertFalse(result["full_plan_active"])

    def test_missing_mapping_dry_run_blocks(self) -> None:
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=None):
            result = compatibility_dry_run(self.root, "GATE-1")
        self.assertEqual(result["status"], "BLOCKED"); self.assertFalse(result["mutation_performed"])

    def test_execute_gate_uses_full_controller_and_never_worker_handoff(self) -> None:
        from runtime.orchestrator.gate_orchestrator import execute_gate
        def result(status):
            return lambda context: {"status": status, "exit_code": 0, "evidence_sha256": "a" * 64, "hard_stop": True}
        adapters = GateControllerAdapters(result("SEALED"), result("READY"), result("COMPLETED"), result("PASS"),
                                           result("PASS"), result("CHECKPOINTED"), result("EXITED"), result("SEALED"))
        approval = self.approval_evidence("execute-approval.json")
        requirement_evidence = self.requirement_evidence()
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan", return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization", return_value=self.auth):
            outcome = execute_gate(self.root, "GATE-1", "run-1", harness_root=self.root.parent, adapters=adapters,
                                   approval_evidence=approval,requirements_sha256="b"*64,branch="main",head="c"*40,
                                   requirement_evidence=requirement_evidence)
        self.assertEqual(outcome["status"], "GATE_EXIT")
        self.assertEqual(len(outcome["lifecycles"]), 3)
        self.assertTrue(all(item["status"] == "SYSTEM_TRANSITION" for item in outcome["lifecycles"]))

    def test_execute_gate_resume_skips_completed_lv_handoff(self) -> None:
        from runtime.orchestrator.gate_orchestrator import execute_gate, namespace_root
        calls=[]
        def result(stage, status):
            def invoke(context): calls.append((stage, context["lv_id"])); return {"status":status,"exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True}
            return invoke
        adapters=GateControllerAdapters(result("PACKAGE","SEALED"),result("PREFLIGHT","READY"),result("WORKER","COMPLETED"),
            result("REVIEW","PASS"),result("REMEDIATION","PASS"),result("CHECKPOINT","CHECKPOINTED"),result("EXIT","EXITED"),result("HANDOFF","SEALED"))
        approval = self.approval_evidence("resume-approval.json")
        requirement_evidence = self.requirement_evidence()
        handoff=namespace_root(self.root.parent,self.plan.project_id,"artifact")/"run-resume.handoff.json"
        handoff.parent.mkdir(parents=True); handoff.write_text('{"lv":"G1-LV3-1","run_id":"run-resume"}')
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=self.auth), \
             patch("runtime.orchestrator.gate_orchestrator.validate_handoff"):
            outcome=execute_gate(self.root,"GATE-1","run-resume",harness_root=self.root.parent,adapters=adapters,resume=True,
                approval_evidence=approval,requirements_sha256="b"*64,branch="main",head="c"*40,
                requirement_evidence=requirement_evidence)
        self.assertEqual(outcome["status"],"GATE_EXIT")
        self.assertNotIn(("PACKAGE","G1-LV3-1"),calls)
        self.assertEqual({lv for _,lv in calls},{"G1-LV3-2","G1-LV3-3"})

    def test_full_plan_capability_dry_run_is_a_pre_worker_prerequisite(self) -> None:
        from runtime.orchestrator.gate_orchestrator import execute_gate
        from runtime.orchestrator.operational_capability import DryRunExecutionContext, run_operational_capability_dry_run
        from runtime.orchestrator.schemas import CapabilityRequirement
        calls=[]
        def result(stage, status):
            def invoke(context): calls.append((stage, context["lv_id"])); return {"status":status,"exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True}
            return invoke
        adapters=GateControllerAdapters(result("PACKAGE","SEALED"),result("PREFLIGHT","READY"),result("WORKER","COMPLETED"),
            result("REVIEW","PASS"),result("REMEDIATION","PASS"),result("CHECKPOINT","CHECKPOINTED"),result("EXIT","EXITED"),result("HANDOFF","SEALED"))
        full_auth=create_gate_authorization(self.plan,"AUTH-FULL",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
        requirements={item.lv_id: CapabilityRequirement("existing-agent",item.gate_id,item.lv_id,("read",),tuple(item.owned_files) or ("fixture/noop",)) for item in self.plan.lvs}
        def prerequisite(context, requirement, checkpoint):
            calls.append(("CAPABILITY", context["lv_id"]))
            dry=DryRunExecutionContext(context["project_id"],context["gate_id"],context["lv_id"],context["plan_sha256"],str(self.root))
            return run_operational_capability_dry_run(context=dry,requirement=requirement,agent_registry={"existing-agent":object()},checkpoint=checkpoint)
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=full_auth):
            with self.assertRaisesRegex(Exception, "TEST_ONLY"):
                execute_gate(self.root,"GATE-1","run-cap-production",harness_root=self.root.parent,adapters=adapters,
                    approval_evidence=self.approval_evidence("cap-approval.json"),requirements_sha256="b"*64,
                    branch="main",head="c"*40,mode=FULL_PLAN,requirement_evidence=self.requirement_evidence(),
                    capability_requirements=requirements,capability_prerequisite=prerequisite,
                    capability_checkpoints={},dry_run_capability_resolution=True)
            outcome=execute_gate(self.root,"GATE-1","run-cap",harness_root=self.root.parent,adapters=adapters,
                approval_evidence=self.approval_evidence("cap-approval.json"),requirements_sha256="b"*64,
                branch="main",head="c"*40,mode=FULL_PLAN,requirement_evidence=self.requirement_evidence(),
                capability_requirements=requirements,capability_prerequisite=prerequisite,
                capability_checkpoints={},dry_run_capability_resolution=True,
                legacy_test_only_capability=True)
        self.assertEqual(outcome["status"],"GATE_EXIT")
        for item in self.plan.lvs:
            lv=item.lv_id
            self.assertLess(calls.index(("PREFLIGHT",lv)),calls.index(("CAPABILITY",lv)))
            self.assertLess(calls.index(("CAPABILITY",lv)),calls.index(("WORKER",lv)))
        self.assertTrue(all(lifecycle["capability"]["gate_passed"] is False for lifecycle in outcome["lifecycles"]))
        self.assertTrue(all(lifecycle["trace"][:3] == ["PACKAGE","PREFLIGHT","WORKER"] for lifecycle in outcome["lifecycles"]))

    def test_full_plan_approval_does_not_bypass_capability_approval(self) -> None:
        from runtime.orchestrator.gate_orchestrator import execute_gate
        from runtime.orchestrator.operational_capability import OperationalCapabilityResult
        from runtime.orchestrator.schemas import CapabilityRequirement
        calls=[]
        def result(stage, status):
            def invoke(context): calls.append(stage); return {"status":status,"exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True}
            return invoke
        adapters=GateControllerAdapters(result("PACKAGE","SEALED"),result("PREFLIGHT","READY"),result("WORKER","COMPLETED"),
            result("REVIEW","PASS"),result("REMEDIATION","PASS"),result("CHECKPOINT","CHECKPOINTED"),result("EXIT","EXITED"),result("HANDOFF","SEALED"))
        full_auth=create_gate_authorization(self.plan,"AUTH-FULL",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
        requirements={item.lv_id: CapabilityRequirement("gap",item.gate_id,item.lv_id,("read",),tuple(item.owned_files) or ("fixture/noop",)) for item in self.plan.lvs}
        blocked=lambda context,requirement,checkpoint: OperationalCapabilityResult("BLOCKED","GAP",False,None,{},"DISCOVERY_APPROVAL","separate approval required")
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=full_auth), \
             self.assertRaisesRegex(Exception,"capability resolution"):
            execute_gate(self.root,"GATE-1","run-blocked",harness_root=self.root.parent,adapters=adapters,
                approval_evidence=self.approval_evidence("blocked-approval.json"),requirements_sha256="b"*64,
                branch="main",head="c"*40,mode=FULL_PLAN,requirement_evidence=self.requirement_evidence(),
                capability_requirements=requirements,capability_prerequisite=blocked,
                capability_checkpoints={},dry_run_capability_resolution=True,
                legacy_test_only_capability=True)
        self.assertEqual(calls,["PACKAGE","PREFLIGHT"])

    def test_execute_gate_canonical_declared_none_calls_worker_without_capability_modules(self):
        from runtime.orchestrator.gate_orchestrator import execute_gate
        calls=[]; plan=self.canonical_capability_plan({"version":"v1","mode":"DECLARED_NONE","requirements":[]})
        auth=create_gate_authorization(plan,"AUTH-CANONICAL",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.operational_capability.run_concrete_module_fixture_dry_run") as concrete:
            outcome=execute_gate(self.root,"GATE-1","canonical-none",harness_root=self.root.parent,
                adapters=self.lifecycle_adapters(calls),approval_evidence=self.approval_evidence("canonical-none.json"),
                requirements_sha256="b"*64,branch="main",head="c"*40,mode=FULL_PLAN,
                requirement_evidence=self.requirement_evidence())
        self.assertEqual(outcome["status"],"GATE_EXIT"); concrete.assert_not_called()
        self.assertEqual([stage for stage,_ in calls].count("WORKER"),3)
        self.assertTrue(all(item["capability"]["status"] == "NO_CAPABILITY_REQUIREMENT" for item in outcome["lifecycles"]))

    def test_execute_gate_canonical_project_and_agent_existing_fast_paths(self):
        from runtime.orchestrator.gate_orchestrator import execute_gate
        from runtime.orchestrator.operational_capability import CanonicalCapabilityRuntimeSources
        from runtime.orchestrator.project_isolation import ProjectIsolation
        source_ref="gate/GATE-1/lv/G1-LV3-1/capability_contract/requirements/0"
        for capability,manifest in (("cap",{"asset_id":"project-cap","scope":"project","capabilities":["cap"],
                                             "permissions":["read"],"owned_files":["app/","tests/"]}),
                                    ("implementation_agent",None)):
            with self.subTest(capability=capability):
                contract={"version":"v1","mode":"REQUIRED","requirements":[{"capability_id":capability,
                          "required_permissions":["read"],"source_ref":source_ref}]}
                plan=self.canonical_capability_plan(contract); calls=[]
                auth=create_gate_authorization(plan,"AUTH-EXISTING",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
                isolation=ProjectIsolation(self.root.parent,self.root,self.plan.project_id,"project-one",{"project-one":self.plan.project_id})
                evidence={}
                if manifest is not None:
                    raw=json.dumps(manifest,sort_keys=True).encode(); reference=f"inventory/{capability}.json"
                    isolation.write_exclusive("artifact",reference,raw); evidence[reference]=hashlib.sha256(raw).hexdigest()
                sources=CanonicalCapabilityRuntimeSources(isolation,evidence,{})
                with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan), \
                     patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
                     patch("runtime.orchestrator.operational_capability.run_concrete_module_fixture_dry_run") as concrete:
                    outcome=execute_gate(self.root,"GATE-1",f"existing-{capability}",harness_root=self.root.parent,
                        adapters=self.lifecycle_adapters(calls),approval_evidence=self.approval_evidence(f"existing-{capability}.json"),
                        requirements_sha256="b"*64,branch="main",head="c"*40,mode=FULL_PLAN,
                        requirement_evidence=self.requirement_evidence(),canonical_capability_sources={"G1-LV3-1":sources})
                concrete.assert_not_called(); self.assertEqual(outcome["status"],"GATE_EXIT")
                first=outcome["lifecycles"][0]["capability"]
                self.assertEqual(first["status"],"EXISTING_CAPABILITY_READY")
                self.assertTrue(first["existing_decision"]["decision_digest"])
                self.assertEqual([stage for stage,_ in calls].count("WORKER"),3)

    def test_execute_gate_canonical_undeclared_and_global_unavailable_never_call_worker(self):
        from runtime.orchestrator.gate_orchestrator import execute_gate
        from runtime.orchestrator.operational_capability import CanonicalCapabilityRuntimeSources
        from runtime.orchestrator.project_isolation import ProjectIsolation
        for mode in ("UNDECLARED","GLOBAL"):
            with self.subTest(mode=mode):
                calls=[]
                if mode == "UNDECLARED": plan=self.plan; source_map=None
                else:
                    ref="gate/GATE-1/lv/G1-LV3-1/capability_contract/requirements/0"
                    plan=self.canonical_capability_plan({"version":"v1","mode":"REQUIRED","requirements":[
                        {"capability_id":"global-cap","required_permissions":["read"],"source_ref":ref}]})
                    isolation=ProjectIsolation(self.root.parent,self.root,self.plan.project_id,"project-one",{"project-one":self.plan.project_id})
                    value={"asset_id":"global-cap","scope":"global","capabilities":["global-cap"],"permissions":["read"],"owned_files":["app/"]}
                    raw=json.dumps(value,sort_keys=True).encode(); reference="inventory/global.json"
                    isolation.write_exclusive("artifact",reference,raw)
                    source_map={"G1-LV3-1":CanonicalCapabilityRuntimeSources(isolation,{},
                        {reference:hashlib.sha256(raw).hexdigest()})}
                auth=create_gate_authorization(plan,"AUTH-BLOCK",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
                with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan), \
                     patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
                     self.assertRaisesRegex(Exception,"canonical capability prerequisite blocked"):
                    execute_gate(self.root,"GATE-1",f"blocked-{mode}",harness_root=self.root.parent,
                        adapters=self.lifecycle_adapters(calls),approval_evidence=self.approval_evidence(f"blocked-{mode}.json"),
                        requirements_sha256="b"*64,branch="main",head="c"*40,mode=FULL_PLAN,
                        requirement_evidence=self.requirement_evidence(),canonical_capability_sources=source_map)
                self.assertEqual(calls,[("PACKAGE","G1-LV3-1"),("PREFLIGHT","G1-LV3-1")])

    def test_execute_gate_canonical_gap_uses_actual_approval_loader_and_concrete_modules(self):
        from tests.test_operational_capability import OperationalCapabilityTests
        from runtime.orchestrator.gate_orchestrator import GateLV, GatePlan, execute_gate
        from runtime.orchestrator.operational_capability import (
            CapabilityApprovalEvidenceRef, CanonicalCapabilityRuntimeSources,
            run_concrete_module_fixture_dry_run,
        )
        from runtime.orchestrator.project_isolation import ProjectIsolation
        import runtime.orchestrator.operational_capability as capability_module
        helper=OperationalCapabilityTests(); helper.setUp()
        with tempfile.TemporaryDirectory() as temp:
            root,kwargs,install_factory,use_factory=helper.concrete_fixture(temp)
            seeded=run_concrete_module_fixture_dry_run(**kwargs,install_approval_factory=install_factory,
                                                       use_approval_factory=use_factory)
            self.assertEqual(seeded.status,"READY_FOR_WORKER",seeded.blocked_reason)
            source_ref="gate/G1/lv/LV1/capability_contract/requirements/0"
            contract={"version":"v1","mode":"REQUIRED","requirements":[{"capability_id":"cap",
                      "required_permissions":["read"],"source_ref":source_ref}]}
            lv=GateLV("G1","LV1",1,"capability",[],["tests/"],["pass"],"sequential",["tests/test_x.py"],contract)
            plan=GatePlan("project",str(root),"G1","PLAN.md",kwargs["context"].canonical_plan_sha256,[lv])
            auth=create_gate_authorization(plan,"AUTH-GAP",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
            namespace=Path(temp)/"namespace"; namespace.mkdir()
            isolation=ProjectIsolation(namespace,root,"project","project",{"project":"project"})
            approvals={"discovery":kwargs["discovery_approval"],"install":helper.concrete_created["install"],
                       "use":helper.concrete_created["use"]}
            refs={}
            for name,value in approvals.items():
                raw=json.dumps(asdict(value)).encode(); relative=f"capability/{name}.json"
                isolation.write_exclusive("approval",relative,raw)
                refs[name]=CapabilityApprovalEvidenceRef(relative,hashlib.sha256(raw).hexdigest())
            def sources(names,ledger):
                return CanonicalCapabilityRuntimeSources(
                    isolation,{}, {},refs["discovery"] if "discovery" in names else None,
                    refs["install"] if "install" in names else None,refs["use"] if "use" in names else None,
                    kwargs["discovery_transport"],kwargs["resolution_transport"],kwargs["http_executor"],
                    kwargs["fixture_repository_root"],kwargs["candidate_metadata"],ledger=ledger)
            actual_discovery=capability_module.run_http_read_only_discovery
            actual_installer=capability_module.install_project_skill
            actual_authorize=capability_module.authorize_candidate_use
            actual_transition=capability_module.transition_used_asset
            with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan), \
                 patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings"), \
                 patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
                 patch("runtime.orchestrator.operational_capability.run_http_read_only_discovery",wraps=actual_discovery) as discovery, \
                 patch("runtime.orchestrator.operational_capability.install_project_skill",wraps=actual_installer) as installer, \
                 patch("runtime.orchestrator.operational_capability.authorize_candidate_use",wraps=actual_authorize) as authorize, \
                 patch("runtime.orchestrator.operational_capability.transition_used_asset",wraps=actual_transition) as transition:
                cases=(((),"DISCOVERY",False),(('discovery',),"ADOPTION",False),
                       (("discovery","install"),"USE_AUTHORIZATION",False),
                       (("discovery","install","use"),"READY",True))
                for index,(names,blocked_stage,ready) in enumerate(cases):
                    calls=[]; ledger={"used_assets":[],"use_authorized_candidates":[],
                                     "use_authorization_evidence_references":[],"gate_passed":False}
                    if ready:
                        outcome=execute_gate(root,"G1",f"gap-{index}",harness_root=namespace,
                            adapters=self.lifecycle_adapters(calls),approval_evidence="unused",requirements_sha256="b"*64,
                            branch="main",head="c"*40,mode=FULL_PLAN,requirement_evidence={"REQ":{"status":"PENDING"}},
                            canonical_capability_sources={"LV1":sources(names,ledger)})
                        self.assertEqual(outcome["status"],"GATE_EXIT")
                        self.assertEqual(outcome["lifecycles"][0]["capability"]["status"],"DISCOVERED_CAPABILITY_READY")
                        self.assertEqual(len(ledger["used_assets"]),1); self.assertTrue(outcome["lifecycles"][0]["capability"]["runtime_selection"])
                        self.assertIn(("WORKER","LV1"),calls)
                    else:
                        with self.assertRaisesRegex(Exception,"canonical capability prerequisite blocked"):
                            execute_gate(root,"G1",f"gap-{index}",harness_root=namespace,
                                adapters=self.lifecycle_adapters(calls),approval_evidence="unused",requirements_sha256="b"*64,
                                branch="main",head="c"*40,mode=FULL_PLAN,requirement_evidence={"REQ":{"status":"PENDING"}},
                                canonical_capability_sources={"LV1":sources(names,ledger)})
                        self.assertNotIn(("WORKER","LV1"),calls); self.assertEqual(ledger["used_assets"],[])
                    if blocked_stage == "DISCOVERY": self.assertEqual(discovery.call_count,0)
                    if blocked_stage == "ADOPTION": self.assertEqual(installer.call_count,0)
                    if blocked_stage == "USE_AUTHORIZATION": self.assertGreaterEqual(authorize.call_count,1)
                    discovery.reset_mock(); installer.reset_mock(); authorize.reset_mock(); transition.reset_mock()

    def test_execute_gate_canonical_ready_does_not_turn_worker_failure_into_gate_pass(self):
        from runtime.orchestrator.gate_controller import GateControllerError
        from runtime.orchestrator.gate_orchestrator import GateLV, GatePlan, execute_gate
        from runtime.orchestrator.operational_capability import CanonicalCapabilityRuntimeSources
        from runtime.orchestrator.project_isolation import ProjectIsolation
        source_ref="gate/G1/lv/LV1/capability_contract/requirements/0"
        contract={"version":"v1","mode":"REQUIRED","requirements":[{"capability_id":"cap",
                  "required_permissions":["read"],"source_ref":source_ref}]}
        plan=GatePlan("project",str(self.root),"G1","PLAN.md", "a"*64,
                      [GateLV("G1","LV1",1,"capability",[],["app/"],["pass"],"sequential",[],contract)])
        auth=create_gate_authorization(plan,"AUTH-WORKER-FAIL",mode=FULL_PLAN,full_plan_opt_in=True,project_final_validation=True)
        isolation=ProjectIsolation(self.root.parent,self.root,"project-one","project-one",{"project-one":"project-one"})
        value={"asset_id":"project-cap","scope":"project","capabilities":["cap"],"permissions":["read"],"owned_files":["app/"]}
        raw=json.dumps(value,sort_keys=True).encode(); reference="inventory/worker-fail.json"
        isolation.write_exclusive("artifact",reference,raw)
        sources=CanonicalCapabilityRuntimeSources(isolation,{reference:hashlib.sha256(raw).hexdigest()}, {})
        captured=[]
        import runtime.orchestrator.operational_capability as capability_module
        actual_prerequisite=capability_module.run_canonical_capability_prerequisite
        def capture_prerequisite(**kwargs):
            result=actual_prerequisite(**kwargs); captured.append(result); return result
        def worker(context):
            raise GateControllerError("worker fixture failed")
        adapters=GateControllerAdapters(
            lambda context:{"status":"SEALED","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True},
            lambda context:{"status":"READY","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True},
            worker,lambda context:{"status":"PASS","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True},
            lambda context:{"status":"PASS","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True},
            lambda context:{"status":"CHECKPOINTED","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True},
            lambda context:{"status":"EXITED","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True},
            lambda context:{"status":"SEALED","exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True})
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan), \
             patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings"), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.operational_capability.run_canonical_capability_prerequisite",side_effect=capture_prerequisite), \
             self.assertRaisesRegex(GateControllerError,"worker fixture failed"):
            execute_gate(self.root,"G1","worker-failure",harness_root=self.root.parent,adapters=adapters,
                approval_evidence="unused",requirements_sha256="b"*64,branch="main",head="c"*40,mode=FULL_PLAN,
                requirement_evidence={"REQ":{"status":"PENDING"}},canonical_capability_sources={"LV1":sources})
        self.assertTrue(captured and captured[0].status == "EXISTING_CAPABILITY_READY")
        self.assertFalse(captured[0].gate_passed)

    def test_operational_capability_checkpoint_is_bound_and_tamper_evident(self) -> None:
        from runtime.orchestrator.gate_orchestrator import _load_capability_checkpoint, _save_capability_checkpoint
        path=self.root/"capability-checkpoint.json"
        records={"DISCOVERY":{"sealed":True}}
        _save_capability_checkpoint(path,project_id=self.plan.project_id,gate_id="GATE-1",lv_id="G1-LV3-1",
                                    canonical_plan_sha256=self.plan.canonical_plan_sha256,stage_records=records)
        self.assertEqual(_load_capability_checkpoint(path,project_id=self.plan.project_id,gate_id="GATE-1",lv_id="G1-LV3-1",
                         canonical_plan_sha256=self.plan.canonical_plan_sha256),records)
        value=json.loads(path.read_text()); value["payload"]["lv_id"]="OTHER"; path.write_text(json.dumps(value))
        with self.assertRaises(GateOrchestrationError):
            _load_capability_checkpoint(path,project_id=self.plan.project_id,gate_id="GATE-1",lv_id="G1-LV3-1",
                                        canonical_plan_sha256=self.plan.canonical_plan_sha256)

    def test_worker_capability_evidence_reaches_handoff_before_seal(self) -> None:
        from runtime.orchestrator.gate_controller import run_gate_lifecycle
        captured=[]
        def stage(status, payload=None):
            def invoke(context):
                if payload is not None: captured.append(context)
                return {"status":status,"exit_code":0,"evidence_sha256":"a"*64,"hard_stop":True, **(payload or {})}
            return invoke
        capability={"capability_projection":{"used_assets":["installed-skill:sha256:"+"b"*64]},"runtime_selection":{"simulated":True}}
        adapters=GateControllerAdapters(stage("SEALED"),stage("READY"),stage("COMPLETED",capability),stage("PASS"),stage("PASS"),stage("CHECKPOINTED"),stage("EXITED"),stage("SEALED",{"seen":True}))
        result=run_gate_lifecycle({"project_id":"project","gate_id":"GATE-1","lv_id":"LV1","run_id":"run","plan_sha256":"a"*64},adapters)
        self.assertEqual(result["status"],"SYSTEM_TRANSITION")
        self.assertTrue(captured and captured[-1].get("worker_result",{}).get("capability_projection"))


if __name__ == "__main__": unittest.main()
