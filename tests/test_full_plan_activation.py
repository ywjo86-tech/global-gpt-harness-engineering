from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from runtime.ai_office.full_plan_activation import AIFullPlanActivationContextV1
from runtime.orchestrator.approved_full_plan_binding import ExecutableAuthorityBundleV1, ValidatedGateAuthorityV1
from runtime.orchestrator.full_plan_activation import (
    FullPlanActivationError, FullPlanActivationStore,
    activate_approved_full_plan, build_executable_full_plan_job,
)
from runtime.orchestrator.production_full_plan_entry import preflight_job


def digest_obj(value) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


class FullPlanActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.project=self.base/"project"; self.project.mkdir(); (self.project/"docs").mkdir()
        self.plan=self.project/"docs/DEVELOPMENT_PLAN.txt"; self.plan.write_text("# Plan\n",encoding="utf-8")
        self.spec=self.project/"docs/spec.md"; self.spec.write_text("# Spec\n",encoding="utf-8")
        self.req=self.project/"docs/req.json"; self.req.write_text('{"schema_version":"orchestration.project-requirement-contract.v1","requirements":{}}\n',encoding="utf-8")
        subprocess.run(["git","init","-b","main"],cwd=self.project,check=True,capture_output=True)
        subprocess.run(["git","add","."],cwd=self.project,check=True)
        subprocess.run(["git","-c","user.name=Test","-c","user.email=test@localhost","commit","-m","base"],cwd=self.project,check=True,capture_output=True)
        self.head=subprocess.run(["git","rev-parse","HEAD"],cwd=self.project,check=True,capture_output=True,text=True).stdout.strip()

        self.state=self.base/"state"; self.state.mkdir()
        approval=self.state/"_workspace/global-gate/project/approval/a.json"; approval.parent.mkdir(parents=True); approval.write_text('{"approval":true}\n')
        engine=self.state/"_workspace/global-gate/project/artifact/e.json"; engine.parent.mkdir(parents=True); engine.write_text('{"engine":true}\n')
        self.approval=approval; self.engine=engine
        self.mapping=self.base/"authority/mappings"; self.mapping.mkdir(parents=True)

        self.runtime=self.base/"runtime-release"; entry=self.runtime/"runtime/orchestrator/production_full_plan_boot.py"; entry.parent.mkdir(parents=True); entry.write_text("# boot\n")
        source_head="a"*40; source_tree="b"*40
        unsigned={"schema_version":"gch.runtime-release.v2","source_head":source_head,"source_tree":source_tree,
                  "release_path":str(self.runtime),"runtime_entry":"runtime/orchestrator/production_full_plan_boot.py",
                  "runtime_entry_sha256":sha(entry),"publication_head":source_head}
        self.release_digest=digest_obj(unsigned)
        (self.runtime/"RUNTIME_RELEASE_MANIFEST.json").write_text(json.dumps({**unsigned,"manifest_sha256":self.release_digest},sort_keys=True),encoding="utf-8")
        gate=ValidatedGateAuthorityV1(
            gate_id="GATE-001", approval_evidence_path=str(approval), approval_evidence_sha256=sha(approval),
            requirements_sha256="1"*64, engine_requirement_evidence_path=str(engine), engine_requirement_evidence_sha256=sha(engine),
            project_requirement_evidence_paths_by_lv=(("TASK-001",str(self.req),sha(self.req)),), lv_order=("TASK-001",),
        )
        self.bundle=ExecutableAuthorityBundleV1(
            schema_version="orchestration.executable-authority-bundle.v1", activation_request_id="FP-ACT-1", request_digest="2"*64,
            project_alias="demo", project_id="project", project_root=str(self.project), authority_root=str(self.base/"authority"), mapping_root=str(self.mapping),
            approved_plan_path="docs/DEVELOPMENT_PLAN.txt", approved_plan_sha256=sha(self.plan), approved_spec_path="docs/spec.md", approved_spec_sha256=sha(self.spec),
            approval_ref="USER-APPROVAL-1", expected_branch="main", expected_head=self.head,
            runtime_release_digest=self.release_digest, runtime_release_source_head=source_head, runtime_code_root=str(self.runtime), gates=(gate,),
        )
        self.context=AIFullPlanActivationContextV1(
            schema_version="ai-office.full-plan-activation-context.v1", activation_request_id="FP-ACT-1", project_id="project", office_run_id="FP-ACT-1",
            requirement_id="approved-full-plan:FP-ACT-1", requirement_envelope_digest="3"*64,
            approved_plan_digest=self.bundle.approved_plan_sha256, approved_spec_digest=self.bundle.approved_spec_sha256,
            approval_ref=self.bundle.approval_ref, expected_head=self.head, executable_authority_bundle_digest=self.bundle.bundle_digest,
            gate_ids=("GATE-001",), workflow_state="INTAKE_READY", workflow_revision=1, workflow_state_digest="4"*64,
        )

    def tearDown(self): self.tmp.cleanup()

    def test_builder_emits_generic_auto_reconcile_job_without_executor_kind(self):
        job=build_executable_full_plan_job(self.bundle,ai_context=self.context,harness_state_root=self.state)
        self.assertEqual(job["schema_version"],"orchestration.production-full-plan-job.v1")
        self.assertEqual(job["execution_owner"],"AUTO_RECONCILE"); self.assertNotIn("executor_kind",job)
        self.assertEqual(job["mapping_root"],str(self.mapping)); self.assertEqual(job["runtime_release_digest"],self.release_digest)
        self.assertEqual(job["runtime_release_source_head"],"a"*40); self.assertEqual(job["expected_branch"],"main"); self.assertEqual(job["expected_head"],self.head)
        self.assertEqual(job["activation_binding_digest"],self.bundle.request_digest); self.assertEqual(job["executable_authority_bundle_digest"],self.bundle.bundle_digest)
        self.assertEqual(job["ai_office_context_digest"],self.context.context_digest)

    def test_builder_uses_only_validated_gate_authority(self):
        gate=build_executable_full_plan_job(self.bundle,ai_context=self.context,harness_state_root=self.state)["gates"][0]
        self.assertEqual(gate["approval_evidence"],str(self.approval)); self.assertEqual(gate["approval_evidence_sha256"],sha(self.approval))
        self.assertEqual(gate["requirement_evidence_path"],str(self.engine)); self.assertEqual(gate["requirement_evidence_sha256"],sha(self.engine))
        self.assertEqual(gate["requirement_evidence_paths_by_lv"],{"TASK-001":str(self.req)})
        self.assertEqual(gate["requirement_evidence_sha256_by_lv"],{"TASK-001":sha(self.req)})
        self.assertTrue(gate["full_plan_opt_in"]); self.assertTrue(gate["project_final_validation"])

    def test_activation_requires_preflight_pass_before_register_job(self):
        with patch("runtime.orchestrator.full_plan_activation.preflight_job",return_value={"status":"BLOCK","reason":"SOURCE"}), \
             patch("runtime.orchestrator.full_plan_activation.register_job") as registrar:
            with self.assertRaisesRegex(FullPlanActivationError,"ACTIVATION_PREFLIGHT_BLOCKED"):
                activate_approved_full_plan(self.bundle,ai_context=self.context,harness_state_root=self.state)
        registrar.assert_not_called()

    def test_preflight_revalidates_expected_head_and_authority_artifact_digests(self):
        job=build_executable_full_plan_job(self.bundle,ai_context=self.context,harness_state_root=self.state)
        self.assertEqual(preflight_job(job)["status"],"PASS")
        self.approval.write_text("drift\n")
        result=preflight_job(job); self.assertEqual(result["status"],"BLOCK"); self.assertIn("GATE_AUTHORITY_EVIDENCE_DRIFT",result["reason"])

    def test_preflight_revalidates_source_head(self):
        job=build_executable_full_plan_job(self.bundle,ai_context=self.context,harness_state_root=self.state)
        (self.project/"drift.txt").write_text("x"); subprocess.run(["git","add","drift.txt"],cwd=self.project,check=True)
        subprocess.run(["git","-c","user.name=Test","-c","user.email=test@localhost","commit","-m","drift"],cwd=self.project,check=True,capture_output=True)
        self.assertEqual(preflight_job(job)["reason"],"SOURCE_HEAD_MISMATCH")

    def test_activate_registers_generic_job_and_replay_store_calls_registrar_once(self):
        result=activate_approved_full_plan(self.bundle,ai_context=self.context,harness_state_root=self.state)
        self.assertEqual(result.status,"FULL_PLAN_REGISTERED"); self.assertTrue(Path(result.canonical_job_path).is_file()); self.assertEqual(len(result.authority_digest),64)
        store=FullPlanActivationStore(self.state); calls=[]
        def registrar(): calls.append(1); return result
        first=store.record_or_load(request_id="FP-ACT-1",bundle=self.bundle,registrar=registrar)
        second=store.record_or_load(request_id="FP-ACT-1",bundle=self.bundle,registrar=registrar)
        self.assertEqual(first,second); self.assertEqual(len(calls),1); self.assertEqual(first.executable_authority_bundle_digest,self.bundle.bundle_digest)

    def test_replay_conflict_blocks_without_second_registrar_call(self):
        result=activate_approved_full_plan(self.bundle,ai_context=self.context,harness_state_root=self.state)
        store=FullPlanActivationStore(self.state); store.record_or_load(request_id="FP-ACT-1",bundle=self.bundle,registrar=lambda:result)
        changed=replace(self.bundle,approved_spec_sha256="f"*64); calls=[]
        with self.assertRaisesRegex(FullPlanActivationError,"ACTIVATION_REPLAY_CONFLICT"):
            store.record_or_load(request_id="FP-ACT-1",bundle=changed,registrar=lambda:calls.append(1))
        self.assertEqual(calls,[])


if __name__=="__main__": unittest.main()
