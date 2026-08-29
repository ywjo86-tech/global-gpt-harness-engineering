from __future__ import annotations

import unittest
import subprocess
import tempfile
from pathlib import Path

from runtime.orchestrator.gate_controller import (
    GateControllerAdapters,
    GateControllerError,
    gate_dry_run,
    run_gate_lifecycle,
    run_production_gate_lifecycle,
)
from runtime.orchestrator.production_approval import write_production_approval


SHA = "a" * 64


class GateControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "project_id": "fixture-project",
            "gate_id": "GATE-1",
            "lv_id": "G1-LV3-1",
            "run_id": "run-1",
            "plan_sha256": SHA,
        }

    @staticmethod
    def _result(status: str) -> dict[str, object]:
        return {"status": status, "exit_code": 0, "evidence_sha256": SHA, "hard_stop": True}

    def _adapters(self, calls: list[str], reviews: list[str] | None = None) -> GateControllerAdapters:
        review_statuses = iter(reviews or ["PASS"])

        def adapter(name: str, status: str):
            def call(payload):
                self.assertEqual(payload["plan_sha256"], SHA)
                self.assertIsInstance(payload["prior_evidence"], dict)
                calls.append(name)
                return self._result(status)
            return call

        def review(payload):
            calls.append("review")
            return self._result(next(review_statuses))

        return GateControllerAdapters(
            package=adapter("package", "SEALED"),
            preflight=adapter("preflight", "READY"),
            worker=adapter("worker", "COMPLETED"),
            review=review,
            remediation=adapter("remediation", "PASS"),
            checkpoint=adapter("checkpoint", "CHECKPOINTED"),
            exit=adapter("exit", "EXITED"),
            handoff=adapter("handoff", "SEALED"),
        )

    def test_dry_run_is_distinct_and_invokes_nothing(self) -> None:
        outcome = gate_dry_run(self.context)
        self.assertEqual(outcome["status"], "DRY_RUN")
        self.assertFalse(outcome["mutation_performed"])
        self.assertEqual(outcome["stages"][-1], "SYSTEM_TRANSITION")

    def test_actual_controller_calls_full_order_and_transitions(self) -> None:
        calls: list[str] = []
        outcome = run_gate_lifecycle(self.context, self._adapters(calls))
        self.assertEqual(calls, ["package", "preflight", "worker", "review", "checkpoint", "exit", "handoff"])
        self.assertEqual(outcome["status"], "SYSTEM_TRANSITION")
        self.assertFalse(outcome["user_approval_renewal"])
        self.assertFalse(outcome["remediated"])

    def test_failed_review_runs_remediation_and_independent_rereview(self) -> None:
        calls: list[str] = []
        outcome = run_gate_lifecycle(self.context, self._adapters(calls, ["FAIL", "PASS"]))
        self.assertEqual(calls, ["package", "preflight", "worker", "review", "remediation", "review", "checkpoint", "exit", "handoff"])
        self.assertTrue(outcome["remediated"])

    def test_nonzero_exit_invalid_evidence_and_missing_hard_stop_fail_closed(self) -> None:
        for mutation, message in (
            ({"exit_code": 9}, "exit code 9"),
            ({"evidence_sha256": "bad"}, "invalid evidence"),
            ({"hard_stop": False}, "hard-stop"),
        ):
            with self.subTest(mutation=mutation):
                calls: list[str] = []
                adapters = self._adapters(calls)

                def bad_package(payload):
                    value = self._result("SEALED")
                    value.update(mutation)
                    return value

                adapters = GateControllerAdapters(bad_package, adapters.preflight, adapters.worker, adapters.review, adapters.remediation, adapters.checkpoint, adapters.exit, adapters.handoff)
                with self.assertRaisesRegex(GateControllerError, message):
                    run_gate_lifecycle(self.context, adapters)
                self.assertEqual(calls, [])

    def test_failed_post_remediation_review_stops_before_checkpoint(self) -> None:
        calls: list[str] = []
        with self.assertRaisesRegex(GateControllerError, "did not pass"):
            run_gate_lifecycle(self.context, self._adapters(calls, ["FAIL", "FAIL"]))
        self.assertEqual(calls[-2:], ["remediation", "review"])
        self.assertNotIn("checkpoint", calls)

    def test_production_controller_consumes_only_v2_and_validates_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fixture-project"; root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
            (root / "PLAN.md").write_text("plan\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, capture_output=True)
            approval = write_production_approval(
                project_root=root, output_path="approval.json", gate_id="GATE-1", plan_sha256=SHA,
                approval_mode="GATE_BY_GATE", canonical_lv_scope=["G1-LV3-1"],
                owned_file_scope={"G1-LV3-1": ["app/a.py"]}, completion_conditions_sha256="c"*64,
                authorization_source="USER_OWNER", dry_run=True,
            )["event"]
            context = {
                **self.context, "branch": "main", "baseline_head": approval["baseline_head"],
                "approval_mode": "GATE_BY_GATE", "canonical_lv_scope": ["G1-LV3-1"],
                "owned_file_scope": {"G1-LV3-1": ["app/a.py"]}, "phase": "PHASE-1",
            }
            state = {
                "schema_version": "orchestration.canonical-gate-state.v2", "project_id": "fixture-project",
                "gate_id": "GATE-1", "phase": "PHASE-1", "plan_sha256": SHA,
                "gate_status": "READY_FOR_TRANSITION", "closure_status": "CLOSED",
                "approval_record_hash": approval["record_hash"],
            }
            calls: list[str] = []
            outcome = run_production_gate_lifecycle(
                context, self._adapters(calls), approval_events=[approval], project_root=str(root),
                canonical_state=state, completion_conditions_sha256="c"*64,
            )
            self.assertEqual(outcome["production_approval_schema"], "orchestration.production-approval.v2")
            calls.clear()
            with self.assertRaises(GateControllerError):
                run_production_gate_lifecycle(
                    context, self._adapters(calls), approval_events=[{"schema_version": "orchestration.gate-approval.v1"}],
                    project_root=str(root), canonical_state=state, completion_conditions_sha256="c"*64,
                )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
