from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .lv_execution_package import canonical_json_bytes


class GateApprovalError(ValueError):
    pass


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EVIDENCE_FIELDS = {
    "schema_version", "approval_id", "project_id", "gate_id", "requirements_sha256",
    "plan_sha256", "branch", "head", "scope", "issued_at", "expires_at", "status",
}
_SCOPE_FIELDS = {"lv_order", "owned_files_by_lv"}


def _hash(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GateApprovalError(f"{label} must be UTC RFC3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise GateApprovalError(f"invalid {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise GateApprovalError(f"{label} must be UTC RFC3339")
    return parsed


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise GateApprovalError(f"invalid {label}")
    return value


def seal_approval_evidence(payload: Mapping[str, object]) -> dict[str, object]:
    value = dict(payload)
    _validate_schema(value)
    return {"payload": value, "record_hash": _hash(value)}


def _validate_schema(payload: Mapping[str, object]) -> None:
    if set(payload) != _EVIDENCE_FIELDS or payload.get("schema_version") != "orchestration.gate-approval.v1":
        raise GateApprovalError("approval evidence schema mismatch")
    for field in ("approval_id", "project_id", "gate_id", "branch"):
        _id(payload.get(field), field)
    for field in ("requirements_sha256", "plan_sha256"):
        if not isinstance(payload.get(field), str) or not _SHA256.fullmatch(payload[field]):
            raise GateApprovalError(f"invalid {field}")
    if not isinstance(payload.get("head"), str) or not _HEAD.fullmatch(payload["head"]):
        raise GateApprovalError("invalid head")
    scope = payload.get("scope")
    if not isinstance(scope, dict) or set(scope) != _SCOPE_FIELDS:
        raise GateApprovalError("approval scope schema mismatch")
    order = scope.get("lv_order")
    owned = scope.get("owned_files_by_lv")
    if (not isinstance(order, list) or not order or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in order)
            or len(set(order)) != len(order)):
        raise GateApprovalError("invalid approval LV order")
    if not isinstance(owned, dict) or set(owned) != set(order):
        raise GateApprovalError("approval owned-file scope mismatch")
    for paths in owned.values():
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
            raise GateApprovalError("invalid approval owned-file scope")
    _time(payload.get("issued_at"), "issued_at")
    _time(payload.get("expires_at"), "expires_at")
    if payload.get("status") != "ACTIVE":
        raise GateApprovalError("approval is not ACTIVE")


def load_approval_evidence(path: str | Path) -> dict[str, object]:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise GateApprovalError("approval evidence is missing or unsafe")
    if source.stat().st_size > 1024 * 1024:
        raise GateApprovalError("approval evidence exceeds size limit")
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateApprovalError("approval evidence is malformed") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "record_hash"} or not isinstance(envelope.get("payload"), dict):
        raise GateApprovalError("approval evidence envelope mismatch")
    if envelope.get("record_hash") != _hash(envelope["payload"]):
        raise GateApprovalError("approval evidence hash mismatch")
    _validate_schema(envelope["payload"])
    return envelope


def validate_approval_evidence(envelope: Mapping[str, object], *, project_id: str, gate_id: str,
                               requirements_sha256: str, plan_sha256: str, branch: str, head: str,
                               lv_order: Sequence[str], owned_files_by_lv: Mapping[str, Sequence[str]],
                               now: datetime | None = None) -> dict[str, object]:
    if set(envelope) != {"payload", "record_hash"} or not isinstance(envelope.get("payload"), dict):
        raise GateApprovalError("approval evidence envelope mismatch")
    payload = envelope["payload"]
    assert isinstance(payload, dict)
    if envelope.get("record_hash") != _hash(payload):
        raise GateApprovalError("approval evidence hash mismatch")
    _validate_schema(payload)
    expected = {
        "project_id": project_id, "gate_id": gate_id, "requirements_sha256": requirements_sha256,
        "plan_sha256": plan_sha256, "branch": branch, "head": head,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise GateApprovalError(f"approval {field} binding mismatch")
    expected_order = list(lv_order)
    expected_owned = {key: list(value) for key, value in owned_files_by_lv.items()}
    if payload["scope"] != {"lv_order": expected_order, "owned_files_by_lv": expected_owned}:
        raise GateApprovalError("approval scope binding mismatch")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise GateApprovalError("validation time must be timezone-aware")
    issued = _time(payload["issued_at"], "issued_at")
    expires = _time(payload["expires_at"], "expires_at")
    if issued > current:
        raise GateApprovalError("approval is stale or not yet issued")
    if expires <= issued or current >= expires:
        raise GateApprovalError("approval is expired")
    return dict(payload)


def derive_system_transition(approval_payload: Mapping[str, object], *, lv_id: str) -> dict[str, object]:
    _validate_schema(approval_payload)
    scope = approval_payload["scope"]
    assert isinstance(scope, dict)
    order = scope["lv_order"]
    assert isinstance(order, list)
    if lv_id not in order:
        raise GateApprovalError("LV is outside approved Gate scope; next Gate is blocked")
    return {
        "schema_version": "orchestration.system-transition.v1",
        "authority_type": "SYSTEM_TRANSITION",
        "derived_from_approval_id": approval_payload["approval_id"],
        "project_id": approval_payload["project_id"],
        "gate_id": approval_payload["gate_id"],
        "lv_id": lv_id,
        "requirements_sha256": approval_payload["requirements_sha256"],
        "plan_sha256": approval_payload["plan_sha256"],
        "branch": approval_payload["branch"],
        "head": approval_payload["head"],
        "owned_files": list(scope["owned_files_by_lv"][lv_id]),
        "user_approval_renewal": False,
    }
