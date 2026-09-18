from __future__ import annotations

import tempfile
import unittest

from runtime.ai_office.recovery_coordinator import (
    RECOVERY_STAGES,
    RecoveryCoordinationError,
    advance_recovery,
    begin_recovery,
    recovery_projection,
    rehydrate_pending_state,
)
from runtime.ai_office.state_store import AIOfficeStateStore


class AIOfficeRecoveryCoordinationTest(unittest.TestCase):
    def test_023_restart_preserves_pending_approval_and_manual_action_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AIOfficeStateStore(directory, project_id="PHASE5_AI_OFFICE_HARNESS_UPGRADE", run_id="recovery-run")
            store.initialize(approved_plan_ref="plan:approved", baseline_ref="baseline:approved")
            store.transition(
                to_state="WAITING_APPROVAL", reason_ref="reason:approval",
                pending_approval_ref="approval:pending-001",
            )
            store.transition(
                to_state="WAITING_STATE_CHANGE_AUTHORITY", reason_ref="reason:manual",
                pending_manual_action_ref="manual-action:pending-001",
            )
            restarted = AIOfficeStateStore(directory, project_id=store.project_id, run_id=store.run_id)
            restored = rehydrate_pending_state(restarted)
            self.assertEqual(restored["pending_approval_ref"], "approval:pending-001")
            self.assertEqual(restored["pending_manual_action_ref"], "manual-action:pending-001")
            self.assertEqual(restored["manual_action_refs"], ("manual-action:pending-001",))

    def test_024_recovery_requires_ordered_evidence_and_same_gate_reference(self) -> None:
        recovery = begin_recovery(
            recovery_id="recovery-001",
            failure_source_ref="failure:001",
            workflow_ref="workflow:001",
            same_gate_ref="GATE-004",
            approval_ref="approval:001",
            manual_action_ref="manual-action:001",
        )
        for stage in RECOVERY_STAGES[1:]:
            recovery = advance_recovery(recovery, next_stage=stage, evidence_ref=f"evidence:{stage.lower()}")
        self.assertEqual(recovery.stage, "SAME_GATE_REEVALUATION_READY")
        self.assertEqual(recovery.same_gate_ref, "GATE-004")
        projection = recovery_projection(recovery)
        self.assertFalse({"provider", "model", "action_replay", "gate_decision"}.intersection(projection))

    def test_024_recovery_stage_skip_or_evidence_replay_is_rejected(self) -> None:
        recovery = begin_recovery(
            recovery_id="recovery-002", failure_source_ref="failure:002",
            workflow_ref="workflow:002", same_gate_ref="GATE-004",
        )
        with self.assertRaises(RecoveryCoordinationError):
            advance_recovery(recovery, next_stage="REMEDIATED", evidence_ref="evidence:skip")
        diagnosed = advance_recovery(recovery, next_stage="DIAGNOSED", evidence_ref="evidence:diagnose")
        with self.assertRaises(RecoveryCoordinationError):
            advance_recovery(diagnosed, next_stage="REMEDIATED", evidence_ref="evidence:diagnose")


if __name__ == "__main__":
    unittest.main()
