import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operator_plan_execution import build_operator_plan_job


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

    def build_job(self, root: Path, *, lifecycle_mode=None) -> dict:
        spec, plan = self.make_repo(root)
        kwargs = {}
        if lifecycle_mode is not None:
            kwargs["lifecycle_mode"] = lifecycle_mode
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
            **kwargs,
        )

    def test_legacy_job_shape_is_unchanged_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            job = self.build_job(Path(d))
            self.assertNotIn("execution_lifecycle", job)

    def test_v2_compat_materializes_gate_authority_bundles_from_existing_authority(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            job = self.build_job(Path(d), lifecycle_mode="V2_COMPAT")
            lifecycle = job["execution_lifecycle"]
            self.assertEqual(lifecycle["schema_version"], "orchestration.execution-lifecycle.v2")
            self.assertEqual(lifecycle["mode"], "V2_COMPAT")
            self.assertTrue(lifecycle["legacy_compatible"])
            self.assertEqual(set(lifecycle["authority_bundles"]), {"TASK-001", "TASK-002"})

            for gate_id, bundle in lifecycle["authority_bundles"].items():
                self.assertEqual(bundle["schema_version"], "orchestration.execution-authority-bundle.v1")
                self.assertEqual(bundle["gate_id"], gate_id)
                self.assertEqual(bundle["approved_plan_sha256"], job["approved_plan_sha256"])
                self.assertEqual(bundle["approved_spec_sha256"], job["approved_spec_sha256"])
                self.assertEqual(bundle["approval_ref"], job["approval_ref"])
                self.assertEqual(bundle["expected_branch"], job["expected_branch"])
                self.assertEqual(bundle["source_head"], job["gates"][0]["head"])
                self.assertRegex(bundle["bundle_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotIn("final_assignee", bundle)
                self.assertNotIn("provider_ref", bundle)
                self.assertNotIn("model_ref", bundle)


if __name__ == "__main__":
    unittest.main()
