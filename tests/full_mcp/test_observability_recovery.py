from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.tool_authorization import OperationIdentity, ToolEffectJournal
from runtime.full_mcp.observability import ObservabilityError, ObservabilityStore
from runtime.full_mcp.recovery import classify_recovery

SHA="a"*64


def identity()->OperationIdentity:
    return OperationIdentity(operation_registration_id="REG-1",operation_dispatch_id="DISP-1",operation_callsite_id="CALL-1",
        operation_class_id="FILE_WRITE",worker_task_id="TASK-X",worker_action_id="ACT-1",project_id="P",gate_id="G",lv_id="L",run_id="R",
        plan_digest=SHA,requirement_digest=SHA,package_digest=SHA,owned_scope_sha256=SHA)


class ObservabilityTests(unittest.TestCase):
    def setUp(self)->None:
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.store=ObservabilityStore(self.root,"run-1")
    def tearDown(self)->None:self.temp.cleanup()

    def test_correlated_utc_append_only_events_and_secret_safe_fields(self)->None:
        first=self.store.append_event(operation_request_id="op-1",correlation_id="corr-1",operation="read",state="RUNNING")
        second=self.store.append_event(operation_request_id="op-1",correlation_id="corr-1",operation="read",state="RESULT_SEALED",result_digest="b"*64)
        other=self.store.append_event(operation_request_id="op-2",correlation_id="corr-2",operation="read",state="RUNNING")
        self.assertEqual((first["sequence"],second["sequence"],other["sequence"]),(1,2,1)); self.assertTrue(first["occurred_at_utc"].endswith("Z"))
        raw=self.store.events_path.read_text(); self.assertNotIn("stdout",raw); self.assertNotIn("runtime.full_mcp.",raw)
        with self.assertRaises(TypeError): self.store.append_event(operation_request_id="op-3",correlation_id="corr",operation="read",state="RUNNING",stdout="secret") # type: ignore[call-arg]

    def test_result_tracking_is_create_once_and_request_isolated(self)->None:
        a=self.store.seal_result(operation_request_id="op-a",correlation_id="ca",operation="read",state="COMPLETED",
            started_at="2026-01-01T00:00:00Z",ended_at="2026-01-01T00:00:01Z",audit_ref="events#a",exit_code=0)
        b=self.store.seal_result(operation_request_id="op-b",correlation_id="cb",operation="write",state="FAILED",
            started_at="2026-01-01T00:00:00Z",ended_at="2026-01-01T00:00:01Z",audit_ref="events#b",error_code="VALIDATION_FAILED")
        self.assertEqual(self.store.status("op-a")["state"],"COMPLETED"); self.assertEqual(self.store.status("op-b")["state"],"FAILED")
        self.assertNotEqual(a["result_digest"],b["result_digest"]); self.assertIsNone(self.store.status("missing"))
        with self.assertRaises(ObservabilityError): self.store.seal_result(operation_request_id="op-a",correlation_id="ca",operation="read",state="COMPLETED",
            started_at="x",ended_at="y",audit_ref="events#a")


class FailureRecoveryPrimitiveTests(unittest.TestCase):
    def test_ambiguous_effect_requires_recovery_and_never_auto_replays(self)->None:
        with tempfile.TemporaryDirectory() as td:
            journal=ToolEffectJournal(Path(td)); ident=identity(); journal.begin(ident,{"authorization_status":"AUTHORIZED"},scope_ref="owned/a")
            self.assertEqual(journal.recovery_state(ident),"BLOCKED_RECOVERY_AMBIGUOUS")
            decision=classify_recovery(error_code="INTERNAL_ERROR",effect_state=journal.recovery_state(ident),state_changing=True)
            self.assertEqual(decision.classification,"RECOVERY_REQUIRED"); self.assertFalse(decision.auto_retry_allowed); self.assertTrue(decision.requires_restore_or_remediation)

    def test_closed_recovery_taxonomy_distinguishes_policy_readonly_and_mutation(self)->None:
        blocked=classify_recovery(error_code="AUTHORIZATION_DENIED",effect_state="NOT_STARTED",state_changing=False)
        read_retry=classify_recovery(error_code="PROCESS_TIMEOUT",effect_state="NOT_STARTED",state_changing=False)
        write_fail=classify_recovery(error_code="PROCESS_TIMEOUT",effect_state="NOT_STARTED",state_changing=True)
        self.assertEqual(blocked.classification,"BLOCKED"); self.assertFalse(blocked.auto_retry_allowed)
        self.assertEqual(read_retry.classification,"RETRY_ELIGIBLE"); self.assertTrue(read_retry.auto_retry_allowed)
        self.assertEqual(write_fail.classification,"REMEDIATION_REQUIRED"); self.assertFalse(write_fail.auto_retry_allowed)
