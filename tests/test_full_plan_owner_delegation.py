import hashlib
import json
import unittest
from datetime import datetime, timezone

from runtime.orchestrator.full_plan_owner_delegation import (
    DelegationError, validate_owner_delegation, bind_delegation_to_activation,
    bind_delegation_to_gate,
)


SCOPE = {
    "schema_version": "orchestration.full-plan-owner-delegation.v1",
    "decision_id": "DECISION-1", "project_id": "PROJECT-1",
    "plan_sha256": "a" * 64, "spec_sha256": "b" * 64,
    "gate_ids": ["GATE-001", "GATE-002"],
    "source_head": "c" * 40, "runtime_sha256": "d" * 64,
    "issued_at": "2026-09-30T00:00:00Z", "expires_at": "2026-10-01T00:00:00Z",
    "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
}


def comment(scope=SCOPE):
    body = "OCP_FULL_PLAN_OWNER_DELEGATION_V1\n" + json.dumps(
        scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"id": 123, "user": {"id": 235775273}, "body": body,
            "created_at": "2026-09-30T00:00:00Z", "updated_at": "2026-09-30T00:00:00Z",
            "performed_via_github_app": None}


class OwnerDelegationTests(unittest.TestCase):
    def check(self, observed, scope=SCOPE):
        return validate_owner_delegation(
            observed, owner_actor_id="235775273", expected_comment_id=123,
            expected_scope=scope, now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc))

    def test_exact_owner_comment_binds_whole_plan_and_gate_order(self):
        result = self.check(comment())
        self.assertEqual(result.gate_ids, ("GATE-001", "GATE-002"))
        self.assertEqual(result.comment_id, 123)

    def test_operator_or_app_authored_comment_is_rejected(self):
        with self.assertRaises(DelegationError):
            self.check({**comment(), "user": {"id": 987}})
        with self.assertRaises(DelegationError):
            self.check({**comment(), "performed_via_github_app": {"slug": "operator"}})

    def test_edited_comment_and_scope_expansion_are_rejected(self):
        with self.assertRaises(DelegationError):
            self.check({**comment(), "updated_at": "2026-09-30T00:00:01Z"})
        wider = {**SCOPE, "gate_ids": ["GATE-001", "GATE-002", "GATE-003"]}
        with self.assertRaises(DelegationError):
            self.check(comment(), scope=wider)

    def test_expired_scope_is_rejected(self):
        expired = {**SCOPE, "expires_at": "2026-09-30T01:00:00Z"}
        with self.assertRaises(DelegationError):
            self.check(comment(expired), scope=expired)

    def test_protected_action_exclusion_cannot_be_removed(self):
        weaker = {**SCOPE, "excluded_actions": ["PR_MERGE"]}
        with self.assertRaises(DelegationError):
            self.check(comment(weaker), scope=weaker)

    def test_activation_must_match_entire_ordered_gate_scope(self):
        activation = {
            "approved_plan": {"sha256": "a" * 64},
            "approved_spec": {"sha256": "b" * 64},
            "expected_head": "c" * 40,
            "runtime_release_digest": "d" * 64,
            "gate_bindings": [{"gate_id": "GATE-001"}, {"gate_id": "GATE-002"}],
        }
        verified = self.check(comment())
        self.assertEqual(bind_delegation_to_activation(verified, SCOPE, activation), ("GATE-001", "GATE-002"))
        with self.assertRaises(DelegationError):
            bind_delegation_to_activation(verified, SCOPE, {**activation, "gate_bindings": [{"gate_id": "GATE-001"}]})
        with self.assertRaises(DelegationError):
            bind_delegation_to_activation(verified, SCOPE, {**activation, "approved_spec": {"sha256": "e" * 64}})
        with self.assertRaises(DelegationError):
            bind_delegation_to_activation(verified, SCOPE, {**activation, "expected_head": "f" * 40})
        with self.assertRaises(DelegationError):
            bind_delegation_to_activation(verified, {**SCOPE, "decision_id": "OTHER"}, activation)

    def test_same_owner_decision_covers_two_exact_gate_preflights(self):
        verified = self.check(comment())
        activation = {
            "approved_plan": {"sha256": "a" * 64},
            "approved_spec": {"sha256": "b" * 64},
            "expected_branch": "main", "expected_head": "c" * 40,
            "runtime_release_digest": "d" * 64, "approval_ref": "DECISION-1",
            "gate_bindings": [{"gate_id": "GATE-001"}, {"gate_id": "GATE-002"}],
        }
        evidence = {"project_id": "PROJECT-1", "plan_sha256": "a" * 64,
                    "branch": "main", "head": "c" * 40}
        for gate in ("GATE-001", "GATE-002"):
            request = {"gate_id": gate, "expected_branch": "main",
                       "expected_head": "c" * 40, "approval_ref": "DECISION-1"}
            self.assertEqual(bind_delegation_to_gate(
                verified, SCOPE, activation, request, evidence,
                serving_runtime_digest="d" * 64), gate)
        with self.assertRaises(DelegationError):
            bind_delegation_to_gate(verified, SCOPE, activation,
                                    {**request, "gate_id": "GATE-003"}, evidence,
                                    serving_runtime_digest="d" * 64)
        with self.assertRaises(DelegationError):
            bind_delegation_to_gate(verified, SCOPE, activation,
                                    request, evidence, serving_runtime_digest="e" * 64)
        with self.assertRaises(DelegationError):
            bind_delegation_to_gate(verified, SCOPE, activation,
                                    {**request, "approval_ref": "OTHER"}, evidence,
                                    serving_runtime_digest="d" * 64)
        with self.assertRaises(DelegationError):
            bind_delegation_to_gate(verified, SCOPE, activation,
                                    request, {**evidence, "head": "f" * 40},
                                    serving_runtime_digest="d" * 64)


if __name__ == "__main__":
    unittest.main()
