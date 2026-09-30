"""HTTP OAuth -> owner confirmation -> signed decision -> host status verification."""
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp_types import ElicitResult
from pydantic import AnyHttpUrl

from runtime.orchestrator.full_plan_approval_issuer import FullPlanApprovalIssuer, canonical
from runtime.orchestrator.full_plan_approval_mcp import create_approval_mcp
from runtime.orchestrator.full_plan_approval_status_app import create_status_app
from runtime.orchestrator.full_plan_owner_attestation import (
    OwnerAttestationError, verify_owner_attestation, verify_owner_status,
)

URL = "http://127.0.0.1:8000/mcp"
SCOPE = "ocp:full-plan-approve"


class Verifier:
    async def verify_token(self, token):
        subject = {"owner-token": "owner-1", "operator-token": "operator"}.get(token)
        if subject is None:
            return None
        return AccessToken(token=token, client_id="test-client", subject=subject,
                           scopes=[SCOPE], resource=URL)


def stamp(value):
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ConnectedApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.private, self.public = root / "private.pem", root / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out",
                        str(self.private)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.private), "-pubout", "-out",
                        str(self.public)], check=True, capture_output=True)
        self.issuer = FullPlanApprovalIssuer(
            database=root / "ledger.db", private_key=self.private,
            owner_user_id="owner-1", owner_actor_id="235775273",
            issuer="issuer-test", audience="ocpv2-test",
        )
        token = root / "host-token"
        token.write_text("z" * 48)
        token.chmod(0o600)
        self.status_app = create_status_app(issuer=self.issuer, token_file=token)
        self.server = create_approval_mcp(
            issuer=self.issuer, verifier=Verifier(),
            auth=AuthSettings(
                issuer_url=AnyHttpUrl("https://auth.example.com"),
                resource_server_url=AnyHttpUrl(URL),
                required_scopes=[SCOPE], validate_token_resource=True,
            ),
        )
        now = datetime.now(timezone.utc)
        self.scope = {
            "schema_version": "orchestration.full-plan-owner-delegation.v1",
            "decision_id": "DECISION-HTTP-1", "project_id": "DISPOSABLE-1",
            "plan_sha256": "a" * 64, "spec_sha256": "b" * 64,
            "gate_ids": ["GATE-1"], "source_head": "c" * 40,
            "runtime_sha256": "d" * 64,
            "issued_at": stamp(now - timedelta(minutes=1)),
            "expires_at": stamp(now + timedelta(hours=1)),
            "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
        }

    async def call(self, bearer, tool, arguments, callback=None):
        transport = httpx2.ASGITransport(app=self.server.streamable_http_app())
        async with self.server.session_manager.run():
            async with (
                httpx2.AsyncClient(transport=transport, base_url=URL,
                                   headers={"Authorization": "Bearer " + bearer}) as http_client,
                Client(streamable_http_client(URL, http_client=http_client),
                       elicitation_callback=callback) as client,
            ):
                return await client.call_tool(tool, arguments)

    def status(self, activation_id):
        challenge = "challenge-" + "x" * 40
        raw = canonical({"decision_id": self.scope["decision_id"],
                         "activation_id": activation_id, "challenge": challenge})
        environ = {"PATH_INFO": "/status", "REQUEST_METHOD": "POST",
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
                   "HTTP_AUTHORIZATION": "Bearer " + "z" * 48,
                   "wsgi.input": io.BytesIO(raw)}
        status = []
        data = b"".join(self.status_app(environ, lambda code, headers: status.append(code)))
        self.assertEqual(status, ["200 OK"])
        return json.loads(data), challenge

    async def test_owner_confirmation_to_signed_host_status_and_revocation(self):
        digest = hashlib.sha256(canonical(self.scope)).hexdigest()
        prompted = []

        async def confirm(context, params):
            prompted.append(params.message)
            return ElicitResult(action="accept", content={"scope_sha256": digest})

        rejected = await self.call("operator-token", "approve_full_plan",
                                   {"scope": self.scope}, confirm)
        self.assertTrue(rejected.is_error)
        self.assertEqual(prompted, [])

        issued = await self.call("owner-token", "approve_full_plan",
                                 {"scope": self.scope}, confirm)
        self.assertFalse(issued.is_error)
        self.assertEqual(len(prompted), 1)
        self.assertIn(digest, prompted[0])
        envelope = issued.structured_content
        now = datetime.now(timezone.utc)
        key_digest = hashlib.sha256(self.public.read_bytes()).hexdigest()
        verified = verify_owner_attestation(
            envelope, public_key_path=self.public, public_key_sha256=key_digest,
            expected_issuer="issuer-test", expected_audience="ocpv2-test",
            expected_owner_actor_id="235775273", now=now)
        active, challenge = self.status("ACT-1")
        verify_owner_status(
            active, public_key_path=self.public, public_key_sha256=key_digest,
            expected_issuer="issuer-test", expected_audience="ocpv2-test",
            expected_decision_id=self.scope["decision_id"],
            expected_scope_sha256=verified.scope_sha256,
            expected_activation_id="ACT-1", expected_challenge=challenge, now=now)
        other, challenge = self.status("ACT-2")
        with self.assertRaises(OwnerAttestationError):
            verify_owner_status(
                other, public_key_path=self.public, public_key_sha256=key_digest,
                expected_issuer="issuer-test", expected_audience="ocpv2-test",
                expected_decision_id=self.scope["decision_id"],
                expected_scope_sha256=verified.scope_sha256,
                expected_activation_id="ACT-2", expected_challenge=challenge, now=now)

        async def confirm_revoke(context, params):
            return ElicitResult(action="accept", content={"decision_id": self.scope["decision_id"]})
        revoked = await self.call("owner-token", "revoke_full_plan",
                                  {"decision_id": self.scope["decision_id"]}, confirm_revoke)
        self.assertFalse(revoked.is_error)
        inactive, _ = self.status("ACT-1")
        self.assertFalse(inactive["payload"]["active"])


if __name__ == "__main__":
    unittest.main()
