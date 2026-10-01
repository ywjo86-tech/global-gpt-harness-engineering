from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.implementation_continuation import (
    ExpectedRedContractV1, FailureObservationV1, LEGACY, TDD_V1,
)
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError

NOW = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)


def contract():
    return ExpectedRedContractV1.create(
        project_id="proj", run_id="run", task_id="TASK-001", tdd_cycle_id="TDD-001",
        source_sha="a"*40, authority_digest="b"*64, test_kind="FOCUSED_TDD",
        test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
        dependency_environment_digest="d"*64, expected_failure_semantic_signature="e"*64,
        expected_failure_count=1, allowed_error_count=0,
        valid_until=(NOW + timedelta(hours=1)).isoformat(),
        allowed_change_paths=("runtime/orchestrator/", "tests/"), max_remediation_attempts=1,
    )


def observation():
    return FailureObservationV1.create(
        project_id="proj", run_id="run", task_id="TASK-001", tdd_cycle_id="TDD-001",
        source_sha="a"*40, authority_digest="b"*64, test_kind="FOCUSED_TDD",
        test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
        dependency_environment_digest="d"*64, outcome="FAILED",
        failure_semantic_signature="e"*64, failure_count=1, error_count=0,
        receipt_digest="f"*64,
    )


class ProductionFullPlanTDDContinuationTests(unittest.TestCase):
    def supervisor(self, root, **kw):
        return DurableFullPlanSupervisor(
            root, project_id="proj", run_id="run", gates=["TASK-001"],
            retry_budget=0, gate_timeout_seconds=1, heartbeat_seconds=.03,
            lease_seconds=.08, min_disk_free_bytes=0, min_inode_free=0,
            min_memory_available_bytes=0, authority_core_sha256="b"*64, **kw)

    def test_existing_jobs_default_to_legacy_without_tdd_state(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d)
            state, _ = sup.load()
            self.assertEqual(sup.continuation_mode, LEGACY)
            self.assertNotIn("tdd_continuation", state)
            with self.assertRaisesRegex(ProductionFullPlanError, "TDD_V1"):
                sup.tdd_store()

    def test_invalid_continuation_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProductionFullPlanError, "continuation mode"):
                self.supervisor(d, continuation_mode="FUTURE")

    def test_tdd_v1_is_opt_in_and_persisted_in_full_plan_state(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, continuation_mode=TDD_V1)
            state, _ = sup.load()
            self.assertEqual(sup.continuation_mode, TDD_V1)
            self.assertEqual(state["tdd_continuation"], {"mode": TDD_V1})

    def test_continuation_mode_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, continuation_mode=TDD_V1)
            state, _ = sup.load(); sup._persist(state, {"event":"INIT"})
            with self.assertRaisesRegex(ProductionFullPlanError, "CONTINUATION_MODE_DRIFT"):
                self.supervisor(d, continuation_mode=LEGACY).load()

    def test_supervisor_rejects_expected_red_from_different_authority_or_task(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, continuation_mode=TDD_V1)
            bad_authority = ExpectedRedContractV1.create(
                project_id="proj", run_id="run", task_id="G1", tdd_cycle_id="TDD-001",
                source_sha="a"*40, authority_digest="9"*64, test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
                dependency_environment_digest="d"*64, expected_failure_semantic_signature="e"*64,
                expected_failure_count=1, allowed_error_count=0,
                valid_until=(NOW+timedelta(hours=1)).isoformat(),
                allowed_change_paths=("runtime/orchestrator/",), max_remediation_attempts=1)
            with self.assertRaisesRegex(ProductionFullPlanError, "authority"):
                sup.arm_expected_red(bad_authority)
            bad_task = ExpectedRedContractV1.create(
                project_id="proj", run_id="run", task_id="OTHER", tdd_cycle_id="TDD-002",
                source_sha="a"*40, authority_digest="b"*64, test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
                dependency_environment_digest="d"*64, expected_failure_semantic_signature="e"*64,
                expected_failure_count=1, allowed_error_count=0,
                valid_until=(NOW+timedelta(hours=1)).isoformat(),
                allowed_change_paths=("runtime/orchestrator/",), max_remediation_attempts=1)
            with self.assertRaisesRegex(ProductionFullPlanError, "Task"):
                sup.arm_expected_red(bad_task)

    def test_supervisor_restart_resumes_exact_expected_red_as_green_ready(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract(); sup = self.supervisor(d, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            sup.record_expected_red(c, observation(), now=NOW)
            restarted = self.supervisor(d, continuation_mode=TDD_V1)
            decision = restarted.resume_tdd(
                current_source_sha="a"*40, current_authority_digest="b"*64,
                current_dependency_environment_digest="d"*64,
                approval_valid=True, now=NOW)
            self.assertEqual(decision.action, "RUN_GREEN")

    def test_supervisor_owns_all_tdd_mutating_transitions_under_existing_run_lock(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract(); sup = self.supervisor(d, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            sup.record_expected_red(c, observation(), now=NOW)
            running = sup.begin_tdd_green(c)
            self.assertEqual(running.phase, "GREEN_RUNNING")
            focused = sup.reconcile_tdd_green_effect(
                c, effect_step_id=running.effect_step_id, canonical_receipt_digest="2"*64,
                effect_reconciliation="RECONCILED")
            self.assertEqual(focused.phase, "FOCUSED_VALIDATION")
            regression = sup.record_tdd_focused_validation(passed=True, receipt_digest="3"*64)
            self.assertEqual(regression.phase, "REGRESSION_VALIDATION")
            completed = sup.record_tdd_regression_validation(
                passed=True, receipt_digest="4"*64, regression_delta_current_only=0)
            self.assertEqual(completed.phase, "COMPLETED")

    def test_supervisor_does_not_turn_unexpected_failure_into_green(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract(); sup = self.supervisor(d, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            bad = FailureObservationV1.create(
                project_id="proj", run_id="run", task_id="TASK-001", tdd_cycle_id="TDD-001",
                source_sha="a"*40, authority_digest="b"*64, test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red", test_command_digest="c"*64,
                dependency_environment_digest="d"*64, outcome="FAILED",
                failure_semantic_signature="0"*64, failure_count=1, error_count=0,
                receipt_digest="f"*64)
            result = sup.record_expected_red(c, bad, now=NOW)
            self.assertEqual(result.phase, "BLOCKED")
            self.assertEqual(sup.resume_tdd(
                current_source_sha="a"*40, current_authority_digest="b"*64,
                current_dependency_environment_digest="d"*64,
                approval_valid=True, now=NOW).action, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
