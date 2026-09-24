import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.execution_lifecycle_v2 import build_v2_operator_plan_job
from runtime.orchestrator.operator_dispatch_v2 import (
    OperatorDispatchError,
    OperatorDispatchStore,
    build_v2_operator_plan_executor,
    ensure_v2_dispatch,
)
from runtime.orchestrator.operator_plan_execution import (
    build_operator_plan_executor,
    build_operator_plan_job,
)


RUNTIME_RELEASE_DIGEST = "a" * 64


class OperatorDispatchV2Tests(unittest.TestCase):
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

    def build_v2_job(self, root: Path) -> dict:
        spec, plan = self.make_repo(root)
        return build_v2_operator_plan_job(
            project_root=root,
            harness_root=root,
            runtime_code_root=root,
            project_id="dispatch-proj",
            run_id="dispatch-run",
            task_ids=("TASK-001", "TASK-002"),
            approved_plan_path=plan,
            approved_spec_path=spec,
            approval_ref="USER-APPROVED-DISPATCH",
            runtime_release_digest=RUNTIME_RELEASE_DIGEST,
        )

    def test_dispatch_is_create_once_idempotent_and_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.build_v2_job(root)
            store = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])

            prepared = store.prepare(job, "TASK-001")
            self.assertEqual(prepared["state"], "DISPATCH_PREPARED")
            replay = store.prepare(job, "TASK-001")
            self.assertEqual(replay["dispatch_id"], prepared["dispatch_id"])
            self.assertEqual(replay["record_sha256"], prepared["record_sha256"])

            dispatched = store.mark_dispatched("TASK-001")
            self.assertEqual(dispatched["state"], "OPERATOR_DISPATCHED")
            restarted_store = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            restarted = ensure_v2_dispatch(job, "TASK-001", dispatch_store=restarted_store)
            self.assertEqual(restarted["dispatch_id"], prepared["dispatch_id"])
            self.assertEqual(restarted["state"], "OPERATOR_DISPATCHED")

    def test_conflicting_dispatch_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.build_v2_job(root)
            store = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            store.prepare(job, "TASK-001")
            changed = dict(job)
            changed["execution_authority_bundle"] = dict(job["execution_authority_bundle"])
            changed["execution_authority_bundle"]["bundle_sha256"] = "0" * 64
            with self.assertRaises(OperatorDispatchError):
                store.prepare(changed, "TASK-001")

    def test_v2_executor_waits_for_dispatch_ack_before_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.build_v2_job(root)
            execute = build_v2_operator_plan_executor(job)

            first = execute("TASK-001", "gate-run-1", False)
            self.assertEqual(first, {
                "status": "WAITING_RESOURCE",
                "reason": "OPERATOR_DISPATCH_ACK_PENDING",
            })

            store = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            dispatch = store.load("TASK-001")
            self.assertIsNotNone(dispatch)
            self.assertEqual(dispatch["state"], "OPERATOR_DISPATCHED")
            store.acknowledge("TASK-001")

            second = execute("TASK-001", "gate-run-1", True)
            self.assertEqual(second, {
                "status": "WAITING_RESOURCE",
                "reason": "OPERATOR_TASK_RECEIPT_PENDING",
            })

    def test_legacy_executor_behavior_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = build_operator_plan_job(
                project_root=root,
                harness_root=root,
                runtime_code_root=root,
                project_id="legacy-proj",
                run_id="legacy-run",
                task_ids=("TASK-001",),
                approved_plan_path=plan,
                approved_spec_path=spec,
                approval_ref="USER-APPROVED-LEGACY",
            )
            execute = build_operator_plan_executor(job)
            self.assertEqual(execute("TASK-001", "gate-run-1", False), {
                "status": "WAITING_RESOURCE",
                "reason": "OPERATOR_TASK_RECEIPT_PENDING",
            })
            self.assertFalse((root / "_workspace" / "operator-dispatch-v2").exists())


if __name__ == "__main__":
    unittest.main()
