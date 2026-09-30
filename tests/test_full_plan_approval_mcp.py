"""Boundary checks for the draft authenticated Full Plan MCP ingress."""
import unittest
from unittest.mock import patch

from mcp import Client
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from runtime.orchestrator.full_plan_approval_issuer import ApprovalIssuerError
from runtime.orchestrator.full_plan_approval_mcp import _principal, create_approval_mcp


class Verifier:
    async def verify_token(self, token):
        return None


class Issuer:
    owner_user_id = "owner-123"

    def issue(self, **kwargs):
        raise AssertionError("unauthenticated call reached issuer")

    def revoke(self, **kwargs):
        raise AssertionError("unauthenticated call reached issuer")


def server():
    return create_approval_mcp(
        issuer=Issuer(), verifier=Verifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl("https://ocp.example.com/mcp"),
            required_scopes=["ocp:full-plan-approve"],
            validate_token_resource=True,
        ),
    )


class ApprovalMcpTests(unittest.IsolatedAsyncioTestCase):
    def test_principal_requires_verified_owner_and_scope(self):
        with patch(
            "runtime.orchestrator.full_plan_approval_mcp.get_access_token",
            return_value=None,
        ):
            with self.assertRaisesRegex(ApprovalIssuerError, "OWNER_AUTH_REQUIRED"):
                _principal("owner-123", "ocp:full-plan-approve")
        with patch(
            "runtime.orchestrator.full_plan_approval_mcp.get_access_token",
            return_value=AccessToken(token="x", client_id="client", subject="owner-123",
                                     scopes=[], resource="https://ocp.example.com/mcp"),
        ):
            with self.assertRaisesRegex(ApprovalIssuerError, "OWNER_AUTH_REQUIRED"):
                _principal("owner-123", "ocp:full-plan-approve")

    async def test_stdio_like_in_memory_call_cannot_issue_or_revoke(self):
        async with Client(server()) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            self.assertNotIn("confirmation", tools["approve_full_plan"].input_schema["properties"])
            self.assertNotIn("confirmation", tools["revoke_full_plan"].input_schema["properties"])
            result = await client.call_tool("approve_full_plan", {"scope": {}})
            self.assertTrue(result.is_error)
            result = await client.call_tool("revoke_full_plan", {"decision_id": "d1"})
            self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()
