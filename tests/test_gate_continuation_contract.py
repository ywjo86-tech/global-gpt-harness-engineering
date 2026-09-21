from __future__ import annotations

import json
import inspect
import subprocess
import tempfile
import unittest
from pathlib import Path

EXPECTED = {
    "schema_version","gate_id","continuation_policy","approved_base_head",
    "source_lineage_policy","allowed_write_paths","forbidden_paths",
    "required_verifiers","required_evidence_classes","commit_policy",
    "risk_classes","approval_coverage_ref","approval_coverage_digest",
    "external_effect_policy","runtime_migration_policy",
}


def mapping(gate_id: str, head: str = "a" * 40) -> dict:
    return {
        "schema_version":"orchestration.gate-continuation-contract.v1",
        "gate_id":gate_id,"continuation_policy":"AUTO_WITHIN_APPROVED_CONTRACT",
        "approved_base_head":head,"source_lineage_policy":"APPROVED_DESCENDANT_CHAIN",
        "allowed_write_paths":["runtime/","tests/"],"forbidden_paths":[".git/","secrets/"],
        "required_verifiers":["UNITTEST","TREE_SCOPE"],"required_evidence_classes":["TEST_RESULT","GIT_TREE"],
        "commit_policy":"LOCAL_COMMIT_ALLOWED","risk_classes":["REPOSITORY_LOCAL"],
        "approval_coverage_ref":"user:approved","approval_coverage_digest":"b"*64,
        "external_effect_policy":"NO_EXTERNAL_EFFECT","runtime_migration_policy":"NO_RUNTIME_MIGRATION",
    }


class GateContinuationContractTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.gate_continuation_contract import GateContinuationContract, continuation_policy_for_gate
        except ModuleNotFoundError as exc:
            self.fail(f"GateContinuationContract module missing: {exc}")
        return GateContinuationContract, continuation_policy_for_gate

    def make_repo(self, root: Path):
        subprocess.run(["git","init","-q",str(root)],check=True)
        subprocess.run(["git","-C",str(root),"config","user.email","t@example.com"],check=True)
        subprocess.run(["git","-C",str(root),"config","user.name","T"],check=True)
        spec=root/"spec.md"; plan=root/"plan.md"; spec.write_text("spec\n"); plan.write_text("plan\n")
        subprocess.run(["git","-C",str(root),"add","spec.md","plan.md"],check=True)
        subprocess.run(["git","-C",str(root),"commit","-qm","base"],check=True)
        head=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
        return spec,plan,head

    def test_wire_schema_has_exact_approved_fields(self):
        Contract,_ = self.api(); contract=Contract.from_mapping(mapping("TASK-001"))
        self.assertEqual(set(contract.canonical_projection()), EXPECTED)
        self.assertEqual(contract.continuation_policy, "AUTO_WITHIN_APPROVED_CONTRACT")

    def test_unknown_enum_and_gate_mismatch_fail_closed(self):
        Contract,_ = self.api(); bad=mapping("TASK-001"); bad["commit_policy"]="PUSH_ALLOWED"
        with self.assertRaisesRegex(ValueError,"commit_policy"):
            Contract.from_mapping(bad)
        good=Contract.from_mapping(mapping("TASK-002"))
        with self.assertRaisesRegex(ValueError,"gate_id"):
            good.require_gate("TASK-001")

    def test_omitted_gate_defaults_to_manual_operator(self):
        _,policy=self.api()
        self.assertEqual(policy({"gate_id":"TASK-001"}), "MANUAL_OPERATOR")

    def test_builder_rejects_unknown_gate_mapping_and_seals_known_contract(self):
        from runtime.orchestrator.operator_plan_execution import build_operator_plan_job, OperatorPlanExecutionError
        self.assertIn("continuation_contracts_by_gate", inspect.signature(build_operator_plan_job).parameters)
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); project=base/"project"; project.mkdir(); spec,plan,head=self.make_repo(project)
            runtime=base/"runtime"; (runtime/"runtime").mkdir(parents=True); state=base/"state"; state.mkdir()
            with self.assertRaisesRegex(OperatorPlanExecutionError,"unknown Gate"):
                build_operator_plan_job(project_root=project,harness_state_root=state,runtime_code_root=runtime,
                    project_id="P",run_id="R",task_ids=("TASK-001",),approved_plan_path=plan,approved_spec_path=spec,
                    approval_ref="approved",continuation_contracts_by_gate={"TASK-999":mapping("TASK-999",head)})
            job=build_operator_plan_job(project_root=project,harness_state_root=state,runtime_code_root=runtime,
                project_id="P",run_id="R2",task_ids=("TASK-001","TASK-002"),approved_plan_path=plan,approved_spec_path=spec,
                approval_ref="approved",continuation_contracts_by_gate={"TASK-001":mapping("TASK-001",head)})
            self.assertEqual(job["gates"][0]["continuation_contract"]["gate_id"],"TASK-001")
            self.assertNotIn("continuation_contract",job["gates"][1])

    def test_continuation_contract_is_authority_core_bound(self):
        from runtime.orchestrator.operator_plan_execution import build_operator_plan_job
        self.assertIn("continuation_contracts_by_gate", inspect.signature(build_operator_plan_job).parameters)
        from runtime.orchestrator.production_run_authority import seal_authority_core, validate_authority_core, RunAuthorityError
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); project=base/"project"; project.mkdir(); spec,plan,head=self.make_repo(project)
            runtime=base/"runtime"; (runtime/"runtime").mkdir(parents=True); state=base/"state"; state.mkdir()
            job=build_operator_plan_job(project_root=project,harness_state_root=state,runtime_code_root=runtime,
                project_id="P",run_id="R",task_ids=("TASK-001",),approved_plan_path=plan,approved_spec_path=spec,
                approval_ref="approved",continuation_contracts_by_gate={"TASK-001":mapping("TASK-001",head)})
            sealed=seal_authority_core(job); validate_authority_core(sealed)
            sealed["gates"][0]["continuation_contract"]["allowed_write_paths"].append("outside/")
            with self.assertRaisesRegex(RunAuthorityError,"RUN_AUTHORITY_DRIFT"):
                validate_authority_core(sealed)


if __name__ == "__main__": unittest.main()
