import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.execution_lifecycle_v2 import (
    build_v2_operator_plan_job,
    resolve_lifecycle_binding,
    validate_execution_authority_bundle,
)
from runtime.orchestrator.operator_plan_execution import build_operator_plan_job


RUNTIME_RELEASE_DIGEST = "a" * 64


class HarnessLifecycleV2CompatTests(unittest.TestCase):
    def make_repo(self, root: Path) -> tuple[Path, Path]:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        spec = root / "spec.md"
        plan = root / "plan.md"
        spec.write_text("# Approved spec\n", encoding="utf-8")
        plan.write_text("# Approved plan\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "spec.md", "plan.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)
        return spec, plan

    def build_legacy_job(self, root: Path) -> dict:
        spec, plan = self.make_repo(root)
        return build_operator_plan_job(
            project_root=root,
            harness_root=root,
            runtime_code_root=root,
            project_id="compat-proj",
            run_id="compat-run",
            task_ids=("TASK-001", "TASK-002"),
            approved_plan_path=plan,
            approved_spec_path=spec,
            approval_ref="USER-APPROVED-COMPAT",
        )

    def test_missing_lifecycle_binding_resolves_to_legacy_without_rewriting_job(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            job = self.build_legacy_job(Path(d))
            self.assertNotIn("lifecycle_binding", job)
            self.assertNotIn("execution_authority_bundle", job)
            resolved = resolve_lifecycle_binding(job)
            self.assertEqual(resolved["schema_version"], "orchestration.lifecycle-binding.v1")
            self.assertEqual(resolved["lifecycle_mode"], "LEGACY")
            self.assertFalse(resolved["bound_at_activation"])
            self.assertFalse(resolved["migration_allowed"])

    def test_v2_job_materializes_one_immutable_authority_bundle_from_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = build_v2_operator_plan_job(
                project_root=root,
                harness_root=root,
                runtime_code_root=root,
                project_id="compat-proj",
                run_id="compat-v2-run",
                task_ids=("TASK-001", "TASK-002"),
                approved_plan_path=plan,
                approved_spec_path=spec,
                approval_ref="USER-APPROVED-COMPAT",
                runtime_release_digest=RUNTIME_RELEASE_DIGEST,
            )

            binding = job["lifecycle_binding"]
            self.assertEqual(binding, {
                "schema_version": "orchestration.lifecycle-binding.v1",
                "lifecycle_mode": "V2",
                "bound_at_activation": True,
                "migration_allowed": False,
                "runtime_release_digest": RUNTIME_RELEASE_DIGEST,
            })

            bundle = job["execution_authority_bundle"]
            self.assertEqual(bundle["schema_version"], "orchestration.execution-authority-bundle.v1")
            self.assertEqual(bundle["project_id"], job["project_id"])
            self.assertEqual(bundle["run_id"], job["run_id"])
            self.assertEqual(bundle["approved_plan_sha256"], job["approved_plan_sha256"])
            self.assertEqual(bundle["approved_spec_sha256"], job["approved_spec_sha256"])
            self.assertEqual(bundle["approval_ref"], job["approval_ref"])
            self.assertEqual(bundle["expected_branch"], job["expected_branch"])
            self.assertEqual(bundle["activation_source_head"], job["gates"][0]["head"])
            self.assertEqual(bundle["runtime_release_digest"], RUNTIME_RELEASE_DIGEST)
            self.assertEqual(bundle["lifecycle_mode"], "V2")
            self.assertEqual([item["gate_id"] for item in bundle["gate_authorities"]], ["TASK-001", "TASK-002"])
            self.assertTrue(all(item["authority_kind"] == "FULL_PLAN_GATE" for item in bundle["gate_authorities"]))
            self.assertRegex(bundle["bundle_sha256"], r"^[0-9a-f]{64}$")
            validate_execution_authority_bundle(job)

            forbidden = {"final_assignee", "provider_ref", "model_ref", "completion_authority", "effect_authority"}
            self.assertTrue(forbidden.isdisjoint(bundle))
            for authority in bundle["gate_authorities"]:
                self.assertTrue(forbidden.isdisjoint(authority))


if __name__ == "__main__":
    unittest.main()
