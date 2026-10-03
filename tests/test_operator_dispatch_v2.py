import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.durable_continuation import AUTO
from runtime.orchestrator.execution_lifecycle_v2 import build_v2_operator_plan_job
from runtime.orchestrator.operator_dispatch_v2 import (
    DispatchReceiptBindingStore,
    OperatorDispatchError,
    OperatorDispatchStore,
    build_v2_operator_plan_executor,
    ensure_v2_dispatch,
    evaluate_v2_auto_continuation,
    seal_v2_dispatch_receipt,
)
from runtime.orchestrator.operator_plan_execution import (
    OperatorPlanReceiptStore,
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

    def receipt_store(self, root: Path, job: dict) -> OperatorPlanReceiptStore:
        return OperatorPlanReceiptStore(root, project_id=job["project_id"], run_id=job["run_id"])

    def create_receipt(self, root: Path, job: dict, gate_id: str = "TASK-001") -> dict:
        gate = next(item for item in job["gates"] if item["gate_id"] == gate_id)
        return self.receipt_store(root, job).create_pass_receipt(
            gate_id=gate_id,
            plan_sha256=job["approved_plan_sha256"],
            spec_sha256=job["approved_spec_sha256"],
            branch=job["expected_branch"],
            source_head=gate["head"],
            tests=("tests.test_operator_dispatch_v2",),
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

    def test_v2_receipt_without_acknowledged_dispatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.build_v2_job(root)
            receipts = self.receipt_store(root, job)
            self.create_receipt(root, job)
            dispatches = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            with self.assertRaises(OperatorDispatchError):
                seal_v2_dispatch_receipt(
                    job,
                    "TASK-001",
                    dispatch_store=dispatches,
                    receipt_store=receipts,
                )

    def test_acknowledged_dispatch_and_receipt_seal_dcc_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.build_v2_job(root)
            dispatches = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            receipts = self.receipt_store(root, job)
            bindings = DispatchReceiptBindingStore(root, project_id=job["project_id"], run_id=job["run_id"])
            ensure_v2_dispatch(job, "TASK-001", dispatch_store=dispatches)
            dispatches.acknowledge("TASK-001")
            receipt = self.create_receipt(root, job)

            sealed = seal_v2_dispatch_receipt(
                job,
                "TASK-001",
                dispatch_store=dispatches,
                receipt_store=receipts,
                binding_store=bindings,
            )
            self.assertEqual(sealed["dispatch_id"], dispatches.load("TASK-001")["dispatch_id"])
            self.assertEqual(sealed["receipt_sha256"], receipt["receipt_sha256"])
            self.assertEqual(sealed["state"], "RECEIPT_SEALED")

            state = {
                "state": "WAITING_RESOURCE",
                "last_error": "OPERATOR_TASK_RECEIPT_PENDING",
            }
            eligibility = evaluate_v2_auto_continuation(
                job,
                "TASK-001",
                state,
                continuation_policy=AUTO,
                contract_valid=True,
                attestation_valid=True,
                owner_epoch_current=True,
                dispatch_store=dispatches,
                receipt_store=receipts,
                binding_store=bindings,
            )
            self.assertTrue(eligibility.eligible)
            self.assertEqual(eligibility.reason, "AUTO_CONTINUATION_ELIGIBLE")

            execute = build_v2_operator_plan_executor(
                job,
                receipt_store=receipts,
                dispatch_store=dispatches,
                binding_store=bindings,
            )
            result = execute("TASK-001", "gate-run-1", True)
            self.assertEqual(result["status"], "GATE_EXIT")
            self.assertEqual(result["dispatch_receipt_binding_sha256"], sealed["binding_sha256"])

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
