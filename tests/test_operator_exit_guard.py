from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.user_interaction_policy import UserDecisionAssessment
from runtime.orchestrator.operator_exit_guard import (
    ALLOW_COMPLETION_RESPONSE,
    CONTINUE_EXECUTION,
    NOTIFY_STALLED,
    REPORT_TERMINAL_STOP,
    REPORT_BOUNDED_CHECKPOINT,
    REQUEST_USER_DECISION,
    assess_operator_turn_exit,
    assess_run_base,
)

NOW = datetime(2026, 9, 19, 13, 0, tzinfo=timezone.utc)


def full_plan_state(state: str = "READY") -> dict:
    return {
        "schema_version": "orchestration.production-full-plan.v1",
        "project_id": "P",
        "run_id": "R",
        "mode": "FULL_PLAN",
        "gates": ["G1"],
        "completed_gates": [],
        "current_gate": "G1",
        "state": state,
        "queue": [{"gate_id": "G1", "status": "READY"}],
        "last_error": None,
        "terminal_reason": None,
        "last_semantic_progress_at": "2026-09-19T12:59:30+00:00",
    }


def completed_state() -> dict:
    state = full_plan_state("COMPLETED")
    state.update({
        "completed_gates": ["G1"],
        "current_gate": None,
        "queue": [{"gate_id": "G1", "status": "COMPLETED"}],
        "terminal_reason": "ALL_GATES_COMPLETED",
    })
    return state


class OperatorExitGuardTests(unittest.TestCase):
    def test_r30_like_ready_work_cannot_end_turn(self) -> None:
        result = assess_operator_turn_exit(
            full_plan_state(), now=NOW,
            continuation_states=[{"execution_state": "PREPARED", "next_action": "EXECUTE_TASK_017"}],
            completion_obligations={"EDP_ALL_PASS": False, "STABLE_BASELINE_SEALED": False},
        )
        self.assertEqual(result.disposition, CONTINUE_EXECUTION)
        self.assertFalse(result.allow_final_response)
        self.assertIn("EDP_ALL_PASS", result.pending_obligations)

    def test_provider_wait_before_threshold_continues_without_user_call(self) -> None:
        state = full_plan_state("WAITING_PROVIDER")
        state["last_error"] = "provider timeout"
        event = {"kind": "WAITING_PROVIDER", "state": "WAITING_PROVIDER", "reason": "provider timeout",
                 "created_at": (NOW - timedelta(seconds=299)).isoformat(), "delivery_class": "DEFERRED_INCIDENT"}
        result = assess_operator_turn_exit(state, attention_events=[event], now=NOW, completion_obligations={})
        self.assertEqual(result.disposition, CONTINUE_EXECUTION)
        self.assertFalse(result.allow_final_response)

    def test_unresolved_provider_wait_at_threshold_notifies_stalled(self) -> None:
        state = full_plan_state("WAITING_PROVIDER")
        state["last_error"] = "provider timeout"
        state["last_semantic_progress_at"] = (NOW - timedelta(seconds=300)).isoformat()
        event = {"kind": "WAITING_PROVIDER", "state": "WAITING_PROVIDER", "reason": "provider timeout",
                 "created_at": (NOW - timedelta(seconds=300)).isoformat(), "delivery_class": "DEFERRED_INCIDENT"}
        result = assess_operator_turn_exit(state, attention_events=[event], now=NOW, completion_obligations={})
        self.assertEqual(result.disposition, NOTIFY_STALLED)
        self.assertTrue(result.allow_final_response)
        self.assertFalse(result.successful_completion)

    def test_genuine_user_decision_is_immediate(self) -> None:
        state = full_plan_state("WAITING_APPROVAL")
        state["last_error"] = "approval required"
        decision = UserDecisionAssessment(True, "RISK_ESCALATION", "scope expanded")
        result = assess_operator_turn_exit(state, now=NOW, user_decision=decision, completion_obligations={})
        self.assertEqual(result.disposition, REQUEST_USER_DECISION)
        self.assertTrue(result.allow_final_response)
        self.assertFalse(result.successful_completion)

    def test_completed_full_plan_without_completion_contract_still_cannot_end(self) -> None:
        result = assess_operator_turn_exit(completed_state(), now=NOW, completion_obligations=None)
        self.assertEqual(result.disposition, CONTINUE_EXECUTION)
        self.assertFalse(result.allow_final_response)
        self.assertEqual(result.reason, "completion obligations were not supplied")

    def test_completed_full_plan_with_false_obligation_continues(self) -> None:
        result = assess_operator_turn_exit(
            completed_state(), now=NOW,
            completion_obligations={"EDP_ALL_PASS": True, "STABLE_BASELINE_SEALED": False},
        )
        self.assertEqual(result.disposition, CONTINUE_EXECUTION)
        self.assertEqual(result.pending_obligations, ("STABLE_BASELINE_SEALED",))

    def test_completed_full_plan_with_all_obligations_allows_completion_response(self) -> None:
        result = assess_operator_turn_exit(
            completed_state(), now=NOW,
            completion_obligations={"EDP_ALL_PASS": True, "STABLE_BASELINE_SEALED": True},
            continuation_states=[{"execution_state": "COMPLETED", "next_action": "FANIN"}],
        )
        self.assertEqual(result.disposition, ALLOW_COMPLETION_RESPONSE)
        self.assertTrue(result.allow_final_response)
        self.assertTrue(result.successful_completion)

    def test_cancelled_run_allows_terminal_status_but_not_success(self) -> None:
        state = full_plan_state("CANCELLED")
        state["terminal_reason"] = "USER_CANCELLED"
        result = assess_operator_turn_exit(state, now=NOW, completion_obligations={})
        self.assertEqual(result.disposition, REPORT_TERMINAL_STOP)
        self.assertTrue(result.allow_final_response)
        self.assertFalse(result.successful_completion)

    def test_budget_yield_requires_durable_checkpoint(self) -> None:
        result = assess_operator_turn_exit(
            full_plan_state(), now=NOW, completion_obligations={},
            bounded_turn_yield=True, durable_turn_checkpoint=False,
        )
        self.assertEqual(result.disposition, CONTINUE_EXECUTION)
        self.assertFalse(result.allow_final_response)

    def test_budget_yield_with_durable_checkpoint_reports_nonterminal_pause(self) -> None:
        result = assess_operator_turn_exit(
            full_plan_state(), now=NOW, completion_obligations={},
            bounded_turn_yield=True, durable_turn_checkpoint=True,
        )
        self.assertEqual(result.disposition, REPORT_BOUNDED_CHECKPOINT)
        self.assertTrue(result.allow_final_response)
        self.assertFalse(result.successful_completion)

    def test_blocked_with_verified_recovery_continues(self) -> None:
        state = full_plan_state("BLOCKED")
        state["last_error"] = "artifact recovery needed"
        result = assess_operator_turn_exit(
            state, now=NOW, completion_obligations={}, recoverable_continuation=True,
        )
        self.assertEqual(result.disposition, CONTINUE_EXECUTION)
        self.assertFalse(result.allow_final_response)

    def test_malformed_or_incomplete_state_fails_closed(self) -> None:
        for state in ({}, {"state": "COMPLETED"}, {"state": "COMPLETED", "gates": ["G1"], "completed_gates": ["G1"]}):
            with self.subTest(state=state):
                result = assess_operator_turn_exit(state, now=NOW, completion_obligations={})
                self.assertEqual(result.disposition, CONTINUE_EXECUTION)
                self.assertFalse(result.allow_final_response)

    def test_run_base_reads_persisted_state_and_attention_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = completed_state()
            raw = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            state["state_sha256"] = hashlib.sha256(raw).hexdigest()
            (base / "state.json").write_text(json.dumps(state), encoding="utf-8")
            before = (base / "state.json").read_bytes()
            result = assess_run_base(base, now=NOW, completion_obligations={"EDP_ALL_PASS": True})
            self.assertEqual(result.disposition, ALLOW_COMPLETION_RESPONSE)
            self.assertEqual((base / "state.json").read_bytes(), before)


    def test_stall_notification_wins_over_merely_available_recovery(self) -> None:
        state = full_plan_state("BLOCKED")
        state["last_error"] = "recovery pending"
        state["last_semantic_progress_at"] = (NOW - timedelta(seconds=300)).isoformat()
        event = {"kind": "DEAD_LETTER", "state": "BLOCKED", "reason": "recovery pending",
                 "created_at": (NOW - timedelta(seconds=300)).isoformat(), "delivery_class": "DEFERRED_INCIDENT"}
        result = assess_operator_turn_exit(
            state, attention_events=[event], now=NOW, completion_obligations={}, recoverable_continuation=True,
        )
        self.assertEqual(result.disposition, NOTIFY_STALLED)

    def test_run_base_rejects_tampered_persisted_state_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = completed_state()
            unsigned = dict(state)
            raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            state["state_sha256"] = hashlib.sha256(raw).hexdigest()
            (base / "state.json").write_text(json.dumps(state), encoding="utf-8")
            state["project_id"] = "TAMPERED"
            (base / "state.json").write_text(json.dumps(state), encoding="utf-8")
            result = assess_run_base(base, now=NOW, completion_obligations={"EDP_ALL_PASS": True})
            self.assertEqual(result.disposition, CONTINUE_EXECUTION)
            self.assertFalse(result.allow_final_response)

    def test_exit_guard_negative_space_has_no_orchestration_authority(self) -> None:
        source = Path("runtime/orchestrator/operator_exit_guard.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_calls = {"route_request", "resume_wait", "resume_recoverable_block", "execute_gate", "run_job", "execute_provider_task"}
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    seen.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    seen.add(node.func.attr)
        self.assertFalse(forbidden_calls.intersection(seen))
        self.assertNotIn("runtime.mprf", source)
        self.assertNotIn("full_mcp", source)

    def test_guard_has_no_control_authority(self) -> None:
        result = assess_operator_turn_exit(full_plan_state(), now=NOW, completion_obligations={})
        self.assertEqual(result.control_authority, "NONE")


if __name__ == "__main__":
    unittest.main()
