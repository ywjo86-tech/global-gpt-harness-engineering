"""Check that every derived Gate record retains one exact owner decision.

Inputs must come from trusted, immutable Harness authority artifacts. A caller
must validate the original owner comment and each artifact before this check.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .full_plan_owner_delegation import OwnerDelegation

FIELDS = {"gate_id", "decision_id", "project_id", "plan_sha256", "spec_sha256",
          "source_head", "runtime_sha256", "owner_comment_id", "scope_sha256"}


class DelegatedGateSetError(ValueError):
    pass


def validate_delegated_gate_set(verified: OwnerDelegation,
                                scope: Mapping[str, Any],
                                rows: Sequence[Mapping[str, Any]]) -> str:
    if not isinstance(verified, OwnerDelegation) or not isinstance(scope, Mapping):
        raise DelegatedGateSetError("ROOT_DECISION_REQUIRED")
    try:
        digest = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        gates = scope["gate_ids"]
        if (digest != verified.scope_sha256 or verified.decision_id != scope["decision_id"]
                or verified.project_id != scope["project_id"]
                or tuple(gates) != verified.gate_ids
                or not isinstance(rows, Sequence) or isinstance(rows, (str, bytes))
                or len(rows) != len(gates)):
            raise DelegatedGateSetError("ROOT_DECISION_MISMATCH")
        for gate, row in zip(gates, rows):
            if not isinstance(row, Mapping) or set(row) != FIELDS:
                raise DelegatedGateSetError("GATE_RECORD_FIELDS_INVALID")
            expected = {
                "gate_id": gate, "decision_id": scope["decision_id"],
                "project_id": scope["project_id"], "plan_sha256": scope["plan_sha256"],
                "spec_sha256": scope["spec_sha256"], "source_head": scope["source_head"],
                "runtime_sha256": scope["runtime_sha256"],
                "owner_comment_id": verified.comment_id,
                "scope_sha256": verified.scope_sha256,
            }
            if dict(row) != expected:
                raise DelegatedGateSetError("GATE_RECORD_BINDING_MISMATCH")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DelegatedGateSetError):
            raise
        raise DelegatedGateSetError("ROOT_DECISION_MISMATCH") from exc
    return verified.decision_id
