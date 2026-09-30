"""Authenticated MCP ingress for a scoped Full Plan owner decision.

Run only over Streamable HTTP with OAuth token verification. The server refuses
in-memory/stdio calls because those transports have no authenticated principal.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Mapping

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Elicit, Resolve
from pydantic import BaseModel, ConfigDict

from .full_plan_approval_issuer import (
    ApprovalIssuerError, FullPlanApprovalIssuer, _scope, canonical,
)


class ConfirmScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_sha256: str


def _principal(owner: str, required_scope: str) -> str:
    token = get_access_token()
    if (token is None or token.subject != owner
            or required_scope not in token.scopes):
        raise ApprovalIssuerError("OWNER_AUTH_REQUIRED")
    return token.subject


def create_approval_mcp(
    *, issuer: FullPlanApprovalIssuer, verifier: TokenVerifier,
    auth: AuthSettings, required_scope: str = "ocp:full-plan-approve",
) -> MCPServer:
    """Construct an OAuth-protected resource server; caller must serve HTTP only."""
    if verifier is None or auth is None or required_scope not in auth.required_scopes:
        raise ApprovalIssuerError("MCP_AUTH_CONFIG_INVALID")
    mcp = MCPServer("OCP Full Plan owner approval", token_verifier=verifier, auth=auth)

    async def confirm_scope(scope: dict[str, Any]) -> Elicit[ConfirmScope]:
        _principal(issuer.owner_user_id, required_scope)
        _scope(scope, datetime.now(timezone.utc))
        digest = hashlib.sha256(canonical(scope)).hexdigest()
        return Elicit(
            "Full Plan Hybrid approval for project " + scope["project_id"]
            + "; decision " + scope["decision_id"]
            + "; gates " + ", ".join(scope["gate_ids"])
            + "; expires " + scope["expires_at"]
            + ". Excluded: " + ", ".join(sorted(scope["excluded_actions"]))
            + ". Review the exact plan/spec/head/runtime in the tool request. "
            + "To approve once, enter this exact scope SHA-256: " + digest,
            ConfirmScope,
        )

    @mcp.tool()
    def approve_full_plan(
        scope: dict[str, Any],
        confirmation: Annotated[ConfirmScope, Resolve(confirm_scope)],
    ) -> dict[str, Any]:
        """Request a single scoped owner approval with an explicit confirmation."""
        owner = _principal(issuer.owner_user_id, required_scope)
        now = datetime.now(timezone.utc)
        _scope(scope, now)
        digest = hashlib.sha256(canonical(scope)).hexdigest()
        if confirmation.scope_sha256 != digest:
            raise ApprovalIssuerError("SCOPE_CONFIRMATION_MISMATCH")
        return issuer.issue(
            scope=scope, authenticated_user_id=owner,
            trusted_confirmation_id="mcp:" + secrets.token_hex(24), now=now,
        )

    async def confirm_revocation(decision_id: str) -> Elicit[ConfirmScope]:
        _principal(issuer.owner_user_id, required_scope)
        return Elicit(
            "Revoke Full Plan decision " + decision_id
            + "? Enter the decision ID to confirm revocation.",
            ConfirmScope,
        )

    @mcp.tool()
    def revoke_full_plan(
        decision_id: str,
        confirmation: Annotated[ConfirmScope, Resolve(confirm_revocation)],
    ) -> dict[str, str]:
        """Revoke an issued decision as its authenticated owner."""
        owner = _principal(issuer.owner_user_id, required_scope)
        if confirmation.scope_sha256 != decision_id:
            raise ApprovalIssuerError("REVOCATION_CONFIRMATION_MISMATCH")
        issuer.revoke(decision_id=decision_id, authenticated_user_id=owner)
        return {"decision_id": decision_id, "status": "revoked"}

    return mcp
