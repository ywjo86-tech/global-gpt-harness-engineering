"""Verify an independently issued, bounded Full Plan approval receipt.

This is a consumer only. Supplying a key or minting a receipt is outside OCP's
operator path; until a trusted issuer is provisioned, verification fails closed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA = "orchestration.full-plan-approval-receipt.v1"
EXCLUDED = {"PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"}
FIELDS = {
    "schema_version", "issuer", "subject", "decision_id", "decision", "project_id",
    "plan_sha256", "spec_sha256", "gate_ids", "source_head", "runtime_sha256",
    "issued_at", "expires_at", "nonce", "excluded_actions",
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEAD = re.compile(r"[0-9a-f]{40}\Z")


class ReceiptError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedApproval:
    decision_id: str
    project_id: str
    gate_ids: tuple[str, ...]
    plan_sha256: str
    spec_sha256: str
    expires_at: str


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReceiptError("RECEIPT_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReceiptError("RECEIPT_TIME_INVALID") from exc
    return parsed.astimezone(timezone.utc)


def verify_receipt(receipt: Mapping[str, Any], *, trust_key: bytes | None,
                   issuer: str, subject: str, project_id: str, plan_sha256: str,
                   spec_sha256: str, gate_id: str, source_head: str,
                   runtime_sha256: str, action: str, now: datetime) -> VerifiedApproval:
    if not isinstance(trust_key, bytes) or len(trust_key) < 32:
        raise ReceiptError("TRUST_ROOT_UNAVAILABLE")
    if not isinstance(receipt, Mapping) or set(receipt) != {"payload", "signature"}:
        raise ReceiptError("RECEIPT_FIELDS_INVALID")
    payload, signature = receipt["payload"], receipt["signature"]
    if not isinstance(payload, Mapping) or set(payload) != FIELDS or not isinstance(signature, str):
        raise ReceiptError("RECEIPT_FIELDS_INVALID")
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReceiptError("RECEIPT_ENCODING_INVALID") from exc
    expected_sig = hmac.new(trust_key, encoded, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        raise ReceiptError("RECEIPT_SIGNATURE_INVALID")
    if (payload["schema_version"] != SCHEMA or payload["decision"] != "APPROVED"
            or any(not isinstance(payload[k], str) or not payload[k]
                   for k in ("issuer", "subject", "decision_id", "project_id", "nonce"))
            or not isinstance(payload["gate_ids"], list)
            or not payload["gate_ids"]
            or any(not isinstance(g, str) or not g for g in payload["gate_ids"])
            or len(set(payload["gate_ids"])) != len(payload["gate_ids"])
            or not isinstance(payload["excluded_actions"], list)
            or set(payload["excluded_actions"]) != EXCLUDED
            or any(not isinstance(payload[k], str) or not SHA.fullmatch(payload[k])
                   for k in ("plan_sha256", "spec_sha256", "runtime_sha256"))
            or not isinstance(payload["source_head"], str)
            or not HEAD.fullmatch(payload["source_head"])):
        raise ReceiptError("RECEIPT_SCOPE_INVALID")
    issued, expires = _time(payload["issued_at"]), _time(payload["expires_at"])
    if now.tzinfo is None or not (issued <= now < expires) or expires <= issued:
        raise ReceiptError("RECEIPT_WINDOW_INVALID")
    if (payload["issuer"] != issuer or payload["subject"] != subject
            or payload["project_id"] != project_id
            or payload["plan_sha256"] != plan_sha256
            or payload["spec_sha256"] != spec_sha256
            or payload["source_head"] != source_head
            or payload["runtime_sha256"] != runtime_sha256
            or gate_id not in payload["gate_ids"]):
        raise ReceiptError("RECEIPT_BINDING_MISMATCH")
    if action != "JOB_EXECUTE":
        raise ReceiptError("ACTION_NOT_AUTHORIZED")
    return VerifiedApproval(payload["decision_id"], project_id,
                            tuple(payload["gate_ids"]), plan_sha256,
                            spec_sha256, payload["expires_at"])
