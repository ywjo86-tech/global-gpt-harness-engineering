from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_V2 = "orchestration.production-approval.v2"
SCHEMA_V1 = "orchestration.gate-approval.v1"
APPROVAL_MODES = {"GATE_BY_GATE"}
EVENT_TYPES = {"APPROVED", "CORRECTION"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SECRET = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})\b|"
    r"\b(?:api[_-]?key|authorization|password|token)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)

FIELDS = {
    "schema_version", "event_id", "event_type", "project_id", "gate_id",
    "plan_sha256", "branch", "baseline_head", "approved_at", "recorded_at",
    "approval_mode", "canonical_lv_scope", "owned_file_scope",
    "completion_conditions_sha256", "predecessor", "supersedes",
    "authorization_source", "record_hash",
}


class ProductionApprovalError(ValueError):
    """Fail-closed production approval validation error."""


@dataclass(frozen=True)
class ApprovalBindings:
    project_id: str
    gate_id: str
    plan_sha256: str
    branch: str
    baseline_head: str
    approval_mode: str
    canonical_lv_scope: tuple[str, ...]
    owned_file_scope: Mapping[str, tuple[str, ...]]
    completion_conditions_sha256: str


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def calculate_v2_record_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes({key: value for key, value in event.items() if key != "record_hash"})).hexdigest()


def _utc_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProductionApprovalError(f"{field} must be UTC RFC3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProductionApprovalError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ProductionApprovalError(f"{field} must be UTC RFC3339")
    return parsed


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProductionApprovalError(f"invalid {field}")
    return value


def _relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or Path(value).is_absolute():
        raise ProductionApprovalError(f"invalid {field}")
    parts = PurePosixPath(value).parts
    if ".." in parts or "." in parts or any(not part for part in parts):
        raise ProductionApprovalError(f"invalid {field}")
    return value


def _contains_secret(value: object) -> bool:
    if isinstance(value, str):
        return bool(_SECRET.search(value))
    if isinstance(value, Mapping):
        return any(_contains_secret(key) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return False


def validate_v2_schema(event: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if set(event) != FIELDS or event.get("schema_version") != SCHEMA_V2:
        raise ProductionApprovalError("production approval v2 schema mismatch")
    if _contains_secret(event):
        raise ProductionApprovalError("approval event contains secret-like material")
    for field in ("event_id", "project_id", "gate_id", "branch", "authorization_source"):
        _identifier(event.get(field), field)
    if event.get("event_type") not in EVENT_TYPES:
        raise ProductionApprovalError("invalid event_type")
    for field in ("plan_sha256", "completion_conditions_sha256", "record_hash"):
        if not isinstance(event.get(field), str) or not _SHA256.fullmatch(event[field]):
            raise ProductionApprovalError(f"invalid {field}")
    if not isinstance(event.get("baseline_head"), str) or not _HEAD.fullmatch(event["baseline_head"]):
        raise ProductionApprovalError("invalid baseline_head")
    if event.get("approval_mode") not in APPROVAL_MODES:
        raise ProductionApprovalError("invalid approval_mode")

    scope = event.get("canonical_lv_scope")
    owned = event.get("owned_file_scope")
    if not isinstance(scope, list) or not scope or len(scope) != len(set(scope)):
        raise ProductionApprovalError("invalid canonical_lv_scope")
    for item in scope:
        _identifier(item, "canonical_lv_scope")
    if not isinstance(owned, dict) or set(owned) != set(scope):
        raise ProductionApprovalError("owned_file_scope must exactly cover canonical_lv_scope")
    for lv_id, paths in owned.items():
        if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
            raise ProductionApprovalError(f"invalid owned_file_scope for {lv_id}")
        for path in paths:
            _relative_path(path, "owned_file_scope path")

    predecessor = event.get("predecessor")
    supersedes = event.get("supersedes")
    if predecessor is not None and (not isinstance(predecessor, str) or not _SHA256.fullmatch(predecessor)):
        raise ProductionApprovalError("invalid predecessor")
    if supersedes is not None:
        _identifier(supersedes, "supersedes")
    if event["event_type"] == "APPROVED" and supersedes is not None:
        raise ProductionApprovalError("APPROVED event cannot supersede another event")
    if event["event_type"] == "CORRECTION" and (predecessor is None or supersedes is None):
        raise ProductionApprovalError("CORRECTION requires predecessor and supersedes")

    approved = _utc_time(event.get("approved_at"), "approved_at")
    recorded = _utc_time(event.get("recorded_at"), "recorded_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current):
        raise ProductionApprovalError("validation clock must be UTC-aware")
    if approved > recorded:
        raise ProductionApprovalError("approved_at cannot be after recorded_at")
    if recorded > current:
        raise ProductionApprovalError("recorded_at cannot be in the future")
    if calculate_v2_record_hash(event) != event["record_hash"]:
        raise ProductionApprovalError("production approval record_hash mismatch")
    return dict(event)


def validate_v2_chain(events: Iterable[Mapping[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    previous_hash: str | None = None
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(events, start=1):
        event = validate_v2_schema(raw, now=now)
        event_id = event["event_id"]
        if event_id in ids:
            raise ProductionApprovalError(f"duplicate production approval event_id at event {index}")
        if event["predecessor"] != previous_hash:
            raise ProductionApprovalError(f"broken predecessor at event {index}")
        supersedes = event["supersedes"]
        if supersedes is not None:
            prior = by_id.get(supersedes)
            if prior is None:
                raise ProductionApprovalError(f"supersedes does not identify a prior event at event {index}")
            if (prior["project_id"], prior["gate_id"]) != (event["project_id"], event["gate_id"]):
                raise ProductionApprovalError(f"cross-scope correction at event {index}")
        ids.add(event_id)
        by_id[event_id] = event
        previous_hash = event["record_hash"]
        validated.append(event)
    if not validated:
        raise ProductionApprovalError("no production approval v2 events")
    return validated


def evaluate_production_authorization(
    events: Iterable[Mapping[str, Any]], bindings: ApprovalBindings, *, now: datetime | None = None,
) -> dict[str, Any]:
    chain = validate_v2_chain(events, now=now)
    event = chain[-1]
    expected: dict[str, object] = {
        "project_id": bindings.project_id,
        "gate_id": bindings.gate_id,
        "plan_sha256": bindings.plan_sha256,
        "branch": bindings.branch,
        "baseline_head": bindings.baseline_head,
        "approval_mode": bindings.approval_mode,
        "canonical_lv_scope": list(bindings.canonical_lv_scope),
        "owned_file_scope": {key: list(value) for key, value in bindings.owned_file_scope.items()},
        "completion_conditions_sha256": bindings.completion_conditions_sha256,
    }
    for field, value in expected.items():
        if event.get(field) != value:
            raise ProductionApprovalError(f"production approval {field} binding mismatch")
    return event


def classify_approval_schema(event: Mapping[str, Any]) -> str:
    """Classify legacy records without ever authorizing production from v1."""
    if event.get("schema_version") == SCHEMA_V1:
        return "HISTORICAL_READ_ONLY"
    if event.get("schema_version") == SCHEMA_V2:
        return "PRODUCTION_V2"
    return "UNSUPPORTED"
