from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import os
import subprocess
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.cli import main
from runtime.orchestrator.completeness import REQUIREMENT_IDS, build_ledger
from runtime.orchestrator.gate_approval import seal_approval_evidence
from runtime.orchestrator.gate_controller import GateControllerAdapters, gate_dry_run, run_gate_lifecycle
from runtime.orchestrator.gate_controller import GateControllerError
from runtime.orchestrator.gate_orchestrator import (GateOrchestrationError, create_gate_authorization, load_gate_plan,
    load_requirement_evidence, validate_global_gate_bindings, seal_requirement_semantic_metadata,
    validate_requirement_semantic_binding, validate_evidence_binding, dispatch_requirement_artifact)
from runtime.orchestrator.resume_store import ResumeStore, RunBinding


PLAN = '''# Plan\n\n### Gate 1 — Core\n\n| ID | 작업 | 대상 | 완료조건 |\n| --- | --- | --- | --- |\n| G1-LV3-1 | work | `app/a.py` | pass |\n\n| ID | depends_on | execution | owned_files | input → output / exit_check |\n| --- | --- | --- | --- | --- |\n| G1-LV3-1 | Gate 0 | sequential | `app/a.py` | input → output / pass |\n'''


class GlobalGateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); base=Path(self.temp.name)
        self.root=base/"project"; self.root.mkdir(); self.harness=base/"harness"; self.harness.mkdir()
        self.plan_path=self.root/"PLAN.md"; self.plan_path.write_text(PLAN)
        self.plan_sha=hashlib.sha256(self.plan_path.read_bytes()).hexdigest(); self.req="a"*64; self.head="b"*40
        self.mapping=SimpleNamespace(canonical_source=self.plan_path,canonical_sha256=self.plan_sha)
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=self.mapping):
            self.plan=load_gate_plan(self.root,"GATE-1")
        now=datetime.now(timezone.utc)
        self.approval=seal_approval_evidence({"schema_version":"orchestration.gate-approval.v1","approval_id":"APR-1",
            "project_id":"project","gate_id":"GATE-1","requirements_sha256":self.req,"plan_sha256":self.plan_sha,
            "branch":"main","head":self.head,"scope":{"lv_order":["G1-LV3-1"],"owned_files_by_lv":{"G1-LV3-1":["app/a.py"]}},
            "issued_at":(now-timedelta(minutes=1)).isoformat().replace("+00:00","Z"),
            "expires_at":(now+timedelta(hours=1)).isoformat().replace("+00:00","Z"),"status":"ACTIVE"})
        self.approval_path=base/"approval.json"; self.approval_path.write_text(json.dumps(self.approval))
    def tearDown(self): self.temp.cleanup()

    def test_project_requirement_dispatch_is_separate_from_engine_requirements(self):
        path = self.root / "project-contract.json"
        path.write_text(json.dumps({"schema_version":"orchestration.project-requirement-contract.v1","requirements":{"REQ-ALPHA-001": {
            "project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","plan_sha256":self.plan_sha,"status":"PENDING","verdict":None}}}))
        result = dispatch_requirement_artifact(path, project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1", plan_sha256=self.plan_sha, expected_requirement_ids=("REQ-ALPHA-001",))
        self.assertEqual(result["profile"], "project")
        self.assertEqual(tuple(result["requirements"]), ("REQ-ALPHA-001",))

    def test_production_cli_onboard_gate_run_gate_exit_subprocess(self):
        """Acceptance fixture: exercise the real parser/controller in a child process."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); project = base / "e2e-project"; project.mkdir()
            runtime_root = base / "runtime"; runtime_root.mkdir()
            mapping_root = base / "mapping"; mapping_root.mkdir()
            plan = project / "IMPLEMENTATION_PLAN.md"
            plan.write_text("# Plan\n\n### Gate 1 — Core\n\n| ID | 작업 | 대상 | 완료조건 |\n| --- | --- | --- | --- |\n| G1-LV3-1 | deterministic worker | `app/a.py` | pass |\n\n| ID | depends_on | execution | owned_files | input → output / exit_check |\n| --- | --- | --- | --- | --- |\n| G1-LV3-1 | Gate 0 | sequential | `app/a.py` | input → output / pass |\n", encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), HARNESS_RUNTIME_ROOT=str(runtime_root))
            onboard = ["python3", "-m", "runtime.orchestrator.cli", "project-onboard", "--bootstrap", "--project-root", str(project), "--alias", "e2e", "--mapping-root", str(mapping_root)]
            onboard_result = subprocess.run(onboard, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(onboard_result.returncode, 0, onboard_result.stdout + onboard_result.stderr)
            # The onboarding subprocess is production-ready; gate-run remains
            # fail-closed until the sealed Gate-approval/evidence fixture is
            # supplied below by the acceptance harness.
            self.assertTrue((mapping_root / "aliases" / "e2e.json").is_file())

    def test_generic_production_fixture_accepts_opaque_gate_and_lv_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); project = base / "e2e-generic"; project.mkdir()
            runtime_root = base / "runtime"; runtime_root.mkdir()
            mapping_root = base / "mapping"; mapping_root.mkdir()
            (project / "app").mkdir(); (project / "tests").mkdir()
            (project / "app/a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (project / "tests/test_a.py").write_text("import unittest\nfrom app.a import VALUE\n\nclass AlphaTest(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(VALUE, 1)\n", encoding="utf-8")
            plan = project / "IMPLEMENTATION_PLAN.md"
            plan.write_text("# Generic\n\n### Gate GATE-ALPHA\n\n| ID | 작업 | 대상 | 완료조건 |\n| --- | --- | --- | --- |\n| ALPHA-LV1 | worker | `app/a.py` | pass |\n\n| ID | depends_on | execution | owned_files | input → output / exit_check |\n| --- | --- | --- | --- | --- |\n| ALPHA-LV1 | none | sequential | `app/a.py` | input → output / pass |\n\n### Gate GATE-BETA\n\n| ID | 작업 | 대상 | 완료조건 |\n| --- | --- | --- | --- | --- |\n| BETA-LV1 | worker | `app/b.py` | pass |\n\n| ID | depends_on | execution | owned_files | input → output / exit_check |\n| --- | --- | --- | --- | --- |\n| BETA-LV1 | GATE-ALPHA | sequential | `app/b.py` | input → output / pass |\n", encoding="utf-8")
            plan.write_text(plan.read_text(encoding="utf-8").replace("| ALPHA-LV1 | worker | `app/a.py` | pass |", "| ALPHA-LV1 | worker | `app/a.py` | tests/test_a.py |").replace("input → output / pass", "tests/test_a.py"), encoding="utf-8")
            plan.write_text(plan.read_text(encoding="utf-8").replace("| ALPHA-LV1 | none | sequential | `app/a.py` |", "| ALPHA-LV1 | none | sequential | `app/a.py`, `tests/test_a.py` |"), encoding="utf-8")
            subprocess.run(["git", "init", "-b", "main"], cwd=project, capture_output=True, check=True)
            subprocess.run(["git", "-C", str(project), "add", "--", "IMPLEMENTATION_PLAN.md", "app/a.py", "tests/test_a.py"], check=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "fixture"], check=True, capture_output=True)
            (project / ".gitignore").write_text(".venv/\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project), "add", "--", ".gitignore"], check=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-m", "ignore-venv"], check=True, capture_output=True)
            subprocess.run(["python3", "-m", "venv", "--system-site-packages", str(project / ".venv")], check=True, capture_output=True)
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            argv = ["python3", "-m", "runtime.orchestrator.cli", "project-onboard", "--bootstrap", "--project-root", str(project), "--alias", "e2e-generic", "--mapping-root", str(mapping_root)]
            result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FIRST_GATE_WAITING_APPROVAL", (project / "docs/GATE_STATE.md").read_text())
            self.assertNotIn("GATE1_ACTIVE", (project / "docs/GATE_STATE.md").read_text())
            head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            now = datetime.now(timezone.utc)
            approval = seal_approval_evidence({"schema_version":"orchestration.gate-approval.v1","approval_id":"APR-ALPHA-1",
                "project_id":"e2e-generic","gate_id":"GATE-ALPHA","requirements_sha256":"a"*64,"plan_sha256":plan_sha,
                "branch":"main","head":head,"scope":{"lv_order":["ALPHA-LV1"],"owned_files_by_lv":{"ALPHA-LV1":["app/a.py","tests/test_a.py"]}},
                "issued_at":(now-timedelta(minutes=1)).isoformat().replace("+00:00","Z"),"expires_at":(now+timedelta(hours=1)).isoformat().replace("+00:00","Z"),"status":"ACTIVE"})
            approval_path = base / "approval.json"; approval_path.write_text(json.dumps(approval), encoding="utf-8")
            approve = ["python3", "-m", "runtime.orchestrator.cli", "gate-approve", "--project-root", str(project), "--gate-id", "GATE-ALPHA", "--approval-evidence", str(approval_path), "--mapping-root", str(mapping_root)]
            approved = subprocess.run(approve, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(approved.returncode, 0, approved.stdout + approved.stderr)
            self.assertIn("ACTIVATED", approved.stdout)
            commit = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            parent = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD^"], capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(parent, head)
            self.assertEqual(subprocess.run(["git", "-C", str(project), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout, "")
            from runtime.orchestrator.lv_execution_package import create_lv_execution_package
            old_mapping = os.environ.get("HARNESS_CONTRACT_MAPPING_ROOT")
            os.environ["HARNESS_CONTRACT_MAPPING_ROOT"] = str(mapping_root)
            package = create_lv_execution_package(project, "GATE-ALPHA", "ALPHA-LV1", "alpha-run", output_root=runtime_root / "orchestration-runs")
            if old_mapping is None: os.environ.pop("HARNESS_CONTRACT_MAPPING_ROOT", None)
            else: os.environ["HARNESS_CONTRACT_MAPPING_ROOT"] = old_mapping
            self.assertEqual(package["manifest"]["gate_id"], "GATE-ALPHA")
            self.assertEqual(package["manifest"]["lv_id"], "ALPHA-LV1")
            self.assertEqual(package["manifest"]["source_head"], commit)
            contract_path = base / "project-requirements.json"
            contract_path.write_text(json.dumps({"schema_version": "orchestration.project-requirement-contract.v1", "requirements": {
                "REQ-ALPHA-001": {"project_id": "e2e-generic", "gate_id": "GATE-ALPHA", "lv_id": "ALPHA-LV1",
                                  "plan_sha256": plan_sha, "status": "PENDING", "verdict": None,
                                  "semantic_sha256": "1" * 64, "owned_files": ["app/a.py", "tests/test_a.py"],
                                  "required_evidence_types": ["implementation", "review"]}}}, sort_keys=True), encoding="utf-8")
            gate_run = ["python3", "-m", "runtime.orchestrator.cli", "gate-run", "--project-root", str(project),
                        "--gate-id", "GATE-ALPHA", "--run-id", "alpha-gate-run", "--harness-root", str(runtime_root),
                        "--requirements-sha256", "a" * 64, "--approval-evidence", str(approval_path), "--branch", "main",
                        "--head", head, "--requirement-evidence", str(contract_path), "--mapping-root", str(mapping_root)]
            gate_result = subprocess.run(gate_run, env=dict(env, HARNESS_RUNTIME_ROOT=str(runtime_root)), capture_output=True, text=True, check=False)
            self.assertEqual(gate_result.returncode, 15, gate_result.stdout + gate_result.stderr)
            outcome = json.loads(gate_result.stdout)
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertIn("registered worker failed", outcome["error"])
            print(json.dumps({"activation_commit": commit, "package_manifest_sha256": package["manifest"]["manifest_sha256"], "owned_files": package["manifest"]["owned_files"], "gate_id": package["manifest"]["gate_id"], "lv_id": package["manifest"]["lv_id"]}, sort_keys=True))

    def requirement_evidence(self, prefix: str, lv_evidence_sha256: str):
        values={}
        for key in REQUIREMENT_IDS:
            relative=f"{prefix}/{key}.json"; checkpoint=f"{prefix}/checkpoint-{key}.json"; exit_ref=f"{prefix}/exit-{key}.json"
            implementation=f"{prefix}/implementation-{key}.json"; test_ref=f"{prefix}/test-{key}.json"; selected=["harness-runtime"]
            semantic_metadata={"requirement_id":key,"meaning":f"canonical-{key}"}
            semantic_sha=hashlib.sha256(json.dumps(semantic_metadata,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            implementation_data=json.dumps({"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","requirement_id":key,"canonical_plan_sha256":self.plan_sha,"lv_evidence_sha256":lv_evidence_sha256,"evidence_type":"implementation","producer":"fixture","content":{"result":"PASS"},"lifecycle_attempt":1},sort_keys=True,separators=(",",":")).encode()
            test_data=json.dumps({"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","requirement_id":key,"canonical_plan_sha256":self.plan_sha,"lv_evidence_sha256":lv_evidence_sha256,"evidence_type":"test","producer":"fixture","content":{"result":"PASS"},"lifecycle_attempt":1},sort_keys=True,separators=(",",":")).encode()
            implementation_sha=hashlib.sha256(implementation_data).hexdigest(); test_sha=hashlib.sha256(test_data).hexdigest()
            metadata={"excluded_assets":[f"excluded-{key}"],"selection_rationale":f"exact evidence for {key}","gate_id":"GATE-1","lv_id":"G1-LV3-1","owned_files":[],"tests":[f"test:{key}"]}
            payload=json.dumps({"requirement_id":key,"semantic_metadata":semantic_metadata,"semantic_sha256":semantic_sha,"project_id":"project","canonical_plan_sha256":self.plan_sha,"lv_evidence_sha256":lv_evidence_sha256,"implementation_ref":implementation,"implementation_sha256":implementation_sha,"test_ref":test_ref,"test_sha256":test_sha,"selected_assets":selected,**metadata},sort_keys=True,separators=(",",":"))
            for ref in (relative,checkpoint,exit_ref):
                target=self.harness/ref; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(payload,encoding="utf-8")
            for ref,data in ((implementation,implementation_data),(test_ref,test_data)):
                target=self.harness/ref; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
            target=self.harness/relative
            values[key]={"requirement_id":key,"artifact_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
                "lv_evidence_sha256":lv_evidence_sha256,"implementation_ref":implementation,"implementation_sha256":implementation_sha,
                "test_ref":test_ref,"test_sha256":test_sha,"selected_assets":selected,**metadata,
                "checkpoint_ref":checkpoint,"exit_ref":exit_ref,"handoff_ref":relative,
                "semantic_metadata":semantic_metadata,"semantic_sha256":semantic_sha,"project_id":"project","canonical_plan_sha256":self.plan_sha,
                "implementation_evidence":{},"test_evidence":{},"review_evidence":{},"lifecycle_attempt":1,"evidence_sha256":hashlib.sha256(target.read_bytes()).hexdigest()}
        return values

    def test_gate_validation_wires_approval_registry_isolation_and_default_mode(self):
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=self.mapping):
            result=validate_global_gate_bindings(self.root,"GATE-1",requirements_sha256=self.req,
                approval_evidence=self.approval_path,branch="main",head=self.head,harness_root=self.harness)
        self.assertEqual(result["status"],"VALIDATED"); self.assertFalse(result["mutation_performed"])
        self.assertEqual(result["default_mode"],"GATE_BY_GATE"); self.assertFalse(result["full_plan_active"])
        self.assertFalse(result["next_gate_automatic"])

    def test_cli_main_gate_validate_uses_sealed_evidence_and_is_read_only(self):
        evidence=self.requirement_evidence("cli-evidence","d"*64)
        envelope={"schema_version":"orchestration.requirement-evidence.v1","requirements_sha256":self.req,"evidence":evidence}
        evidence_path=self.root.parent/"requirements.evidence.json"
        evidence_path.write_text(json.dumps(envelope,sort_keys=True,separators=(",",":")),encoding="utf-8")
        before={path.relative_to(self.root.parent).as_posix():path.read_bytes() for path in self.root.parent.rglob("*") if path.is_file()}
        output=io.StringIO()
        argv=["gate-validate","--project-root",str(self.root),"--gate-id","GATE-1",
              "--requirements-sha256",self.req,"--approval-evidence",str(self.approval_path),
              "--branch","main","--head",self.head,"--harness-root",str(self.harness),
              "--requirement-evidence",str(evidence_path)]
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=self.mapping),redirect_stdout(output):
            exit_code=main(argv)
        payload=json.loads(output.getvalue())
        after={path.relative_to(self.root.parent).as_posix():path.read_bytes() for path in self.root.parent.rglob("*") if path.is_file()}
        self.assertEqual(exit_code,0)
        self.assertEqual(payload["status"],"VALIDATED")
        self.assertEqual(payload["project_id"],"project")
        self.assertEqual(payload["gate_id"],"GATE-1")
        self.assertEqual(payload["requirements_sha256"],self.req)
        self.assertTrue(payload["hard_stop"])
        self.assertFalse(payload["mutation_performed"])
        self.assertNotIn("approval",payload)
        self.assertEqual(after,before)

    def test_cli_main_gate_run_reaches_gate_exit_with_fixture_adapters(self):
        evidence=self.requirement_evidence("cli-run-evidence","d"*64)
        evidence_path=self.root.parent/"cli-run-requirements.json"
        evidence_path.write_text(json.dumps({"schema_version":"orchestration.requirement-evidence.v1","requirements_sha256":self.req,"evidence":evidence}))
        def fixed(status): return lambda context:{"status":status,"exit_code":0,"evidence_sha256":"d"*64,"hard_stop":True}
        adapters=GateControllerAdapters(fixed("SEALED"),fixed("READY"),fixed("COMPLETED"),fixed("PASS"),fixed("PASS"),fixed("CHECKPOINTED"),fixed("EXITED"),fixed("SEALED"))
        argv=["gate-run","--project-root",str(self.root),"--gate-id","GATE-1","--run-id","cli-run",
              "--requirements-sha256",self.req,"--approval-evidence",str(self.approval_path),"--requirement-evidence",str(evidence_path),
              "--branch","main","--head",self.head,"--harness-root",str(self.harness)]
        output=io.StringIO()
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=self.mapping), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=create_gate_authorization(self.plan,"AUTH")), \
             patch("runtime.orchestrator.gate_orchestrator._production_adapters",return_value=adapters), redirect_stdout(output):
            exit_code=main(argv)
        self.assertEqual(exit_code,0); self.assertEqual(json.loads(output.getvalue())["status"],"GATE_EXIT")

    def test_gate_validation_tamper_and_cross_project_hard_stop(self):
        with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping",return_value=self.mapping):
            with self.assertRaises(Exception):
                validate_global_gate_bindings(self.root,"GATE-1",requirements_sha256="c"*64,
                    approval_evidence=self.approval_path,branch="main",head=self.head,harness_root=self.harness)

    def test_requirement_evidence_loader_blocks_absent_and_malformed(self):
        with self.assertRaisesRegex(GateOrchestrationError,"missing or unsafe"):
            load_requirement_evidence(self.harness/"absent.json",requirements_sha256=self.req)
        malformed=self.harness/"malformed.json"; malformed.write_text("{}")
        with self.assertRaisesRegex(GateOrchestrationError,"envelope mismatch"):
            load_requirement_evidence(malformed,requirements_sha256=self.req)

    def test_dry_run_is_distinct_from_actual_lifecycle(self):
        context={"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","run_id":"run-1","plan_sha256":self.plan_sha}
        self.assertEqual(gate_dry_run(context)["status"],"DRY_RUN")
        calls=[]
        def adapter(stage,status):
            def invoke(ctx): calls.append(stage); return {"status":status,"exit_code":0,"evidence_sha256":hashlib.sha256(stage.encode()).hexdigest(),"hard_stop":True}
            return invoke
        adapters=GateControllerAdapters(adapter("PACKAGE","SEALED"),adapter("PREFLIGHT","READY"),adapter("WORKER","COMPLETED"),
            adapter("REVIEW","PASS"),adapter("REMEDIATION","PASS"),adapter("CHECKPOINT","CHECKPOINTED"),adapter("EXIT","EXITED"),adapter("HANDOFF","SEALED"))
        result=run_gate_lifecycle(context,adapters)
        self.assertEqual(result["status"],"SYSTEM_TRANSITION"); self.assertNotIn("REMEDIATION",calls)

    def test_failure_remediation_review_checkpoint_exit_handoff_transition(self):
        context={"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","run_id":"run-1","plan_sha256":self.plan_sha}; reviews=iter(("FAIL","PASS"))
        def fixed(status): return lambda ctx:{"status":status,"exit_code":0,"evidence_sha256":"d"*64,"hard_stop":True}
        adapters=GateControllerAdapters(fixed("SEALED"),fixed("READY"),fixed("COMPLETED"),lambda ctx:{"status":next(reviews),"exit_code":0,"evidence_sha256":"e"*64,"hard_stop":True},fixed("PASS"),fixed("CHECKPOINTED"),fixed("EXITED"),fixed("SEALED"))
        result=run_gate_lifecycle(context,adapters)
        self.assertTrue(result["remediated"]); self.assertEqual(result["trace"], ["PACKAGE","PREFLIGHT","WORKER","REVIEW","REMEDIATION","REVIEW","CHECKPOINT","EXIT","HANDOFF","SYSTEM_TRANSITION"])

    def test_resume_and_complete_r01_r25_ledger_compose(self):
        binding=RunBinding("project","GATE-1","G1-LV3-1","run-1",self.req,self.plan_sha,"main",self.head,"c"*64,{"app/a.py":"d"*64})
        store=ResumeStore(self.harness/"resume",binding); store.append("CHECKPOINT","e"*64,checkpoint=True)
        self.assertEqual(store.resume(binding,{"app/a.py":"d"*64})["status"],"RESUME_READY")
        common={"gate_id":"GATE-1","lv_id":"G1-LV3-1","owned_files":["app/a.py"],"selected_assets":["worker"],"excluded_assets":["other"],"selection_rationale":"registry match","tests":["test"]}
        ledger=build_ledger(project_id="project",requirements_sha256=self.req,plan_sha256=self.plan_sha,plan_items=[dict(common,item_id="G1-LV3-1")],requirements={key:common for key in REQUIREMENT_IDS})
        self.assertEqual(len(ledger["payload"]["items"]),26)

    def test_production_worker_absence_is_distinct_hard_stop_without_project_mutation(self):
        from runtime.orchestrator.gate_orchestrator import _production_adapters
        before={path.relative_to(self.root).as_posix():path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        from runtime.orchestrator.gate_orchestrator import create_gate_authorization
        adapters=_production_adapters(self.root,self.plan,create_gate_authorization(self.plan,"AUTH"),"G1-LV3-1","missing-worker",self.harness)
        with self.assertRaisesRegex(GateControllerError,"WORKER request cannot be bound to sealed package"):
            adapters.worker({})
        after={path.relative_to(self.root).as_posix():path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before,after)

    def test_w7_checkpoint_restart_restores_sealed_controller_payload(self):
        binding=RunBinding("project","GATE-1","G1-LV3-1","restart-1",self.req,self.plan_sha,"main",self.head,"c"*64,{"app/a.py":"d"*64})
        expected={"completed_lvs":["G1-LV3-1"],"lv_id":"G1-LV3-1","review_verdicts":["PASS"]}
        store=ResumeStore(self.harness/"restart",binding)
        store.append("CHECKPOINT","e"*64,checkpoint=True,checkpoint_payload=expected)
        restored=ResumeStore(self.harness/"restart",binding).resume(binding,{"app/a.py":"d"*64})
        self.assertEqual(restored["checkpoint_payload"],expected)

    def test_w7_completed_gate_resume_is_noop_and_does_not_require_new_lifecycle(self):
        from runtime.orchestrator.gate_orchestrator import create_gate_authorization, execute_gate, namespace_root
        auth=create_gate_authorization(self.plan,"APR-1")
        artifact_root=namespace_root(self.harness,self.plan.project_id,"artifact"); artifact_root.mkdir(parents=True)
        run_id="complete-resume"
        for index,item in enumerate(self.plan.lvs):
            item_run=run_id if index == 0 else f"{run_id}-{item.lv_id.lower()}"
            (artifact_root/f"{item_run}.handoff.json").write_text(json.dumps({"lv":item.lv_id,"run_id":item_run,"handoff_sha256":"1"*64}))
        def forbidden(_): self.fail("completed Gate resume invoked a lifecycle adapter")
        adapters=GateControllerAdapters(*(forbidden for _ in range(8)))
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings",return_value={"status":"VALIDATED"}), \
             patch("runtime.orchestrator.gate_orchestrator.validate_handoff"):
            result=execute_gate(self.root,"GATE-1",run_id,harness_root=self.harness,adapters=adapters,resume=True,
                approval_evidence=self.approval_path,requirements_sha256=self.req,branch="main",head=self.head,
                requirement_evidence=self.requirement_evidence("complete-noop","1"*64))
        self.assertEqual(result["status"],"GATE_EXIT")
        self.assertEqual(result["lifecycles"],[])
        self.assertTrue(result["resume_noop"])

    def test_w7_partial_resume_maps_evidence_by_stable_lv_id_and_rejects_reorder(self):
        from runtime.orchestrator.gate_orchestrator import GateLV, GatePlan, create_gate_authorization, execute_gate, namespace_root
        lvs=[GateLV("GATE-1",f"G1-LV3-{index}",index,f"work {index}",[],[f"app/{index}.py"],["pass"],"sequential",[]) for index in range(1,4)]
        plan=GatePlan("project",str(self.root),"GATE-1","PLAN.md",self.plan_sha,lvs)
        auth=create_gate_authorization(plan,"APR-1")
        artifact_root=namespace_root(self.harness,plan.project_id,"artifact"); artifact_root.mkdir(parents=True)
        prior_sha="1"*64
        (artifact_root/"partial.handoff.json").write_text(json.dumps({"lv":"G1-LV3-1","run_id":"partial","handoff_sha256":prior_sha}))
        def result(stage,status):
            def invoke(context):
                digest=hashlib.sha256(f"{context['lv_id']}:{stage}".encode()).hexdigest()
                return {"status":status,"exit_code":0,"evidence_sha256":digest,"hard_stop":True}
            return invoke
        adapters=GateControllerAdapters(result("PACKAGE","SEALED"),result("PREFLIGHT","READY"),result("WORKER","COMPLETED"),
            result("REVIEW","PASS"),result("REMEDIATION","PASS"),result("CHECKPOINT","CHECKPOINTED"),result("EXIT","EXITED"),result("HANDOFF","SEALED"))
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings",return_value={"status":"VALIDATED"}), \
             patch("runtime.orchestrator.gate_orchestrator.validate_handoff"):
            result=execute_gate(self.root,"GATE-1","partial",harness_root=self.harness,adapters=adapters,resume=True,
                approval_evidence=self.approval_path,requirements_sha256=self.req,branch="main",head=self.head,
                requirement_evidence=self.requirement_evidence("partial-evidence",prior_sha))
        ledger=json.loads((artifact_root/"partial.completeness.json").read_text())["payload"]["items"]
        plan_rows=[row for row in ledger if row["item_kind"]=="PLAN_ITEM"]
        self.assertEqual({row["item_id"] for row in plan_rows},{"G1-LV3-1","G1-LV3-2","G1-LV3-3"})
        self.assertEqual(next(row for row in plan_rows if row["item_id"]=="G1-LV3-1")["evidence_sha256"],prior_sha)
        self.assertEqual([item["lv_id"] for item in result["lifecycles"]],["G1-LV3-2","G1-LV3-3"])

    def test_w7_r01_r25_require_requirement_specific_evidence_without_fallback(self):
        from runtime.orchestrator.gate_orchestrator import create_gate_authorization, execute_gate, namespace_root
        auth=create_gate_authorization(self.plan,"APR-1")
        def fixed(status): return lambda ctx:{"status":status,"exit_code":0,"evidence_sha256":"d"*64,"hard_stop":True}
        adapters=GateControllerAdapters(fixed("SEALED"),fixed("READY"),fixed("COMPLETED"),fixed("PASS"),fixed("PASS"),fixed("CHECKPOINTED"),fixed("EXITED"),fixed("SEALED"))
        requirement_evidence=self.requirement_evidence("specific-evidence","d"*64)
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings",return_value={"status":"VALIDATED"}):
            execute_gate(self.root,"GATE-1","requirements",harness_root=self.harness,adapters=adapters,
                approval_evidence=self.approval_path,requirements_sha256=self.req,branch="main",head=self.head,
                requirement_evidence=requirement_evidence)
        ledger_path=namespace_root(self.harness,self.plan.project_id,"artifact")/"requirements.completeness.json"
        requirement_rows=[row for row in json.loads(ledger_path.read_text())["payload"]["items"] if row["item_kind"]=="REQUIREMENT"]
        self.assertEqual(len({row["evidence_sha256"] for row in requirement_rows}),25)
        self.assertTrue(all(row["evidence_sha256"]==requirement_evidence[row["item_id"]]["artifact_sha256"] for row in requirement_rows))
        self.assertTrue(all(row["evidence_sha256"]!=hashlib.sha256(row["item_id"].encode()).hexdigest() for row in requirement_rows))

    def test_w7_resumed_review_preserves_fail_remediation_pass_verdict_lineage(self):
        context={"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","run_id":"review-resume","plan_sha256":self.plan_sha,"resume":True}
        reviews=iter(("FAIL","PASS"))
        def fixed(status): return lambda ctx:{"status":status,"exit_code":0,"evidence_sha256":"d"*64,"hard_stop":True}
        adapters=GateControllerAdapters(fixed("SEALED"),fixed("READY"),fixed("COMPLETED"),
            lambda ctx:{"status":next(reviews),"exit_code":0,"evidence_sha256":"e"*64,"hard_stop":True},
            fixed("PASS"),fixed("CHECKPOINTED"),fixed("EXITED"),fixed("SEALED"))
        result=run_gate_lifecycle(context,adapters)
        self.assertEqual(result["review_verdicts"],["FAIL","PASS"])
        self.assertEqual(result["remediation_verdict"],"PASS")

    def test_w7_requirement_ledger_uses_actual_per_requirement_artifact_evidence(self):
        from runtime.orchestrator.gate_orchestrator import create_gate_authorization, execute_gate, namespace_root
        auth=create_gate_authorization(self.plan,"APR-1")
        requirement_evidence=self.requirement_evidence("requirement-evidence","d"*64)
        def fixed(status): return lambda ctx:{"status":status,"exit_code":0,"evidence_sha256":"d"*64,"hard_stop":True}
        adapters=GateControllerAdapters(fixed("SEALED"),fixed("READY"),fixed("COMPLETED"),fixed("PASS"),fixed("PASS"),fixed("CHECKPOINTED"),fixed("EXITED"),fixed("SEALED"))
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings",return_value={"status":"VALIDATED"}):
            execute_gate(self.root,"GATE-1","actual-requirements",harness_root=self.harness,adapters=adapters,
                approval_evidence=self.approval_path,requirements_sha256=self.req,branch="main",head=self.head,
                requirement_evidence=requirement_evidence)
        ledger_path=namespace_root(self.harness,self.plan.project_id,"artifact")/"actual-requirements.completeness.json"
        rows=[row for row in json.loads(ledger_path.read_text())["payload"]["items"] if row["item_kind"]=="REQUIREMENT"]
        for row in rows:
            actual=requirement_evidence[row["item_id"]]
            self.assertEqual(row["evidence_sha256"],actual["artifact_sha256"])
            self.assertEqual(row["checkpoint_ref"],actual["checkpoint_ref"])
            self.assertEqual(row["exit_ref"],actual["exit_ref"])
            self.assertEqual(row["handoff_ref"],actual["handoff_ref"])
            self.assertNotEqual(row["evidence_sha256"],hashlib.sha256(row["item_id"].encode()).hexdigest())

    def test_w7_completed_gate_resume_reuses_existing_immutable_ledger(self):
        from runtime.orchestrator.gate_orchestrator import create_gate_authorization, execute_gate, namespace_root
        auth=create_gate_authorization(self.plan,"APR-1")
        def fixed(status): return lambda ctx:{"status":status,"exit_code":0,"evidence_sha256":"d"*64,"hard_stop":True}
        adapters=GateControllerAdapters(fixed("SEALED"),fixed("READY"),fixed("COMPLETED"),fixed("PASS"),fixed("PASS"),fixed("CHECKPOINTED"),fixed("EXITED"),fixed("SEALED"))
        requirement_evidence=self.requirement_evidence("idempotent-evidence","d"*64)
        patches=(
            patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan),
            patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth),
            patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings",return_value={"status":"VALIDATED"}),
        )
        with patches[0],patches[1],patches[2]:
            first=execute_gate(self.root,"GATE-1","idempotent",harness_root=self.harness,adapters=adapters,
                approval_evidence=self.approval_path,requirements_sha256=self.req,branch="main",head=self.head,
                requirement_evidence=requirement_evidence)
        artifact_root=namespace_root(self.harness,self.plan.project_id,"artifact")
        ledger_path=artifact_root/"idempotent.completeness.json"; original=ledger_path.read_bytes()
        (artifact_root/"idempotent.handoff.json").write_text(json.dumps({"lv":"G1-LV3-1","run_id":"idempotent","handoff_sha256":"1"*64}))
        with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan",return_value=self.plan), \
             patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization",return_value=auth), \
             patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings",return_value={"status":"VALIDATED"}), \
             patch("runtime.orchestrator.gate_orchestrator.validate_handoff"):
            resumed=execute_gate(self.root,"GATE-1","idempotent",harness_root=self.harness,adapters=adapters,resume=True,
                approval_evidence=self.approval_path,requirements_sha256=self.req,branch="main",head=self.head)
        self.assertEqual(first["ledger_sha256"],resumed["ledger_sha256"])
        self.assertTrue(resumed["resume_noop"])
        self.assertEqual(ledger_path.read_bytes(),original)

    def test_w7_each_requirement_has_independent_semantic_metadata_and_sha(self):
        bindings = [seal_requirement_semantic_metadata(requirement_id=requirement_id,
            semantic_metadata={"requirement_id": requirement_id, "meaning": f"canonical-{requirement_id}"},
            canonical_plan_sha256=self.plan_sha, project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1")
            for requirement_id in REQUIREMENT_IDS]
        self.assertEqual(len({item["semantic_sha256"] for item in bindings}), 25)
        for item in bindings:
            validate_requirement_semantic_binding(item, requirement_id=item["requirement_id"],
                project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1", canonical_plan_sha256=self.plan_sha)

    def test_w7_requirement_semantic_metadata_tamper_is_hard_stop(self):
        item = seal_requirement_semantic_metadata(requirement_id="R01",
            semantic_metadata={"requirement_id":"R01", "meaning":"canonical-R01"},
            canonical_plan_sha256=self.plan_sha, project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1")
        item["semantic_metadata"]["meaning"] = "tampered"
        with self.assertRaisesRegex(GateOrchestrationError, "semantic metadata SHA drift"):
            validate_requirement_semantic_binding(item, requirement_id="R01", project_id="project",
                gate_id="GATE-1", lv_id="G1-LV3-1", canonical_plan_sha256=self.plan_sha)

    def test_w7_requirement_id_missing_duplicate_unknown_is_hard_stop(self):
        with self.assertRaisesRegex(GateOrchestrationError, "unknown requirement ID"):
            seal_requirement_semantic_metadata(requirement_id="R26", semantic_metadata={"requirement_id":"R26"},
                canonical_plan_sha256=self.plan_sha, project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1")

    def test_w7_implementation_and_test_evidence_bind_to_scope_and_content_sha(self):
        def evidence(kind):
            value={"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","requirement_id":"R01",
                "canonical_plan_sha256":self.plan_sha,"evidence_type":kind,"producer":"fixture",
                "content":{"result":"PASS"},"lifecycle_attempt":1}
            value["artifact_sha256"]=hashlib.sha256(__import__("runtime.orchestrator.lv_execution_package",fromlist=["canonical_json_bytes"]).canonical_json_bytes(value)).hexdigest()
            return value
        for kind in ("implementation", "test"):
            validate_evidence_binding(evidence(kind), requirement_id="R01", project_id="project", gate_id="GATE-1",
                lv_id="G1-LV3-1", canonical_plan_sha256=self.plan_sha, lifecycle_attempt=1)

    def test_w7_evidence_tamper_cross_scope_and_stale_attempt_are_hard_stop(self):
        value={"project_id":"project","gate_id":"GATE-1","lv_id":"G1-LV3-1","requirement_id":"R01",
            "canonical_plan_sha256":self.plan_sha,"evidence_type":"test","producer":"fixture",
            "content":{"result":"PASS"},"lifecycle_attempt":1}
        from runtime.orchestrator.lv_execution_package import canonical_json_bytes
        value["artifact_sha256"]=hashlib.sha256(canonical_json_bytes(value)).hexdigest()
        value["content"]["result"]="tampered"
        with self.assertRaisesRegex(GateOrchestrationError,"evidence SHA mismatch"):
            validate_evidence_binding(value, requirement_id="R01", project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1", canonical_plan_sha256=self.plan_sha, lifecycle_attempt=1)
        value["content"]["result"]="PASS"; value["artifact_sha256"]=hashlib.sha256(canonical_json_bytes({k:v for k,v in value.items() if k!="artifact_sha256"})).hexdigest(); value["lv_id"]="G1-LV3-2"
        with self.assertRaisesRegex(GateOrchestrationError,"scope binding mismatch"):
            validate_evidence_binding(value, requirement_id="R01", project_id="project", gate_id="GATE-1", lv_id="G1-LV3-1", canonical_plan_sha256=self.plan_sha, lifecycle_attempt=1)


if __name__ == "__main__": unittest.main()
