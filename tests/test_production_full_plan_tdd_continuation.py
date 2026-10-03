from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.implementation_continuation import (
    ExpectedRedContractV1, FailureObservationV1, LEGACY, TDD_V1,
)
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError
from runtime.orchestrator.production_execution_gateway import build_effect_reconciliation_result, _digest

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


def green_boundary_context(**overrides):
    value = {
        "contract_valid": True,
        "checkpoint_valid": True,
        "phase": "GREEN_READY",
        "approval_valid": True,
        "source_valid": True,
        "environment_valid": True,
    }
    value.update(overrides)
    return value


def applied_reconciliation_port(request):
    return build_effect_reconciliation_result(
        request, status="APPLIED", canonical_effect_id="TE-canonical",
        canonical_receipt_ref="full-mcp://receipt/TE-canonical",
        receipt_digest="2"*64, evidence_ref="full-mcp://evidence/TE-canonical",
        observed_at="2026-10-01T10:00:00+00:00",
    )


def mismatched_reconciliation_port(request):
    result = dict(applied_reconciliation_port(request))
    result["effect_intent_id"] = "0"*64
    unsigned = dict(result); unsigned.pop("result_digest")
    result["result_digest"] = _digest(unsigned)
    return result


def tdd_revalidation(**overrides):
    value = {
        "approval_valid": True,
        "current_source_sha": "a"*40,
        "current_authority_digest": "b"*64,
        "current_dependency_environment_digest": "d"*64,
        "focused_validation_passed": False,
        "regression_validation_passed": False,
        "gate_evidence_valid": False,
    }
    value.update(overrides)
    return value


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

    def test_supervisor_requires_boundary_guard_before_green_effect(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract(); sup = self.supervisor(d, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            sup.record_expected_red(c, observation(), now=NOW)
            with self.assertRaisesRegex(ProductionFullPlanError, "TDD boundary guard"):
                sup.begin_tdd_green(c)
            with self.assertRaisesRegex(ProductionFullPlanError, "APPROVAL_INVALID"):
                sup.begin_tdd_green(c, boundary_context=green_boundary_context(approval_valid=False))
            running = sup.begin_tdd_green(c, boundary_context=green_boundary_context())
            self.assertEqual(running.phase, "GREEN_RUNNING")

    def test_supervisor_owns_all_tdd_mutating_transitions_under_existing_run_lock(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract(); sup = self.supervisor(d, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            sup.record_expected_red(c, observation(), now=NOW)
            running = sup.begin_tdd_green(c, boundary_context=green_boundary_context())
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

    def test_supervisor_exposes_common_boundary_guard_under_tdd_lock(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract(); sup = self.supervisor(d, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            sup.record_expected_red(c, observation(), now=NOW)
            sup.begin_tdd_green(c, boundary_context=green_boundary_context())
            decision = sup.evaluate_tdd_boundary({
                "contract_valid": True,
                "checkpoint_valid": True,
                "phase": "GREEN_RUNNING",
                "approval_valid": True,
                "source_valid": True,
                "environment_valid": True,
            }, "PRE_DISPATCH")
            self.assertEqual(decision.action, "WAIT_EVIDENCE")
            self.assertEqual(decision.reason, "GREEN_EFFECT_RECEIPT_REQUIRED")

    def test_direct_runner_blocked_checkpoint_never_dispatches_executor(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root, continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest)
            bad=FailureObservationV1.create(
                project_id="proj",run_id="run",task_id="TASK-001",tdd_cycle_id="TDD-001",
                source_sha="a"*40,authority_digest="b"*64,test_kind="FOCUSED_TDD",
                test_selector="tests.test_x.X.test_red",test_command_digest="c"*64,
                dependency_environment_digest="d"*64,outcome="FAILED",
                failure_semantic_signature="0"*64,failure_count=1,error_count=0,receipt_digest="f"*64)
            sup.record_expected_red(c,bad,now=NOW)
            calls=root/'calls.log'
            def executor(*_): calls.write_text(calls.read_text()+'x\n' if calls.exists() else 'x\n'); return {"status":"GATE_EXIT"}
            result=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(result.status,"BLOCKED")
            self.assertFalse(calls.exists())
            self.assertNotEqual(result.state.get("state"),"COMPLETED")

    def test_direct_runner_green_ready_without_revalidation_waits_and_dispatches_zero_effects(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
            calls=root/'calls.log'
            def executor(*_): calls.write_text('effect\n'); return {"status":"GATE_EXIT"}
            result=sup.run(executor)
            self.assertEqual(result.status,"WAITING_EVIDENCE")
            self.assertEqual(result.state.get("wait_reason"),"TDD_REVALIDATION_REQUIRED")
            self.assertFalse(calls.exists())

    def test_direct_runner_green_ready_invalid_revalidation_dispatches_zero_effects(self):
        cases=(
            {"approval_valid":False},
            {"current_source_sha":"9"*40},
            {"current_dependency_environment_digest":"8"*64},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as d:
                root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
                sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
                calls=root/'calls.log'
                def executor(*_): calls.write_text('effect\n'); return {"status":"GATE_EXIT"}
                result=sup.run(executor,tdd_revalidation=tdd_revalidation(**overrides))
                self.assertEqual(result.status,"BLOCKED")
                self.assertFalse(calls.exists())

    def test_green_effect_runs_once_then_missing_receipt_waits_without_replay(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
            calls=root/'calls.log'
            def executor(*_):
                calls.write_text(calls.read_text()+'effect\n' if calls.exists() else 'effect\n')
                return {"status":"GATE_EXIT"}
            first=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(first.status,"WAITING_EVIDENCE")
            running=sup.tdd_store().load()
            self.assertEqual(running.phase,"GREEN_RUNNING")
            second=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(second.status,"WAITING_EVIDENCE")
            self.assertEqual(calls.read_text().splitlines(),["effect"])
            reconciled=sup.run(
                executor,tdd_revalidation=tdd_revalidation(),
                effect_reconciliation_port=applied_reconciliation_port)
            self.assertEqual(reconciled.status,"WAITING_EVIDENCE")
            self.assertEqual(sup.tdd_store().load().phase,"FOCUSED_VALIDATION")
            self.assertEqual(calls.read_text().splitlines(),["effect"])

    def test_executor_local_receipt_fields_cannot_replace_full_mcp_reconciliation_port(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
            calls=root/'calls.log'
            def executor(*_):
                calls.write_text('effect\n')
                running=sup.tdd_store().load()
                return {"status":"GATE_EXIT","effect_intent_id":running.effect_step_id,
                        "canonical_receipt_digest":"2"*64,"effect_reconciliation":"RECONCILED"}
            result=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(result.status,"WAITING_EVIDENCE")
            self.assertEqual(result.state.get("wait_reason"),"EFFECT_RECONCILIATION_REQUIRED")
            self.assertEqual(sup.tdd_store().load().phase,"GREEN_RUNNING")
            self.assertEqual(calls.read_text().splitlines(),["effect"])

    def test_matching_effect_receipt_advances_validation_without_parent_completion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
            calls=root/'calls.log'
            def executor(*_):
                calls.write_text('effect\n')
                return {"status":"GATE_EXIT"}
            result=sup.run(
                executor,tdd_revalidation=tdd_revalidation(),
                effect_reconciliation_port=applied_reconciliation_port)
            self.assertEqual(result.status,"WAITING_EVIDENCE")
            self.assertEqual(sup.tdd_store().load().phase,"FOCUSED_VALIDATION")
            self.assertNotEqual(result.state.get("state"),"COMPLETED")
            self.assertEqual(calls.read_text().splitlines(),["effect"])

    def test_receipt_binding_mismatch_blocks_without_effect_replay(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
            calls=root/'calls.log'
            def executor(*_):
                calls.write_text(calls.read_text()+'effect\n' if calls.exists() else 'effect\n')
                return {"status":"GATE_EXIT"}
            first=sup.run(
                executor,tdd_revalidation=tdd_revalidation(),
                effect_reconciliation_port=mismatched_reconciliation_port)
            self.assertEqual(first.status,"BLOCKED")
            second=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(second.status,"BLOCKED")
            self.assertEqual(calls.read_text().splitlines(),["effect"])

    def test_parent_completion_requires_completed_tdd_and_gate_evidence_without_reexecuting_effect(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=contract(); sup=self.supervisor(root,continuation_mode=TDD_V1)
            sup.arm_expected_red(c); sup.begin_expected_red(c.contract_digest); sup.record_expected_red(c,observation(),now=NOW)
            calls=root/'calls.log'
            def executor(*_):
                calls.write_text(calls.read_text()+'effect\n' if calls.exists() else 'effect\n')
                return {"status":"GATE_EXIT"}
            sup.run(
                executor,tdd_revalidation=tdd_revalidation(),
                effect_reconciliation_port=applied_reconciliation_port)
            focused_wait=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(focused_wait.status,"WAITING_EVIDENCE")
            self.assertEqual(calls.read_text().splitlines(),["effect"])
            sup.record_tdd_focused_validation(passed=True,receipt_digest="3"*64)
            regression_wait=sup.run(executor,tdd_revalidation=tdd_revalidation())
            self.assertEqual(regression_wait.status,"WAITING_EVIDENCE")
            self.assertEqual(calls.read_text().splitlines(),["effect"])
            sup.record_tdd_regression_validation(passed=True,receipt_digest="4"*64,regression_delta_current_only=0)
            waiting=sup.run(executor,tdd_revalidation=tdd_revalidation(
                focused_validation_passed=True,regression_validation_passed=True,gate_evidence_valid=False))
            self.assertEqual(waiting.status,"WAITING_EVIDENCE")
            completed=sup.run(executor,tdd_revalidation=tdd_revalidation(
                focused_validation_passed=True,regression_validation_passed=True,gate_evidence_valid=True))
            self.assertEqual(completed.status,"COMPLETED")
            self.assertEqual(calls.read_text().splitlines(),["effect"])

    def test_legacy_direct_runner_behavior_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); sup=self.supervisor(root)
            calls=root/'calls.log'
            def executor(*_): calls.write_text('legacy\n'); return {"status":"GATE_EXIT"}
            result=sup.run(executor)
            self.assertEqual(result.status,"COMPLETED")
            self.assertEqual(calls.read_text().splitlines(),["legacy"])

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
