import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.durable_continuation import AUTO
from runtime.orchestrator.execution_lifecycle_v2 import (
    build_v2_operator_plan_job,
    resolve_lifecycle_binding,
)
from runtime.orchestrator.lifecycle_v2_continuation import resume_v2_after_bound_receipt
from runtime.orchestrator.lifecycle_v2_supervisor import LifecycleV2FullPlanSupervisor
from runtime.orchestrator.operator_dispatch_v2 import (
    DispatchReceiptBindingStore,
    OperatorDispatchStore,
    build_v2_operator_plan_executor,
    ensure_v2_dispatch,
    seal_v2_dispatch_receipt,
)
from runtime.orchestrator.operator_plan_execution import (
    OperatorPlanReceiptStore,
    build_operator_plan_executor,
    build_operator_plan_job,
)
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor


RUNTIME_RELEASE_DIGEST = "b" * 64
TASKS = ("TASK-001", "TASK-002", "TASK-003")


class HarnessLifecycleV2CanaryTests(unittest.TestCase):
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

    def legacy_job(self, root: Path, *, run_id: str = "legacy-run") -> dict:
        spec, plan = self.make_repo(root)
        return build_operator_plan_job(
            project_root=root,
            harness_root=root,
            runtime_code_root=root,
            project_id="canary-legacy",
            run_id=run_id,
            task_ids=("TASK-001",),
            approved_plan_path=plan,
            approved_spec_path=spec,
            approval_ref="USER-APPROVED-CANARY-LEGACY",
        )

    def v2_job(self, root: Path) -> dict:
        spec, plan = self.make_repo(root)
        return build_v2_operator_plan_job(
            project_root=root,
            harness_root=root,
            runtime_code_root=root,
            project_id="canary-v2",
            run_id="canary-v2-run",
            task_ids=TASKS,
            approved_plan_path=plan,
            approved_spec_path=spec,
            approval_ref="USER-APPROVED-CANARY-V2",
            runtime_release_digest=RUNTIME_RELEASE_DIGEST,
        )

    def supervisor_kwargs(self) -> dict:
        return {
            "min_disk_free_bytes": 0,
            "min_inode_free": 0,
            "min_memory_available_bytes": 0,
            "max_cpu_load_per_cpu_milli": 10_000_000,
            "max_io_pressure_full_avg10_milli": 1_000_000,
        }

    def create_receipt(self, root: Path, job: dict, gate_id: str) -> dict:
        gate = next(item for item in job["gates"] if item["gate_id"] == gate_id)
        return OperatorPlanReceiptStore(
            root, project_id=job["project_id"], run_id=job["run_id"]
        ).create_pass_receipt(
            gate_id=gate_id,
            plan_sha256=job["approved_plan_sha256"],
            spec_sha256=job["approved_spec_sha256"],
            branch=job["expected_branch"],
            source_head=gate["head"],
            tests=("tests.test_harness_lifecycle_v2_canary",),
        )

    def test_canary_a_legacy_path_requires_no_v2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.legacy_job(root)
            execute = build_operator_plan_executor(job)
            result = execute("TASK-001", "gate-run-1", False)
            self.assertEqual(result["reason"], "OPERATOR_TASK_RECEIPT_PENDING")
            self.assertEqual(resolve_lifecycle_binding(job)["lifecycle_mode"], "LEGACY")
            self.assertNotIn("lifecycle_binding", job)
            self.assertNotIn("execution_authority_bundle", job)
            self.assertFalse((root / "_workspace" / "operator-dispatch-v2").exists())

    def test_canary_b_existing_legacy_run_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.legacy_job(root, run_id="preexisting-run")
            supervisor = DurableFullPlanSupervisor(
                root,
                project_id=job["project_id"],
                run_id=job["run_id"],
                gates=("TASK-001",),
                **self.supervisor_kwargs(),
            )
            first = supervisor.run(build_operator_plan_executor(job))
            self.assertEqual(first.status, "WAITING_RESOURCE")
            state_path = supervisor.state_path
            before_state = state_path.read_bytes()
            before_job = json.dumps(job, sort_keys=True, separators=(",", ":"))

            resolved = resolve_lifecycle_binding(job)
            restarted = DurableFullPlanSupervisor(
                root,
                project_id=job["project_id"],
                run_id=job["run_id"],
                gates=("TASK-001",),
                **self.supervisor_kwargs(),
            )
            loaded, _ = restarted.load()

            self.assertEqual(resolved["lifecycle_mode"], "LEGACY")
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(json.dumps(job, sort_keys=True, separators=(",", ":")), before_job)
            self.assertEqual(loaded["state"], "WAITING_RESOURCE")
            self.assertFalse((root / "_workspace" / "operator-dispatch-v2").exists())

    def test_canary_c_three_task_closed_loop_survives_restart_without_duplicate_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            job = self.v2_job(root)
            dispatches = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            receipts = OperatorPlanReceiptStore(root, project_id=job["project_id"], run_id=job["run_id"])
            bindings = DispatchReceiptBindingStore(root, project_id=job["project_id"], run_id=job["run_id"])

            def new_supervisor() -> LifecycleV2FullPlanSupervisor:
                return LifecycleV2FullPlanSupervisor(
                    root,
                    project_id=job["project_id"],
                    run_id=job["run_id"],
                    gates=TASKS,
                    **self.supervisor_kwargs(),
                )

            execute = build_v2_operator_plan_executor(
                job,
                dispatch_store=dispatches,
                receipt_store=receipts,
                binding_store=bindings,
            )

            supervisor = new_supervisor()
            first = supervisor.run(execute)
            self.assertEqual(first.status, "WAITING_RESOURCE")
            self.assertEqual(first.state["wait_reason"], "OPERATOR_DISPATCH_ACK_PENDING")
            first_dispatch = dispatches.load("TASK-001")
            self.assertIsNotNone(first_dispatch)

            # Restart between dispatch and receipt: durable reconciliation must reuse the dispatch.
            restarted_dispatches = OperatorDispatchStore(root, project_id=job["project_id"], run_id=job["run_id"])
            replay = ensure_v2_dispatch(job, "TASK-001", dispatch_store=restarted_dispatches)
            self.assertEqual(replay["dispatch_id"], first_dispatch["dispatch_id"])
            self.assertEqual(replay["record_sha256"], first_dispatch["record_sha256"])
            supervisor = new_supervisor()

            for index, gate_id in enumerate(TASKS):
                current_dispatch = dispatches.load(gate_id)
                self.assertIsNotNone(current_dispatch)
                dispatch_id = current_dispatch["dispatch_id"]
                dispatches.acknowledge(gate_id)

                supervisor.resume_wait("WAITING_RESOURCE")
                receipt_wait = supervisor.run(execute)
                self.assertEqual(receipt_wait.status, "WAITING_RESOURCE")
                self.assertEqual(receipt_wait.state["wait_reason"], "OPERATOR_TASK_RECEIPT_PENDING")

                self.create_receipt(root, job, gate_id)
                sealed = seal_v2_dispatch_receipt(
                    job,
                    gate_id,
                    dispatch_store=dispatches,
                    receipt_store=receipts,
                    binding_store=bindings,
                )
                self.assertEqual(sealed["state"], "RECEIPT_SEALED")

                resumed = resume_v2_after_bound_receipt(
                    job,
                    gate_id,
                    supervisor,
                    continuation_policy=AUTO,
                    contract_valid=True,
                    attestation_valid=True,
                    owner_epoch_current=True,
                    dispatch_store=dispatches,
                    receipt_store=receipts,
                    binding_store=bindings,
                )
                self.assertEqual(resumed["state"], "RECOVERING")

                progressed = supervisor.run(execute)
                self.assertEqual(dispatches.load(gate_id)["dispatch_id"], dispatch_id)
                if index < len(TASKS) - 1:
                    next_gate = TASKS[index + 1]
                    self.assertEqual(progressed.status, "WAITING_RESOURCE")
                    self.assertEqual(progressed.state["current_gate"], next_gate)
                    self.assertEqual(progressed.state["wait_reason"], "OPERATOR_DISPATCH_ACK_PENDING")
                    self.assertIsNotNone(dispatches.load(next_gate))
                    supervisor = new_supervisor()
                else:
                    self.assertEqual(progressed.status, "COMPLETED")
                    self.assertEqual(progressed.state["completed_gates"], list(TASKS))

            dispatch_files = sorted(
                path.name for path in (root / "_workspace" / "operator-dispatch-v2" / job["project_id"] / job["run_id"]).glob("TASK-*.json")
            )
            self.assertEqual(dispatch_files, ["TASK-001.json", "TASK-002.json", "TASK-003.json"])


if __name__ == "__main__":
    unittest.main()
