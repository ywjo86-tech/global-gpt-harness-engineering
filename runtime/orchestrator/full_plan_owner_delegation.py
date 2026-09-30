"""Verify a direct owner comment granting one bounded Full Plan delegation.

The caller must fetch the comment from GitHub using its trusted API and must
check deletion or revocation before each later Gate. This module never grants
execution by itself and does not replace the existing Gate approval issuer.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA = "orchestration.full-plan-owner-delegation.v1"
PREFIX = "OCP_FULL_PLAN_OWNER_DELEGATION_V1\n"
EXCLUDED = {"PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"}
FIELDS = {"schema_version", "decision_id", "project_id", "plan_sha256",
          "spec_sha256", "gate_ids", "source_head", "runtime_sha256",
          "issued_at", "expires_at", "excluded_actions"}
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class DelegationError(ValueError):
    pass


@dataclass(frozen=True)
class OwnerDelegation:
    decision_id: str
    comment_id: int
    project_id: str
    gate_ids: tuple[str, ...]
    scope_sha256: str
    expires_at: str


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DelegationError("TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise DelegationError("TIME_INVALID") from exc


def validate_owner_delegation(comment: Mapping[str, Any], *, owner_actor_id: str,
                              expected_comment_id: int, expected_scope: Mapping[str, Any],
                              now: datetime) -> OwnerDelegation:
    if not isinstance(expected_scope, Mapping) or set(expected_scope) != FIELDS:
        raise DelegationError("SCOPE_FIELDS_INVALID")
    scope = dict(expected_scope)
    if (scope["schema_version"] != SCHEMA
            or any(not isinstance(scope[k], str) or not SAFE.fullmatch(scope[k])
                   for k in ("decision_id", "project_id"))
            or any(not isinstance(scope[k], str) or not SHA.fullmatch(scope[k])
                   for k in ("plan_sha256", "spec_sha256", "runtime_sha256"))
            or not isinstance(scope["source_head"], str)
            or not HEAD.fullmatch(scope["source_head"])
            or not isinstance(scope["gate_ids"], list) or not scope["gate_ids"]
            or any(not isinstance(g, str) or not SAFE.fullmatch(g) for g in scope["gate_ids"])
            or len(set(scope["gate_ids"])) != len(scope["gate_ids"])
            or not isinstance(scope["excluded_actions"], list)
            or set(scope["excluded_actions"]) != EXCLUDED
            or len(scope["excluded_actions"]) != len(EXCLUDED)):
        raise DelegationError("SCOPE_INVALID")
    issued, expires = _utc(scope["issued_at"]), _utc(scope["expires_at"])
    if now.tzinfo is None or not (issued <= now < expires):
        raise DelegationError("SCOPE_EXPIRED")
    if not isinstance(comment, Mapping) or type(expected_comment_id) is not int:
        raise DelegationError("OWNER_COMMENT_INVALID")
    actor = comment.get("user")
    if (comment.get("id") != expected_comment_id or expected_comment_id <= 0
            or not isinstance(actor, Mapping) or str(actor.get("id")) != owner_actor_id
            or comment.get("performed_via_github_app") is not None
            or comment.get("created_at") != comment.get("updated_at")):
        raise DelegationError("EXACT_OWNER_COMMENT_REQUIRED")
    created = _utc(comment.get("created_at"))
    if not (issued <= created <= now and created < expires):
        raise DelegationError("OWNER_COMMENT_TIME_INVALID")
    try:
        encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DelegationError("SCOPE_ENCODING_INVALID") from exc
    if comment.get("body") != PREFIX + encoded.decode("utf-8"):
        raise DelegationError("EXACT_OWNER_COMMENT_REQUIRED")
    return OwnerDelegation(scope["decision_id"], expected_comment_id,
                           scope["project_id"], tuple(scope["gate_ids"]),
                           hashlib.sha256(encoded).hexdigest(), scope["expires_at"])


def bind_delegation_to_activation(verified: OwnerDelegation,
                                  scope: Mapping[str, Any],
                                  activation: Mapping[str, Any]) -> tuple[str, ...]:
    """Check the entire activation request against the already verified scope.

    The caller must first validate the original owner comment and then use the
    ordinary Full Plan binding validator to verify these requested artifacts
    against committed files and the serving runtime.
    """
    try:
        encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        if (not isinstance(verified, OwnerDelegation)
                or verified.scope_sha256 != hashlib.sha256(encoded).hexdigest()
                or verified.project_id != scope["project_id"]
                or verified.decision_id != scope["decision_id"]):
            raise DelegationError("DELEGATION_SCOPE_MISMATCH")
        plan = activation["approved_plan"]
        spec = activation["approved_spec"]
        gates = activation["gate_bindings"]
        actual = [gate["gate_id"] for gate in gates]
        matched = (
            isinstance(plan, Mapping) and isinstance(spec, Mapping)
            and isinstance(gates, list) and bool(gates)
            and all(isinstance(gate, Mapping) for gate in gates)
            and scope["plan_sha256"] == plan["sha256"]
            and scope["spec_sha256"] == spec["sha256"]
            and scope["source_head"] == activation["expected_head"]
            and scope["runtime_sha256"] == activation["runtime_release_digest"]
            and scope["gate_ids"] == actual
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DelegationError):
            raise
        raise DelegationError("ACTIVATION_BINDING_MISMATCH") from exc
    if not matched:
        raise DelegationError("ACTIVATION_BINDING_MISMATCH")
    return tuple(actual)
