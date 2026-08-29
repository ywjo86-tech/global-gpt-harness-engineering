from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import (
    FULL_PLAN, GATE_BY_GATE, RESUME, GateAuthorization, GateOrchestrationError,
    advance_lifecycle, compatibility_dry_run, create_gate_authorization, derive_transition,
    gate_exit_action, initial_ledger, load_gate_plan, namespace_root, onboarding_dry_run, recovery_checkpoint,
    resume_from_checkpoint, select_assets, structured_handoff, validate_authorization,
    validate_concurrent_ownership, validate_handoff, validate_ledger, validate_owned_access,
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
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "project-one"; self.root.mkdir()
        self.plan_path = self.root / "PLAN.md"; self.plan_path.write_text(PLAN)
        self.plan_hash = hashlib.sha256(self.plan_path.read_bytes()).hexdigest()
        self.mapping = SimpleNamespace(canonical_source=self.plan_path, canonical_sha256=self.plan_hash)
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=self.mapping):
            self.plan = load_gate_plan(self.root, "GATE-1")
        self.auth = create_gate_authorization(self.plan, "AUTH-G1")

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
        self.assertEqual(result["selected"], ["global-project-orchestrator", "project-specialist"])
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


if __name__ == "__main__": unittest.main()
