from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.gate_approval import (
    GateApprovalError, derive_system_transition, load_approval_evidence,
    seal_approval_evidence, validate_approval_evidence,
)


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
SHA_R = "a" * 64
SHA_P = "b" * 64
HEAD = "c" * 40
ORDER = ["G1-LV3-1", "G1-LV3-2"]
OWNED = {"G1-LV3-1": ["app/a.py"], "G1-LV3-2": ["app/b.py"]}


def payload(**changes):
    value = {
        "schema_version": "orchestration.gate-approval.v1", "approval_id": "APR-G1-1",
        "project_id": "wallet-affiliate-collector", "gate_id": "GATE-1",
        "requirements_sha256": SHA_R, "plan_sha256": SHA_P, "branch": "main", "head": HEAD,
        "scope": {"lv_order": ORDER, "owned_files_by_lv": OWNED},
        "issued_at": "2026-08-28T00:00:00Z", "expires_at": "2026-08-29T00:00:00Z", "status": "ACTIVE",
    }
    value.update(changes)
    return value


def validate(envelope, **changes):
    args = dict(project_id="wallet-affiliate-collector", gate_id="GATE-1", requirements_sha256=SHA_R,
                plan_sha256=SHA_P, branch="main", head=HEAD, lv_order=ORDER,
                owned_files_by_lv=OWNED, now=NOW)
    args.update(changes)
    return validate_approval_evidence(envelope, **args)


class GateApprovalTests(unittest.TestCase):
    def test_persisted_evidence_loads_and_validates_exactly(self):
        envelope = seal_approval_evidence(payload())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            self.assertEqual(validate(load_approval_evidence(path))["approval_id"], "APR-G1-1")

    def test_tamper_is_blocked(self):
        envelope = seal_approval_evidence(payload()); envelope["payload"]["gate_id"] = "GATE-2"
        with self.assertRaisesRegex(GateApprovalError, "hash mismatch"): validate(envelope)

    def test_expired_and_future_issued_are_blocked(self):
        with self.assertRaisesRegex(GateApprovalError, "expired"):
            validate(seal_approval_evidence(payload(expires_at="2026-08-28T11:59:59Z")))
        with self.assertRaisesRegex(GateApprovalError, "stale"):
            validate(seal_approval_evidence(payload(issued_at="2026-08-28T12:00:01Z", expires_at="2026-08-29T00:00:00Z")))

    def test_inactive_status_is_blocked(self):
        with self.assertRaisesRegex(GateApprovalError, "not ACTIVE"):
            seal_approval_evidence(payload(status="REVOKED"))

    def test_wrong_gate_and_cross_project_are_blocked(self):
        envelope = seal_approval_evidence(payload())
        with self.assertRaisesRegex(GateApprovalError, "gate_id binding mismatch"): validate(envelope, gate_id="GATE-2")
        with self.assertRaisesRegex(GateApprovalError, "project_id binding mismatch"): validate(envelope, project_id="other")

    def test_requirements_plan_branch_head_and_scope_staleness_are_blocked(self):
        envelope = seal_approval_evidence(payload())
        cases = ({"requirements_sha256": "d"*64}, {"plan_sha256": "d"*64}, {"branch": "feature"},
                 {"head": "d"*40}, {"lv_order": list(reversed(ORDER))},
                 {"owned_files_by_lv": {"G1-LV3-1": ["other.py"], "G1-LV3-2": ["app/b.py"]}})
        for case in cases:
            with self.subTest(case=case), self.assertRaises(GateApprovalError): validate(envelope, **case)

    def test_exact_schema_rejects_extra_fields(self):
        value = payload(); value["authorization"] = "forged"
        with self.assertRaisesRegex(GateApprovalError, "schema mismatch"): seal_approval_evidence(value)

    def test_system_transition_is_bounded_and_not_approval_reuse(self):
        approved = validate(seal_approval_evidence(payload()))
        authority = derive_system_transition(approved, lv_id="G1-LV3-2")
        self.assertEqual(authority["authority_type"], "SYSTEM_TRANSITION")
        self.assertEqual(authority["owned_files"], ["app/b.py"])
        self.assertNotEqual(authority["schema_version"], approved["schema_version"])
        self.assertFalse(authority["user_approval_renewal"])

    def test_next_gate_lv_is_blocked(self):
        approved = validate(seal_approval_evidence(payload()))
        with self.assertRaisesRegex(GateApprovalError, "next Gate is blocked"):
            derive_system_transition(approved, lv_id="G2-LV3-1")

    def test_symlink_evidence_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); target = root / "target.json"; target.write_text("{}")
            link = root / "approval.json"; link.symlink_to(target)
            with self.assertRaisesRegex(GateApprovalError, "unsafe"): load_approval_evidence(link)


if __name__ == "__main__": unittest.main()
