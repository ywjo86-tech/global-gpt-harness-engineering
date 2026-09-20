import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operator_plan_execution import (
    EXECUTOR_KIND,
    OperatorPlanExecutionError,
    OperatorPlanReceiptStore,
    build_operator_plan_executor,
    build_operator_plan_job,
    validate_operator_plan_job,
)
from runtime.orchestrator.production_full_plan_entry import (
    build_gate_executor, load_job, load_registered_job, preflight_job, register_job,
    transient_systemd_command,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


class OperatorPlanExecutionTests(unittest.TestCase):
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

    def build_job(self, root: Path, spec: Path, plan: Path) -> dict:
        return build_operator_plan_job(
            project_root=root, harness_root=root, runtime_code_root=root,
            project_id="proj", run_id="run-final-op",
            task_ids=("TASK-001", "TASK-002"), approved_plan_path=plan,
            approved_spec_path=spec, approval_ref="chat://2026-09-20/spec-approved",
        )

    def test_build_job_binds_approved_plan_spec_branch_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = self.build_job(root, spec, plan)
            self.assertEqual(job["executor_kind"], EXECUTOR_KIND)
            self.assertEqual(job["approved_plan_sha256"], sha(plan))
            self.assertEqual(job["approved_spec_sha256"], sha(spec))
            self.assertEqual(job["expected_branch"], git(root, "branch", "--show-current"))
            self.assertEqual([g["gate_id"] for g in job["gates"]], ["TASK-001", "TASK-002"])
            path = root / "job.json"
            path.write_text(json.dumps(job), encoding="utf-8")
            loaded = load_job(path)
            self.assertEqual(loaded["executor_kind"], EXECUTOR_KIND)

    def test_validation_rejects_plan_digest_drift_and_unsafe_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = self.build_job(root, spec, plan)
            plan.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(OperatorPlanExecutionError, "plan digest"):
                validate_operator_plan_job(job)
            plan.write_text("# Approved plan\n", encoding="utf-8")
            link = root / "spec-link.md"
            link.symlink_to(spec)
            job["approved_spec_path"] = str(link)
            with self.assertRaisesRegex(OperatorPlanExecutionError, "regular committed file"):
                validate_operator_plan_job(job)


    def test_load_job_revalidates_operator_plan_digests(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = self.build_job(root, spec, plan)
            path = root / "job.json"
            job["approved_plan_sha256"] = "f" * 64
            path.write_text(json.dumps(job), encoding="utf-8")
            with self.assertRaisesRegex(OperatorPlanExecutionError, "plan digest"):
                load_job(path)

    def test_production_entry_uses_operator_executor_for_operator_job(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = self.build_job(root, spec, plan)
            out = build_gate_executor(job)("TASK-001", "run--task-001", False)
            self.assertEqual(out["status"], "WAITING_RESOURCE")
            self.assertEqual(out["reason"], "OPERATOR_TASK_RECEIPT_PENDING")

    def test_preflight_and_transient_launch_use_immutable_runtime_code_root(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            root = base / "project"
            root.mkdir()
            spec, plan = self.make_repo(root)
            runtime = base / "release"
            (runtime / "runtime/orchestrator").mkdir(parents=True)
            (runtime / "runtime/orchestrator/production_full_plan_entry.py").write_text("# frozen\n")
            job = build_operator_plan_job(
                project_root=root, harness_root=root, runtime_code_root=runtime,
                project_id="proj", run_id="run-release", task_ids=("TASK-001",),
                approved_plan_path=plan, approved_spec_path=spec, approval_ref="chat://approved",
            )
            requested = root / "job.json"
            requested.write_text(json.dumps(job), encoding="utf-8")
            canonical = register_job(load_job(requested))
            registered = load_registered_job(canonical)
            self.assertEqual(preflight_job(registered)["status"], "PASS")
            command = transient_systemd_command(canonical)
            self.assertIn(f"--working-directory={runtime.resolve()}", command)

    def test_receipt_is_create_once_and_executor_only_observes_it(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = self.build_job(root, spec, plan)
            store = OperatorPlanReceiptStore(root, project_id="proj", run_id="run-final-op")
            executor = build_operator_plan_executor(job, receipt_store=store)
            pending = executor("TASK-001", "run-final-op--task-001", False)
            self.assertEqual(pending["status"], "WAITING_RESOURCE")
            self.assertEqual(pending["reason"], "OPERATOR_TASK_RECEIPT_PENDING")
            receipt = store.create_pass_receipt(
                gate_id="TASK-001", plan_sha256=job["approved_plan_sha256"],
                spec_sha256=job["approved_spec_sha256"], branch=job["expected_branch"],
                source_head=git(root, "rev-parse", "HEAD"), tests=("unit:PASS",),
            )
            completed = executor("TASK-001", "run-final-op--task-001", True)
            self.assertEqual(completed["status"], "GATE_EXIT")
            self.assertEqual(completed["receipt_sha256"], receipt["receipt_sha256"])
            same = store.create_pass_receipt(
                gate_id="TASK-001", plan_sha256=job["approved_plan_sha256"],
                spec_sha256=job["approved_spec_sha256"], branch=job["expected_branch"],
                source_head=git(root, "rev-parse", "HEAD"), tests=("unit:PASS",),
            )
            self.assertEqual(same["receipt_sha256"], receipt["receipt_sha256"])

    def test_conflicting_receipt_and_duplicate_task_ids_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = self.build_job(root, spec, plan)
            store = OperatorPlanReceiptStore(root, project_id="proj", run_id="run-final-op")
            store.create_pass_receipt(
                gate_id="TASK-001", plan_sha256=job["approved_plan_sha256"],
                spec_sha256=job["approved_spec_sha256"], branch=job["expected_branch"],
                source_head=git(root, "rev-parse", "HEAD"), tests=("unit:PASS",),
            )
            with self.assertRaisesRegex(OperatorPlanExecutionError, "conflicting receipt"):
                store.create_pass_receipt(
                    gate_id="TASK-001", plan_sha256=job["approved_plan_sha256"],
                    spec_sha256=job["approved_spec_sha256"], branch=job["expected_branch"],
                    source_head="f" * 40, tests=("unit:PASS",),
                )
            with self.assertRaisesRegex(OperatorPlanExecutionError, "duplicated"):
                build_operator_plan_job(
                    project_root=root, harness_root=root, runtime_code_root=root,
                    project_id="proj", run_id="run-dup", task_ids=("TASK-001", "TASK-001"),
                    approved_plan_path=plan, approved_spec_path=spec,
                    approval_ref="chat://2026-09-20/spec-approved",
                )


if __name__ == "__main__":
    unittest.main()
