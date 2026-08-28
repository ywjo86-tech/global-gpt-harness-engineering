from __future__ import annotations

import unittest

from runtime.orchestrator.gate_controller import (
    GateControllerAdapters,
    GateControllerError,
    gate_dry_run,
    run_gate_lifecycle,
)


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


if __name__ == "__main__":
    unittest.main()
