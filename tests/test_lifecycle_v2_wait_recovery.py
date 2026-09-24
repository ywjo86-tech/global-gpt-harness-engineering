import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.orchestrator.wait_recovery import classify_wait_recovery


class LifecycleV2WaitRecoveryTests(unittest.TestCase):
    def test_ack_pending_wait_reason_is_preserved_by_full_plan(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            supervisor = DurableFullPlanSupervisor(
                root,
                project_id="v2-wait-proj",
                run_id="v2-wait-run",
                gates=("TASK-001",),
                min_disk_free_bytes=0,
                min_inode_free=0,
                min_memory_available_bytes=0,
                max_cpu_load_per_cpu_milli=10_000_000,
                max_io_pressure_full_avg10_milli=1_000_000,
            )

            def execute(gate_id: str, gate_run_id: str, resume: bool):
                del gate_id, gate_run_id, resume
                return {
                    "status": "WAITING_RESOURCE",
                    "reason": "OPERATOR_DISPATCH_ACK_PENDING",
                }

            result = supervisor.run(execute)
            self.assertEqual(result.status, "WAITING_RESOURCE")
            self.assertEqual(result.state["wait_reason"], "OPERATOR_DISPATCH_ACK_PENDING")
            self.assertEqual(result.state["last_error"], "OPERATOR_DISPATCH_ACK_PENDING")

    def test_ack_pending_wait_has_explicit_recovery_owner_but_not_receipt_continuation(self) -> None:
        assessment = classify_wait_recovery({
            "state": "WAITING_RESOURCE",
            "wait_reason": "OPERATOR_DISPATCH_ACK_PENDING",
        })
        self.assertEqual(assessment.owner, "DCC_OR_OPERATOR")
        self.assertTrue(assessment.auto_recoverable)


if __name__ == "__main__":
    unittest.main()
