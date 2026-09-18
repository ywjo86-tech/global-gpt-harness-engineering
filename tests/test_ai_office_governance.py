from __future__ import annotations

import unittest

from runtime.ai_office.governance import (
    HUMAN_APPROVAL_SCHEMA_V1,
    RISK_ENVELOPE_SCHEMA_V1,
    HumanApprovalV1,
    RiskEnvelopeV1,
    build_activation_gate,
    evaluate_governance,
)

APPROVAL_DIGEST = "a" * 64


class AIOfficeGovernanceTest(unittest.TestCase):
    def risk(self, *, requested="scope:approved", allowed="scope:approved", risk_class="HIGH"):
        return RiskEnvelopeV1(
            RISK_ENVELOPE_SCHEMA_V1,
            "action:fixture",
            requested,
            allowed,
            risk_class,
            ("permission:filesystem",),
        )

    def approval(self, *, scope="scope:approved", digest=APPROVAL_DIGEST, start=100, end=200):
        return HumanApprovalV1(
            HUMAN_APPROVAL_SCHEMA_V1,
            "approval:user-001",
            digest,
            scope,
            start,
            end,
        )
    def test_020_scope_expansion_and_permission_mismatch_fail_closed(self) -> None:
        expanded = self.risk(requested="scope:expanded", allowed="scope:approved")
        decision = evaluate_governance(
            expanded,
            permission_allow=True,
            approval=self.approval(scope="scope:expanded"),
            expected_approval_digest=APPROVAL_DIGEST,
            now_epoch=150,
        )
        self.assertEqual(decision.decision, "BLOCK")
        denied = evaluate_governance(
            self.risk(), permission_allow=False, approval=self.approval(),
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(denied.decision, "BLOCK")

    def test_021_activation_requires_policy_allow_and_fresh_human_approval(self) -> None:
        approval = self.approval()
        decision = evaluate_governance(
            self.risk(), permission_allow=True, approval=approval,
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(decision.decision, "ALLOW")
        gate = build_activation_gate(
            activation_scope="PRODUCTION", governance=decision, approval=approval,
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(gate.status, "GO")
    def test_021_recovery_context_does_not_bypass_missing_approval(self) -> None:
        decision = evaluate_governance(
            self.risk(), permission_allow=True, approval=None,
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(decision.decision, "APPROVAL_REQUIRED")
        gate = build_activation_gate(
            activation_scope="PILOT", governance=decision, approval=None,
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(gate.status, "BLOCKED")

    def test_022_stale_or_replayed_approval_digest_fails_closed(self) -> None:
        stale = self.approval(start=10, end=20)
        stale_decision = evaluate_governance(
            self.risk(), permission_allow=True, approval=stale,
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(stale_decision.decision, "APPROVAL_REQUIRED")
        mismatched = self.approval(digest="b" * 64)
        replay_decision = evaluate_governance(
            self.risk(), permission_allow=True, approval=mismatched,
            expected_approval_digest=APPROVAL_DIGEST, now_epoch=150,
        )
        self.assertEqual(replay_decision.decision, "APPROVAL_REQUIRED")


if __name__ == "__main__":
    unittest.main()
