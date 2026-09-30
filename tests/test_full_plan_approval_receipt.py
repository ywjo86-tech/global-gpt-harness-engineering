import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from runtime.orchestrator.full_plan_approval_receipt import ReceiptError, verify_receipt


KEY = b"test-only-independent-issuer-secret"
BASE = {
    "schema_version": "orchestration.full-plan-approval-receipt.v1",
    "issuer": "trusted-test-issuer", "subject": "owner-123", "decision_id": "decision-1",
    "decision": "APPROVED", "project_id": "project-1", "plan_sha256": "a" * 64,
    "spec_sha256": "b" * 64, "gate_ids": ["GATE-001"],
    "source_head": "c" * 40, "runtime_sha256": "d" * 64,
    "issued_at": "2026-09-30T00:00:00Z", "expires_at": "2026-10-01T00:00:00Z",
    "nonce": "nonce-1", "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
}


def signed(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {"payload": payload, "signature": hmac.new(KEY, encoded, hashlib.sha256).hexdigest()}


class ApprovalReceiptTests(unittest.TestCase):
    def check(self, receipt, *, key=KEY, gate="GATE-001", action="JOB_EXECUTE"):
        return verify_receipt(
            receipt, trust_key=key, issuer="trusted-test-issuer", subject="owner-123",
            project_id="project-1", plan_sha256="a" * 64, spec_sha256="b" * 64,
            gate_id=gate, source_head="c" * 40, runtime_sha256="d" * 64,
            action=action, now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
        )

    def test_exact_signed_scope_passes(self):
        self.assertEqual(self.check(signed(BASE)).decision_id, "decision-1")

    def test_no_trust_key_fails_closed(self):
        with self.assertRaises(ReceiptError):
            self.check(signed(BASE), key=None)

    def test_tampered_scope_fails(self):
        receipt = signed(BASE)
        receipt["payload"] = {**BASE, "gate_ids": ["GATE-001", "GATE-002"]}
        with self.assertRaises(ReceiptError):
            self.check(receipt)

    def test_unapproved_gate_fails(self):
        with self.assertRaises(ReceiptError):
            self.check(signed(BASE), gate="GATE-002")

    def test_expired_receipt_fails(self):
        expired = {**BASE, "expires_at": "2026-09-30T01:00:00Z"}
        with self.assertRaises(ReceiptError):
            self.check(signed(expired))

    def test_wrong_owner_fails(self):
        wrong_owner = {**BASE, "subject": "operator-456"}
        with self.assertRaises(ReceiptError):
            self.check(signed(wrong_owner))

    def test_protected_action_fails_even_with_valid_signature(self):
        with self.assertRaises(ReceiptError):
            self.check(signed(BASE), action="PR_MERGE")


if __name__ == "__main__":
    unittest.main()
