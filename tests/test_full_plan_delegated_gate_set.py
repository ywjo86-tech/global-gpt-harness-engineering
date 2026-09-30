import hashlib
import json
import unittest
from datetime import datetime, timezone

from runtime.orchestrator.full_plan_delegated_gate_set import (
    DelegatedGateSetError, validate_delegated_gate_set,
)
from runtime.orchestrator.full_plan_owner_delegation import validate_owner_delegation


SCOPE = {"schema_version": "orchestration.full-plan-owner-delegation.v1",
         "decision_id": "D-1", "project_id": "P-1", "plan_sha256": "a" * 64,
         "spec_sha256": "b" * 64, "source_head": "c" * 40,
         "runtime_sha256": "d" * 64, "gate_ids": ["G-1", "G-2"],
         "issued_at": "2026-09-30T00:00:00Z", "expires_at": "2026-10-01T00:00:00Z",
         "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"]}
SCOPE_DIGEST = hashlib.sha256(json.dumps(SCOPE, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def row(gate):
    return {"gate_id": gate, "decision_id": "D-1", "project_id": "P-1",
            "plan_sha256": "a" * 64, "spec_sha256": "b" * 64,
            "source_head": "c" * 40, "runtime_sha256": "d" * 64,
            "owner_comment_id": 123, "scope_sha256": SCOPE_DIGEST}


class DelegatedGateSetTests(unittest.TestCase):
    def verified(self):
        body = "OCP_FULL_PLAN_OWNER_DELEGATION_V1\n" + json.dumps(
            SCOPE, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return validate_owner_delegation(
            {"id": 123, "user": {"id": 456}, "body": body,
             "created_at": "2026-09-30T00:00:00Z", "updated_at": "2026-09-30T00:00:00Z",
             "performed_via_github_app": None},
            owner_actor_id="456", expected_comment_id=123, expected_scope=SCOPE,
            now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc))

    def test_two_gates_share_one_exact_root_decision(self):
        self.assertEqual(validate_delegated_gate_set(self.verified(), SCOPE, [row("G-1"), row("G-2")]), "D-1")

    def test_missing_or_duplicate_gate_is_rejected(self):
        for rows in ([row("G-1")], [row("G-1"), row("G-1")]):
            with self.subTest(rows=rows), self.assertRaises(DelegatedGateSetError):
                validate_delegated_gate_set(self.verified(), SCOPE, rows)

    def test_spec_or_root_reference_drift_is_rejected(self):
        for change in ({"spec_sha256": "f" * 64}, {"owner_comment_id": 124},
                       {"scope_sha256": "f" * 64}):
            with self.subTest(change=change), self.assertRaises(DelegatedGateSetError):
                validate_delegated_gate_set(self.verified(), SCOPE, [row("G-1"), {**row("G-2"), **change}])

    def test_runtime_and_source_drift_is_rejected(self):
        for change in ({"runtime_sha256": "f" * 64}, {"source_head": "f" * 40}):
            with self.subTest(change=change), self.assertRaises(DelegatedGateSetError):
                validate_delegated_gate_set(self.verified(), SCOPE, [row("G-1"), {**row("G-2"), **change}])


if __name__ == "__main__":
    unittest.main()
