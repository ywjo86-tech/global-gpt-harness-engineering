import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.full_plan_owner_attestation import OwnerAttestationError, verify_owner_attestation


class OwnerAttestationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        private = root / "issuer.key"
        self.public = root / "issuer.pub"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True)
        subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(self.public)], check=True)
        self.private = private
        self.key_sha = hashlib.sha256(self.public.read_bytes()).hexdigest()
        self.scope = {
            "schema_version": "orchestration.full-plan-owner-delegation.v1",
            "decision_id": "APPROVAL-1", "project_id": "PROJECT-1",
            "plan_sha256": "a" * 64, "spec_sha256": "b" * 64,
            "source_head": "c" * 40, "runtime_sha256": "d" * 64,
            "gate_ids": ["GATE-001", "GATE-002"],
            "issued_at": "2026-09-30T00:00:00Z",
            "expires_at": "2026-10-01T00:00:00Z",
            "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
        }
        self.payload = {
            "schema_version": "orchestration.full-plan-owner-attestation.v1",
            "issuer": "trusted-mcp-issuer", "audience": "ocpv2-full-plan",
            "decision_id": "APPROVAL-1", "owner_actor_id": "235775273",
            "confirmation_id": "CONFIRM-1", "scope": self.scope,
            "issued_at": "2026-09-30T01:00:00Z",
            "expires_at": "2026-09-30T23:00:00Z",
        }

    def signed(self, payload=None):
        payload = self.payload if payload is None else payload
        root = Path(self.tmp.name)
        data = root / "input.json"
        sig = root / "input.sig"
        data.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode())
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(self.private),
                        "-rawin", "-in", str(data), "-out", str(sig)], check=True)
        return {"payload": payload,
                "signature": base64.urlsafe_b64encode(sig.read_bytes()).rstrip(b"=").decode()}

    def verify(self, envelope, **overrides):
        args = dict(public_key_path=self.public, public_key_sha256=self.key_sha,
                    expected_issuer="trusted-mcp-issuer", expected_audience="ocpv2-full-plan",
                    expected_owner_actor_id="235775273",
                    now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
        args.update(overrides)
        return verify_owner_attestation(envelope, **args)

    def test_verified_scope_and_identity(self):
        verified = self.verify(self.signed())
        self.assertEqual(verified.gate_ids, ("GATE-001", "GATE-002"))
        self.assertEqual(verified.owner_actor_id, "235775273")

    def test_operator_claim_cannot_replace_signature(self):
        forged = self.signed()
        forged["payload"] = {**self.payload, "owner_actor_id": "987"}
        with self.assertRaises(OwnerAttestationError):
            self.verify(forged)
        unsigned = {**forged, "signature": "A" * 86}
        with self.assertRaises(OwnerAttestationError):
            self.verify(unsigned)

    def test_scope_expansion_and_wrong_key_are_rejected(self):
        forged = self.signed()
        forged["payload"] = {**self.payload, "scope": {**self.scope,
                             "gate_ids": ["GATE-001", "GATE-002", "GATE-003"]}}
        with self.assertRaises(OwnerAttestationError):
            self.verify(forged)
        with self.assertRaises(OwnerAttestationError):
            self.verify(self.signed(), public_key_sha256="0" * 64)

    def test_expiry_and_wrong_audience_are_rejected(self):
        with self.assertRaises(OwnerAttestationError):
            self.verify(self.signed(), now=datetime(2026, 10, 1, tzinfo=timezone.utc))
        with self.assertRaises(OwnerAttestationError):
            self.verify(self.signed(), expected_audience="other")


if __name__ == "__main__":
    unittest.main()
