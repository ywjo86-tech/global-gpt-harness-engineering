from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.full_mcp import qualification as q
from runtime.full_mcp.git_service import GitService
from runtime.full_mcp.path_policy import WorkspacePathPolicy
from runtime.full_mcp.recovery_integration import plan_integrated_recovery

SHA = "a" * 64
NOW = "2026-09-16T14:50:00Z"


def validation_result() -> dict:
    snapshot={"source_set_name":"RECOVERY_FIXTURE","files":[{"path":"runtime/full_mcp/git_service.py","sha256":SHA,"mode":"0644"}],"artifact_inputs":[]}
    snapshot["snapshot_digest"]=q.source_snapshot_digest(snapshot)
    rec={"schema_version":"gch.full-mcp.validation-result.v1","project_id":"GH-FULL-MCP-PH4","run_id":"r","attempt":1,
         "test_id":"TEST-012","consumer_task_id":"TASK-011","producer_task_id":"TASK-011","test_contract_digest":SHA,
         "profile_id":None,"profile_digest":None,"selector_digest":SHA,"started_at_utc":NOW,"ended_at_utc":NOW,
         "verdict":"PASS","exit_status_category":"EXIT_0","assertion_summary_digest":SHA,"audit_ref":"audit#1","audit_digest":SHA,"source_snapshot":snapshot}
    return q.seal_digest(rec,"result_digest")


def evidence(result: dict) -> dict:
    ref="attempts/1/validation-results/TEST-012/TASK-011.json"
    binding={"head_sha":"1"*40,"origin_main_sha":"1"*40,"phase3_sealed_sha":"2"*40,"dependency_lock_sha256":SHA,
             "invocation_context_id":"ctx-test","workspace_state_digest":SHA}
    rec={"schema_version":"gch.full-mcp.evidence.v2","evidence_id":"EVD-005","project_id":"GH-FULL-MCP-PH4","run_id":"r",
         "origin_gate_id":"GATE-002","attempt":1,"requirement_refs":["REQ-013"],"task_refs":["TASK-011"],"test_refs":["TEST-012"],
         "producer_task_id":"TASK-011","validation_result_refs":[{"test_id":"TEST-012","source_attempt":1,"consumer_task_id":"TASK-011","relative_path":ref,"result_digest":result["result_digest"]}],
         "artifact_refs":[],"verdict":"PASS","collected_at_utc":NOW,"source_binding":binding}
    return q.seal_digest(rec,"record_digest")


def gate(evd: dict) -> dict:
    binding={"head_sha":"1"*40,"origin_main_sha":"1"*40,"phase3_sealed_sha":"2"*40,"dependency_lock_sha256":SHA,
             "invocation_context_id":"ctx-test","workspace_state_digest":SHA}
    rec={"schema_version":"gch.full-mcp.gate-decision.v2","gate_id":"GATE-002","project_id":"GH-FULL-MCP-PH4","run_id":"r","attempt":1,
         "decision":"GO","required_evidence":["EVD-005"],"evidence_digests":{"EVD-005":evd["record_digest"]},
         "prerequisite_gate_states":{"GATE-001":"GO"},"official_acceptance_results":{"Filesystem":"PASS"},
         "review_ref":"review.json","review_digest":SHA,"blocker_count":0,"major_count":0,"source_binding":binding,
         "selection_index_ref":"index.json","selection_index_digest":SHA,"evaluated_at_utc":NOW}
    return q.seal_digest(rec,"record_digest")


class RecoveryIntegrationTests(unittest.TestCase):
    def test_changed_source_invalidates_prerequisite_and_returns_to_same_failed_gate(self) -> None:
        vr=validation_result(); ev=evidence(vr); g2=gate(ev)
        vr_ref="attempts/1/validation-results/TEST-012/TASK-011.json"; ev_ref="attempts/1/evidence/EVD-005.json"
        plan=plan_integrated_recovery(error_code="VALIDATION_FAILED",effect_state="NOT_STARTED",state_changing=True,
            changed_paths=["runtime/full_mcp/git_service.py"],validation_results_by_path={vr_ref:vr},evidence_by_path={ev_ref:ev},
            gate_records={"GATE-002":g2},originally_failed_gate="GATE-003")
        self.assertEqual(plan.classification,"REMEDIATION_REQUIRED")
        self.assertFalse(plan.auto_retry_allowed); self.assertEqual(plan.earliest_reentry_gate,"GATE-002")
        self.assertEqual(plan.gate_reentry_sequence,("GATE-002","GATE-003"))
        self.assertEqual(plan.required_sequence[-1],"REEVALUATE:GATE-003")

    def test_ambiguous_effect_never_auto_replays_and_same_gate_is_retained(self) -> None:
        plan=plan_integrated_recovery(error_code="INTERNAL_ERROR",effect_state="BLOCKED_RECOVERY_AMBIGUOUS",state_changing=True,
            changed_paths=[],validation_results_by_path={},evidence_by_path={},gate_records={},originally_failed_gate="GATE-002")
        self.assertEqual(plan.classification,"RECOVERY_REQUIRED"); self.assertFalse(plan.auto_retry_allowed)
        self.assertTrue(plan.requires_restore_or_remediation); self.assertEqual(plan.gate_reentry_sequence,("GATE-002",))

    def test_bounded_git_restore_composes_with_recovery_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); subprocess.check_call(["git","init","-q"],cwd=root)
            subprocess.check_call(["git","config","user.email","recovery@example.invalid"],cwd=root)
            subprocess.check_call(["git","config","user.name","Recovery Test"],cwd=root)
            (root/"owned").mkdir(); target=root/"owned/a.txt"; target.write_text("base\n")
            subprocess.check_call(["git","add","owned/a.txt"],cwd=root); subprocess.check_call(["git","commit","-qm","base"],cwd=root)
            target.write_text("changed\n")
            policy=WorkspacePathPolicy(root.resolve(),read_scopes=(".",),mutable_scopes=("owned",))
            result=GitService(root.resolve(),policy).restore(["owned/a.txt"],source_ref="HEAD")
            self.assertEqual(result["restored_paths"],["owned/a.txt"]); self.assertEqual(target.read_text(),"base\n")
            plan=plan_integrated_recovery(error_code="PATCH_CONFLICT",effect_state="NOT_STARTED",state_changing=True,
                changed_paths=[],validation_results_by_path={},evidence_by_path={},gate_records={},originally_failed_gate="GATE-002")
            self.assertEqual(plan.required_sequence[1],"REMEDIATE_OR_RESTORE")


if __name__ == "__main__": unittest.main()
