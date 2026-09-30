import hashlib
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.full_plan_approval_issuer import (
    ApprovalIssuerError, FullPlanApprovalIssuer,
)
from runtime.orchestrator.full_plan_owner_attestation import (
    OwnerAttestationError, verify_owner_attestation, verify_owner_status,
)


def stamp(value):
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ApprovalIssuerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.private, self.public = root / "private.pem", root / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519",
                        "-out", str(self.private)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.private), "-pubout",
                        "-out", str(self.public)], check=True, capture_output=True)
        self.issuer = FullPlanApprovalIssuer(
            database=root / "decisions.db", private_key=self.private,
            owner_user_id="site-owner-1", owner_actor_id="235775273",
            issuer="trusted-mcp-issuer", audience="ocpv2-full-plan")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.scope = {
            "schema_version": "orchestration.full-plan-owner-delegation.v1",
            "decision_id": "DECISION-1", "project_id": "PROJECT-1",
            "plan_sha256": "a" * 64, "spec_sha256": "b" * 64,
            "gate_ids": ["GATE-001", "GATE-002"],
            "source_head": "c" * 40, "runtime_sha256": "d" * 64,
            "issued_at": stamp(self.now - timedelta(minutes=1)),
            "expires_at": stamp(self.now + timedelta(hours=1)),
            "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
        }

    def issue(self, **overrides):
        arguments = dict(scope=self.scope, authenticated_user_id="site-owner-1",
                         trusted_confirmation_id="CONFIRM-1", now=self.now)
        arguments.update(overrides)
        return self.issuer.issue(**arguments)

    def test_signed_issue_replay_binding_and_revocation(self):
        envelope = self.issue()
        verified = verify_owner_attestation(
            envelope, public_key_path=self.public,
            public_key_sha256=hashlib.sha256(self.public.read_bytes()).hexdigest(),
            expected_issuer="trusted-mcp-issuer", expected_audience="ocpv2-full-plan",
            expected_owner_actor_id="235775273", now=self.now)
        self.assertEqual(verified.decision_id, "DECISION-1")
        with self.assertRaisesRegex(ApprovalIssuerError, "DECISION_OR_CONFIRMATION_REPLAY"):
            self.issue()
        with self.assertRaisesRegex(ApprovalIssuerError, "DECISION_OR_CONFIRMATION_REPLAY"):
            self.issue(scope={**self.scope, "decision_id": "DECISION-2"})
        challenge = "fresh-challenge-" + "x" * 32
        active = self.issuer.status(decision_id="DECISION-1", activation_id="ACT-1",
                                    challenge=challenge, now=self.now)
        self.assertTrue(active["payload"]["active"])
        status_args = dict(
            public_key_path=self.public,
            public_key_sha256=hashlib.sha256(self.public.read_bytes()).hexdigest(),
            expected_issuer="trusted-mcp-issuer", expected_audience="ocpv2-full-plan",
            expected_decision_id="DECISION-1", expected_scope_sha256=verified.scope_sha256,
            expected_activation_id="ACT-1", expected_challenge=challenge, now=self.now)
        verify_owner_status(active, **status_args)
        with self.assertRaises(OwnerAttestationError):
            verify_owner_status(active, **{**status_args, "expected_challenge": "other"})
        other = self.issuer.status(decision_id="DECISION-1", activation_id="ACT-2",
                                   challenge=challenge, now=self.now)
        self.assertFalse(other["payload"]["active"])
        with self.assertRaises(OwnerAttestationError):
            verify_owner_status(other, **{**status_args, "expected_activation_id": "ACT-2"})
        with self.assertRaisesRegex(ApprovalIssuerError, "OWNER_AUTH_REQUIRED"):
            self.issuer.revoke(decision_id="DECISION-1", authenticated_user_id="other")
        self.issuer.revoke(decision_id="DECISION-1",
                           authenticated_user_id="site-owner-1")
        revoked = self.issuer.status(decision_id="DECISION-1", activation_id="ACT-1",
                                     challenge=challenge, now=self.now)
        self.assertFalse(revoked["payload"]["active"])
        with self.assertRaises(OwnerAttestationError):
            verify_owner_status(revoked, **status_args)

    def test_untrusted_identity_and_widened_scope_rejected(self):
        with self.assertRaisesRegex(ApprovalIssuerError, "OWNER_AUTH_REQUIRED"):
            self.issue(authenticated_user_id="operator")
        with self.assertRaisesRegex(ApprovalIssuerError, "SCOPE_INVALID"):
            self.issue(scope={**self.scope, "excluded_actions": []})
        with self.assertRaisesRegex(ApprovalIssuerError, "SCOPE_INVALID"):
            self.issue(scope={**self.scope, "gate_ids": ["GATE-001", "GATE-001"]})


if __name__ == "__main__":
    unittest.main()
