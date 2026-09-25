from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.ai_office.full_plan_activation import AIFullPlanActivationContextV1
from runtime.orchestrator.approved_full_plan_activation_contract import GateBindingRefV1
from runtime.orchestrator.approved_full_plan_binding import ExecutableAuthorityBundleV1, ValidatedGateAuthorityV1
from runtime.orchestrator.full_plan_activation import build_executable_full_plan_job
from runtime.orchestrator.production_full_plan_entry import build_gate_executor, load_job, preflight_job


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FullPlanPrefixActivationBridgeTests(unittest.TestCase):
    def test_gate_contract_remains_backward_compatible_without_prefix(self):
        gate = GateBindingRefV1.from_mapping({
            "gate_id": "GATE-10",
            "approval_evidence": {"path": "approval.json", "sha256": "a" * 64},
            "engine_requirement_evidence": {"path": "engine.json", "sha256": "b" * 64},
            "project_requirement_evidence_by_lv": [],
        })
        self.assertIsNone(gate.adopted_prefix_evidence)
        self.assertNotIn("adopted_prefix_evidence", gate.to_dict())

    def test_gate_contract_accepts_optional_prefix_artifact(self):
        gate = GateBindingRefV1.from_mapping({
            "gate_id": "GATE-10",
            "approval_evidence": {"path": "approval.json", "sha256": "a" * 64},
            "engine_requirement_evidence": {"path": "engine.json", "sha256": "b" * 64},
            "project_requirement_evidence_by_lv": [],
            "adopted_prefix_evidence": {"path": "sft-task-1-9-prefix.json", "sha256": "c" * 64},
        })
        self.assertEqual(gate.adopted_prefix_evidence.path, "sft-task-1-9-prefix.json")
        self.assertEqual(gate.to_dict()["adopted_prefix_evidence"]["sha256"], "c" * 64)

    def test_job_builder_binds_prefix_path_and_digest_without_readding_prior_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            project = base / "project"; project.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=project, check=True)
            (project / "plan.md").write_text("plan\n", encoding="utf-8")
            (project / "spec.md").write_text("spec\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=project, check=True)
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
            state = base / "state"; state.mkdir()
            prefix = base / "prefix.json"; prefix.write_text('{"sealed":true}\n', encoding="utf-8")
            requirement = base / "task10.json"; requirement.write_text('{"schema_version":"orchestration.project-requirement-contract.v1","requirements":{}}\n', encoding="utf-8")
            approval = base / "approval.json"; approval.write_text("{}\n", encoding="utf-8")
            engine = base / "engine.json"; engine.write_text("{}\n", encoding="utf-8")
            runtime = base / "runtime"; (runtime / "runtime/orchestrator").mkdir(parents=True)
            (runtime / "runtime/orchestrator/production_full_plan_boot.py").write_text("# boot\n", encoding="utf-8")
            gate = ValidatedGateAuthorityV1(
                gate_id="GATE-10", approval_evidence_path=str(approval), approval_evidence_sha256=sha(approval),
                requirements_sha256="1" * 64, engine_requirement_evidence_path=str(engine), engine_requirement_evidence_sha256=sha(engine),
                project_requirement_evidence_paths_by_lv=(("TASK-010", str(requirement), sha(requirement)),),
                lv_order=("TASK-001","TASK-002","TASK-003","TASK-004","TASK-005","TASK-006","TASK-007","TASK-008","TASK-009","TASK-010"),
                adopted_prefix_evidence_path=str(prefix), adopted_prefix_evidence_sha256=sha(prefix),
            )
            bundle = ExecutableAuthorityBundleV1(
                schema_version="orchestration.executable-authority-bundle.v1", activation_request_id="SFT-TASK10-ACT",
                request_digest="2" * 64, project_alias="system-financial-trading-office", project_id="project",
                project_root=str(project), authority_root=str(base / "authority"), mapping_root=str(base / "mappings"),
                approved_plan_path="plan.md", approved_plan_sha256=sha(project / "plan.md"),
                approved_spec_path="spec.md", approved_spec_sha256=sha(project / "spec.md"), approval_ref="USER-SFT-TASK10",
                expected_branch="main", expected_head=head, runtime_release_digest="3" * 64,
                runtime_release_source_head="4" * 40, runtime_code_root=str(runtime), gates=(gate,),
            )
            context = AIFullPlanActivationContextV1(
                schema_version="ai-office.full-plan-activation-context.v1", activation_request_id="SFT-TASK10-ACT",
                project_id="project", office_run_id="SFT-TASK10-ACT", requirement_id="approved-full-plan:SFT-TASK10-ACT",
                requirement_envelope_digest="5" * 64, approved_plan_digest=bundle.approved_plan_sha256,
                approved_spec_digest=bundle.approved_spec_sha256, approval_ref=bundle.approval_ref,
                expected_head=head, executable_authority_bundle_digest=bundle.bundle_digest,
                gate_ids=("GATE-10",), workflow_state="INTAKE_READY", workflow_revision=1, workflow_state_digest="6" * 64,
            )
            job = build_executable_full_plan_job(bundle, ai_context=context, harness_state_root=state)
            gate_job = job["gates"][0]
            self.assertEqual(gate_job["adopted_prefix_evidence_path"], str(prefix))
            self.assertEqual(gate_job["adopted_prefix_evidence_sha256"], sha(prefix))
            self.assertEqual(set(gate_job["requirement_evidence_paths_by_lv"]), {"TASK-010"})

    def test_preflight_blocks_prefix_evidence_drift_and_executor_passes_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            prefix = root / "prefix.json"; prefix.write_text('{"sealed":true}\n', encoding="utf-8")
            approval = root / "approval.json"; approval.write_text("{}\n", encoding="utf-8")
            payload = {
                "schema_version": "orchestration.production-full-plan-job.v1",
                "project_root": str(root), "harness_root": str(root), "project_id": "proj", "run_id": "run",
                "git_common_dir": str((root / ".git").resolve()), "required_executables": ["git"],
                "gates": [{
                    "gate_id": "GATE-10", "approval_evidence": str(approval), "requirements_sha256": "a" * 64,
                    "branch": "main", "head": "b" * 40, "full_plan_opt_in": True, "project_final_validation": True,
                    "adopted_prefix_evidence_path": str(prefix), "adopted_prefix_evidence_sha256": sha(prefix),
                }],
            }
            path = root / "job.json"; path.write_text(json.dumps(payload), encoding="utf-8")
            job = load_job(path)
            executor = build_gate_executor(job)
            with patch("runtime.orchestrator.gate_orchestrator.execute_gate", return_value={"status": "GATE_EXIT"}) as call:
                executor("GATE-10", "run--gate-10", False)
            self.assertEqual(call.call_args.kwargs["adopted_prefix_evidence"], {"sealed": True})
            prefix.write_text('{"sealed":false}\n', encoding="utf-8")
            self.assertIn("PREFIX_ADOPTION_EVIDENCE_DRIFT", preflight_job(job)["reason"])


if __name__ == "__main__":
    unittest.main()
