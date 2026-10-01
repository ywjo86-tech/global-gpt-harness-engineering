from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.implementation_continuation import (
    ExpectedRedContractV1,
    FailureObservationV1,
    TDDContinuationError,
    TDDContinuationStore,
)


NOW = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
SHA40 = "a" * 40
SHA64 = "b" * 64
AUTH = "c" * 64
CMD = "d" * 64
ENV = "e" * 64
FAIL_SIG = "f" * 64
RECEIPT = "1" * 64


def contract(**overrides):
    values = dict(
        project_id="P", run_id="R", task_id="TASK-001", tdd_cycle_id="TDD-001",
        source_sha=SHA40, authority_digest=AUTH, test_kind="FOCUSED_TDD",
        test_selector="tests.test_x.X.test_red", test_command_digest=CMD,
        dependency_environment_digest=ENV, expected_failure_semantic_signature=FAIL_SIG,
        expected_failure_count=1, allowed_error_count=0,
        valid_until=(NOW + timedelta(hours=1)).isoformat(),
        allowed_change_paths=("runtime/orchestrator/", "tests/"), max_remediation_attempts=2,
    )
    values.update(overrides)
    return ExpectedRedContractV1.create(**values)


def observation(**overrides):
    values = dict(
        project_id="P", run_id="R", task_id="TASK-001", tdd_cycle_id="TDD-001",
        source_sha=SHA40, authority_digest=AUTH, test_kind="FOCUSED_TDD",
        test_selector="tests.test_x.X.test_red", test_command_digest=CMD,
        dependency_environment_digest=ENV, outcome="FAILED",
        failure_semantic_signature=FAIL_SIG, failure_count=1, error_count=0,
        receipt_digest=RECEIPT,
    )
    values.update(overrides)
    return FailureObservationV1.create(**values)


class FullPlanTDDContinuationTests(unittest.TestCase):
    def test_exact_expected_red_moves_to_green_ready(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            result = store.record_red_observation(c, observation(), now=NOW)
            self.assertEqual(result.phase, "GREEN_READY")
            self.assertEqual(result.next_action, "RUN_GREEN")
            self.assertEqual(result.latest_test_receipt_digest, RECEIPT)

    def test_unexpected_failure_blocks_and_never_schedules_green(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            result = store.record_red_observation(
                c, observation(failure_semantic_signature="0" * 64), now=NOW)
            self.assertEqual(result.phase, "BLOCKED")
            self.assertEqual(result.next_action, "NONE")
            self.assertEqual(result.block_reason, "UNEXPECTED_FAILURE")

    def test_full_regression_delta_and_p5_p6_cannot_be_armed_as_expected_red(self):
        for kind in ("FULL_REGRESSION", "REGRESSION_DELTA", "P5_LIFECYCLE", "P6_LIFECYCLE"):
            with self.subTest(kind=kind), self.assertRaisesRegex(TDDContinuationError, "focused TDD"):
                contract(test_kind=kind)

    def test_expected_red_contract_is_durable_and_reloadable_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); c = contract()
            first = TDDContinuationStore(root, project_id="P", run_id="R")
            first.arm(c)
            restarted = TDDContinuationStore(root, project_id="P", run_id="R")
            loaded = restarted.load_contract()
            self.assertEqual(loaded, c)
            self.assertEqual(loaded.contract_digest, c.contract_digest)

    def test_tampered_durable_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); c = contract()
            store = TDDContinuationStore(root, project_id="P", run_id="R")
            store.arm(c)
            path = store.contract_path(c.task_id, c.tdd_cycle_id)
            raw = path.read_text(encoding="utf-8").replace(FAIL_SIG, "0" * 64)
            path.write_text(raw, encoding="utf-8")
            path.with_suffix(path.suffix + ".prev").unlink(missing_ok=True)
            with self.assertRaisesRegex(TDDContinuationError, "contract"):
                TDDContinuationStore(root, project_id="P", run_id="R").load_contract()

    def test_session_restart_resumes_green_from_durable_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); c = contract()
            first = TDDContinuationStore(root, project_id="P", run_id="R")
            first.arm(c); first.begin_red(c.contract_digest)
            first.record_red_observation(c, observation(), now=NOW)
            restarted = TDDContinuationStore(root, project_id="P", run_id="R")
            decision = restarted.resume(
                c, current_source_sha=SHA40, current_authority_digest=AUTH,
                current_dependency_environment_digest=ENV, approval_valid=True, now=NOW)
            self.assertEqual(decision.action, "RUN_GREEN")
            self.assertEqual(restarted.load().phase, "GREEN_READY")

    def test_resume_revalidates_source_authority_environment_and_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            for field, value in (
                ("current_source_sha", "9" * 40),
                ("current_authority_digest", "8" * 64),
                ("current_dependency_environment_digest", "7" * 64),
            ):
                kwargs = dict(current_source_sha=SHA40, current_authority_digest=AUTH,
                              current_dependency_environment_digest=ENV, approval_valid=True, now=NOW)
                kwargs[field] = value
                self.assertEqual(store.resume(c, **kwargs).action, "BLOCKED")
            self.assertEqual(store.resume(
                c, current_source_sha=SHA40, current_authority_digest=AUTH,
                current_dependency_environment_digest=ENV, approval_valid=False, now=NOW).action, "BLOCKED")

    def test_green_effect_is_deterministic_and_blind_retry_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            running = store.begin_green(c)
            self.assertEqual(running.phase, "GREEN_RUNNING")
            self.assertRegex(running.effect_step_id, r"^[0-9a-f]{64}$")
            with self.assertRaisesRegex(TDDContinuationError, "reconciliation"):
                store.begin_green(c)

    def test_green_crash_requires_canonical_receipt_before_resume(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); c = contract()
            store = TDDContinuationStore(root, project_id="P", run_id="R")
            store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            running = store.begin_green(c)
            restarted = TDDContinuationStore(root, project_id="P", run_id="R")
            blocked = restarted.resume(
                c, current_source_sha=SHA40, current_authority_digest=AUTH,
                current_dependency_environment_digest=ENV, approval_valid=True, now=NOW)
            self.assertEqual(blocked.action, "BLOCKED_RECONCILIATION_REQUIRED")
            reconciled = restarted.reconcile_green_effect(
                c, effect_step_id=running.effect_step_id,
                canonical_receipt_digest="2" * 64, effect_reconciliation="RECONCILED")
            self.assertEqual(reconciled.phase, "FOCUSED_VALIDATION")

    def test_positive_validation_only_after_green_receipt_and_regression_delta_zero(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            running = store.begin_green(c)
            store.reconcile_green_effect(c, effect_step_id=running.effect_step_id,
                                         canonical_receipt_digest="2"*64,
                                         effect_reconciliation="RECONCILED")
            store.record_focused_validation(passed=True, receipt_digest="3"*64)
            done = store.record_regression_validation(
                passed=True, receipt_digest="4"*64, regression_delta_current_only=0)
            self.assertEqual(done.phase, "COMPLETED")
            self.assertEqual(done.next_action, "NONE")

    def test_regression_failure_is_never_expected_red(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            running = store.begin_green(c)
            store.reconcile_green_effect(c, effect_step_id=running.effect_step_id,
                                         canonical_receipt_digest="2"*64,
                                         effect_reconciliation="RECONCILED")
            store.record_focused_validation(passed=True, receipt_digest="3"*64)
            blocked = store.record_regression_validation(
                passed=False, receipt_digest="4"*64, regression_delta_current_only=1)
            self.assertEqual(blocked.phase, "BLOCKED")
            self.assertEqual(blocked.block_reason, "REGRESSION_VALIDATION_FAILED")

    def test_bounded_remediation_enforces_attempt_and_change_scope(self):
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(max_remediation_attempts=1)
            store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            running = store.begin_green(c)
            store.reconcile_green_effect(c, effect_step_id=running.effect_step_id,
                                         canonical_receipt_digest="2"*64,
                                         effect_reconciliation="RECONCILED")
            store.record_focused_validation(passed=False, receipt_digest="3"*64)
            resumed = store.request_bounded_remediation(
                c, changed_paths=("runtime/orchestrator/x.py",),
                failure_class="IMPLEMENTATION_TEST_FAILURE")
            self.assertEqual(resumed.phase, "GREEN_READY")
            running2 = store.begin_green(c)
            store.reconcile_green_effect(c, effect_step_id=running2.effect_step_id,
                                         canonical_receipt_digest="5"*64,
                                         effect_reconciliation="RECONCILED")
            store.record_focused_validation(passed=False, receipt_digest="6"*64)
            with self.assertRaisesRegex(TDDContinuationError, "budget"):
                store.request_bounded_remediation(
                    c, changed_paths=("runtime/orchestrator/x.py",),
                    failure_class="IMPLEMENTATION_TEST_FAILURE")
        with tempfile.TemporaryDirectory() as d:
            store = TDDContinuationStore(Path(d), project_id="P", run_id="R")
            c = contract(); store.arm(c); store.begin_red(c.contract_digest)
            store.record_red_observation(c, observation(), now=NOW)
            running = store.begin_green(c)
            store.reconcile_green_effect(c, effect_step_id=running.effect_step_id,
                                         canonical_receipt_digest="2"*64,
                                         effect_reconciliation="RECONCILED")
            store.record_focused_validation(passed=False, receipt_digest="3"*64)
            with self.assertRaisesRegex(TDDContinuationError, "scope"):
                store.request_bounded_remediation(
                    c, changed_paths=("deploy/prod.sh",),
                    failure_class="IMPLEMENTATION_TEST_FAILURE")


if __name__ == "__main__":
    unittest.main()
