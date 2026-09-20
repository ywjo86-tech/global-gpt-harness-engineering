from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from runtime.orchestrator.user_interaction_policy import (
    ApprovalCoverageEvidence,
    classify_continuation_directive,
    evaluate_attention_delivery,
    evaluate_user_decision,
)


UTC = timezone.utc


def coverage(*, risks=("general",), operations=("PROJECT_WRITE",)) -> ApprovalCoverageEvidence:
    digest = "a" * 64
    return ApprovalCoverageEvidence(
        approval_ref="approval://full-plan/1",
        approved_semantic_digest=digest,
        reviewed_semantic_digest=digest,
        allowed_risk_classes=tuple(risks),
        allowed_operations=tuple(operations),
    )


class UserDecisionPolicyTests(unittest.TestCase):

    def test_progress_word_promotes_approved_unregistered_harness_work(self) -> None:
        out = classify_continuation_directive(
            "진행", approved_scope_active=True, durable_job_registered=False,
            material_contract_change=False,
        )
        self.assertEqual(out.action, "PROMOTE_TO_FULL_PLAN")

    def test_progress_word_resumes_registered_full_plan(self) -> None:
        out = classify_continuation_directive(
            "이어서 진행", approved_scope_active=True, durable_job_registered=True,
            material_contract_change=False,
        )
        self.assertEqual(out.action, "RESUME_FULL_PLAN")

    def test_continuation_never_broadens_or_replaces_approval(self) -> None:
        revision = classify_continuation_directive(
            "continue", approved_scope_active=True, durable_job_registered=True,
            material_contract_change=True,
        )
        no_scope = classify_continuation_directive(
            "resume", approved_scope_active=False, durable_job_registered=False,
            material_contract_change=False,
        )
        arbitrary = classify_continuation_directive(
            "새 기능을 추가해", approved_scope_active=True, durable_job_registered=True,
            material_contract_change=False,
        )
        self.assertEqual(revision.action, "REQUIRE_PLAN_REVISION")
        self.assertEqual(no_scope.action, "NO_CONTINUATION")
        self.assertEqual(arbitrary.action, "NO_CONTINUATION")

    def test_missing_approval_requires_initial_decision(self) -> None:
        out = evaluate_user_decision(
            approval_coverage=None, material_contract_change=False,
            requested_risk_class="general", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=False,
        )
        self.assertTrue(out.required)
        self.assertEqual(out.decision_type, "INITIAL_EXECUTION_APPROVAL")

    def test_material_change_and_risk_escalation_require_decision(self) -> None:
        material = evaluate_user_decision(
            approval_coverage=coverage(), material_contract_change=True,
            requested_risk_class="general", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=False,
        )
        self.assertEqual(material.decision_type, "PLAN_REVISION_REQUIRED")
        escalated = evaluate_user_decision(
            approval_coverage=coverage(), material_contract_change=False,
            requested_risk_class="dangerous", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=False,
        )
        self.assertEqual(escalated.decision_type, "RISK_ESCALATION")

    def test_dangerous_reexecution_requires_safe_effect_evidence(self) -> None:
        approved = coverage(risks=("dangerous",))
        blocked = evaluate_user_decision(
            approval_coverage=approved, material_contract_change=False,
            requested_risk_class="dangerous", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=True, effect_reconciliation="AMBIGUOUS",
        )
        self.assertEqual(blocked.decision_type, "AMBIGUOUS_DANGEROUS_EFFECT")
        safe = evaluate_user_decision(
            approval_coverage=approved, material_contract_change=False,
            requested_risk_class="dangerous", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=True, effect_reconciliation="NO_EFFECT",
        )
        self.assertFalse(safe.required)
        self.assertEqual(safe.decision_type, "NONE")

    def test_stale_approval_digest_requires_plan_revision(self) -> None:
        stale = ApprovalCoverageEvidence(
            approval_ref="approval://full-plan/1",
            approved_semantic_digest="a" * 64,
            reviewed_semantic_digest="b" * 64,
            allowed_risk_classes=("general",),
            allowed_operations=("PROJECT_WRITE",),
        )
        out = evaluate_user_decision(
            approval_coverage=stale, material_contract_change=False,
            requested_risk_class="general", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=False,
        )
        self.assertTrue(out.required)
        self.assertEqual(out.decision_type, "PLAN_REVISION_REQUIRED")

    def test_same_scope_recovery_needs_no_new_decision(self) -> None:
        out = evaluate_user_decision(
            approval_coverage=coverage(), material_contract_change=False,
            requested_risk_class="general", requested_operation="PROJECT_WRITE",
            dangerous_reexecution=False,
        )
        self.assertFalse(out.required)
        self.assertEqual(out.decision_type, "NONE")

    def test_immediate_decision_attention_bypasses_delay(self) -> None:
        now = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
        event = {"kind": "WAITING_APPROVAL", "delivery_class": "IMMEDIATE_DECISION",
                 "created_at": now.isoformat(), "reason": "approval required"}
        state = {"state": "WAITING_APPROVAL", "last_error": "approval required",
                 "last_semantic_progress_at": now.isoformat()}
        out = evaluate_attention_delivery(event, state, now=now)
        self.assertTrue(out.eligible)
        self.assertEqual(out.delivery_class, "IMMEDIATE_DECISION")

    def test_deferred_incident_waits_300_seconds(self) -> None:
        created = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
        event = {"kind": "WAITING_PROVIDER", "delivery_class": "DEFERRED_INCIDENT",
                 "created_at": created.isoformat(), "reason": "provider timeout"}
        state = {"state": "WAITING_PROVIDER", "last_error": "provider timeout",
                 "last_semantic_progress_at": created.isoformat()}
        early = evaluate_attention_delivery(event, state, now=created + timedelta(seconds=299))
        late = evaluate_attention_delivery(event, state, now=created + timedelta(seconds=300))
        self.assertFalse(early.eligible)
        self.assertTrue(late.eligible)

    def test_semantic_progress_resets_effective_notification_timer(self) -> None:
        created = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
        progressed = created + timedelta(seconds=240)
        event = {"kind": "WAITING_PROVIDER", "delivery_class": "DEFERRED_INCIDENT",
                 "created_at": created.isoformat(), "reason": "provider timeout"}
        state = {"state": "WAITING_PROVIDER", "last_error": "provider timeout",
                 "last_semantic_progress_at": progressed.isoformat()}
        before = evaluate_attention_delivery(event, state, now=created + timedelta(seconds=500))
        after = evaluate_attention_delivery(event, state, now=created + timedelta(seconds=540))
        self.assertFalse(before.eligible)
        self.assertTrue(after.eligible)

    def test_recovered_or_completed_incident_is_suppressed(self) -> None:
        created = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
        event = {"kind": "WAITING_PROVIDER", "delivery_class": "DEFERRED_INCIDENT",
                 "created_at": created.isoformat(), "reason": "provider timeout"}
        recovered = {"state": "RECOVERING", "last_error": None,
                     "last_semantic_progress_at": (created + timedelta(seconds=50)).isoformat()}
        completed = {"state": "COMPLETED", "last_error": None,
                     "last_semantic_progress_at": (created + timedelta(seconds=50)).isoformat()}
        now = created + timedelta(seconds=1000)
        self.assertFalse(evaluate_attention_delivery(event, recovered, now=now).eligible)
        self.assertFalse(evaluate_attention_delivery(event, completed, now=now).eligible)

    def test_historical_event_infers_r2_delivery_class(self) -> None:
        created = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
        provider = {"kind": "WAITING_PROVIDER", "created_at": created.isoformat(),
                    "reason": "provider timeout"}
        approval = {"kind": "WAITING_APPROVAL", "created_at": created.isoformat(),
                    "reason": "approval required"}
        state_provider = {"state": "WAITING_PROVIDER", "last_error": "provider timeout",
                          "last_semantic_progress_at": created.isoformat()}
        state_approval = {"state": "WAITING_APPROVAL", "last_error": "approval required",
                          "last_semantic_progress_at": created.isoformat()}
        self.assertFalse(evaluate_attention_delivery(
            provider, state_provider, now=created + timedelta(seconds=10)).eligible)
        self.assertTrue(evaluate_attention_delivery(
            approval, state_approval, now=created + timedelta(seconds=10)).eligible)

    def test_stall_confirmed_is_immediate_but_terminal_state_suppresses(self) -> None:
        now = datetime(2026, 9, 19, 8, 5, tzinfo=UTC)
        event = {"kind": "STALLED_SUSPECTED", "delivery_class": "STALL_CONFIRMED",
                 "created_at": now.isoformat(), "reason": "NO_SEMANTIC_PROGRESS"}
        running = {"state": "RUNNING", "last_error": None,
                   "last_semantic_progress_at": (now - timedelta(seconds=300)).isoformat()}
        cancelled = {"state": "CANCELLED", "last_error": None,
                     "last_semantic_progress_at": running["last_semantic_progress_at"]}
        self.assertTrue(evaluate_attention_delivery(event, running, now=now).eligible)
        self.assertFalse(evaluate_attention_delivery(event, cancelled, now=now).eligible)


    def test_recovered_stall_and_resolved_decision_are_suppressed(self) -> None:
        created = datetime(2026, 9, 19, 8, 5, tzinfo=UTC)
        stall = {"kind":"STALLED_SUSPECTED","delivery_class":"STALL_CONFIRMED",
                 "created_at":created.isoformat(),"reason":"NO_SEMANTIC_PROGRESS"}
        recovered = {"state":"RUNNING","last_error":None,
                     "last_semantic_progress_at":(created + timedelta(seconds=10)).isoformat()}
        self.assertFalse(evaluate_attention_delivery(stall, recovered, now=created + timedelta(seconds=20)).eligible)
        decision = {"kind":"WAITING_APPROVAL","delivery_class":"IMMEDIATE_DECISION",
                    "created_at":created.isoformat(),"reason":"approval required"}
        resumed = {"state":"RECOVERING","last_error":None,
                   "last_semantic_progress_at":(created + timedelta(seconds=5)).isoformat()}
        self.assertFalse(evaluate_attention_delivery(decision, resumed, now=created + timedelta(seconds=6)).eligible)


if __name__ == "__main__":
    unittest.main()
