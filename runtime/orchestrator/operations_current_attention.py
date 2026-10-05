"""Typed current-attention projection for the AI Office dashboard."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .durable_io import atomic_write_json

CURRENT_ATTENTION_SCHEMA_V1 = "orchestration.current-attention-projection.v1"
CURRENT_ATTENTION_SOURCE_V1 = "CANONICAL_CURRENT_ATTENTION_V1"
_MAX_ITEMS = 20


class CurrentAttentionProjectionError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    unsigned = {k: v for k, v in value.items() if k != "projection_sha256"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise CurrentAttentionProjectionError("generated_at required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CurrentAttentionProjectionError("generated_at invalid") from exc
    if parsed.tzinfo is None:
        raise CurrentAttentionProjectionError("generated_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _safe(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _safe_public_reason(value: object) -> str:
    text = str(value or "").strip()
    for key, secret in os.environ.items():
        if (
            secret
            and len(secret) >= 8
            and re.search(r"(?i)(key|token|secret|password|authorization)", key)
        ):
            text = text.replace(secret, "<redacted>")
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"/home/\S+", "<path>", text)
    text = re.sub(r"[A-Za-z]:\\\S+", "<path>", text)
    return text[:256]


def build_current_attention_projection(
    *,
    runtime_source_identity: str,
    blockers: Sequence[Mapping[str, Any]],
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    runtime = _safe(runtime_source_identity, 160)
    if not runtime:
        raise CurrentAttentionProjectionError("runtime source identity required")
    current = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    items: list[dict[str, str]] = []
    for blocker in blockers[:_MAX_ITEMS]:
        project_id = _safe(blocker.get("project_id"), 160)
        run_id = _safe(blocker.get("run_id"), 200)
        state = _safe(blocker.get("state"), 64).upper()
        if not project_id or not run_id or not state:
            continue
        items.append({
            "project_id": project_id,
            "run_id": run_id,
            "state": state,
            "kind": _safe(blocker.get("kind") or state, 96),
            "reason": _safe_public_reason(blocker.get("reason") or state),
            "current_gate": _safe(
                blocker.get("current_gate") or blocker.get("gate_id"), 160
            ),
            "delivery_class": _safe(blocker.get("delivery_class"), 64),
            "event_id": _safe(blocker.get("event_id"), 64),
        })
    payload: dict[str, Any] = {
        "schema_version": CURRENT_ATTENTION_SCHEMA_V1,
        "generated_at": current.isoformat(timespec="seconds"),
        "runtime_source_identity": runtime,
        "source_state": CURRENT_ATTENTION_SOURCE_V1,
        "items": items,
    }
    payload["projection_sha256"] = _digest(payload)
    return validate_current_attention_projection(payload)


def validate_current_attention_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CurrentAttentionProjectionError("attention projection mapping required")
    raw = dict(value)
    required = {
        "schema_version",
        "generated_at",
        "runtime_source_identity",
        "source_state",
        "items",
        "projection_sha256",
    }
    if set(raw) != required:
        raise CurrentAttentionProjectionError("attention projection shape mismatch")
    if raw["schema_version"] != CURRENT_ATTENTION_SCHEMA_V1:
        raise CurrentAttentionProjectionError("attention projection schema mismatch")
    if raw["source_state"] != CURRENT_ATTENTION_SOURCE_V1:
        raise CurrentAttentionProjectionError("attention projection source mismatch")
    _timestamp(raw["generated_at"])
    if not isinstance(raw["runtime_source_identity"], str) or not raw["runtime_source_identity"]:
        raise CurrentAttentionProjectionError("attention runtime source missing")
    items = raw["items"]
    if not isinstance(items, list) or len(items) > _MAX_ITEMS:
        raise CurrentAttentionProjectionError("attention items invalid")
    item_fields = {
        "project_id",
        "run_id",
        "state",
        "kind",
        "reason",
        "current_gate",
        "delivery_class",
        "event_id",
    }
    for item in items:
        if not isinstance(item, Mapping) or set(item) != item_fields:
            raise CurrentAttentionProjectionError("attention item shape mismatch")
        if not all(isinstance(item[key], str) for key in item_fields):
            raise CurrentAttentionProjectionError("attention item values invalid")
        if not item["project_id"] or not item["run_id"] or not item["state"]:
            raise CurrentAttentionProjectionError("attention item identity missing")
    digest = raw.get("projection_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or digest != _digest(raw):
        raise CurrentAttentionProjectionError("attention projection digest mismatch")
    return raw


def current_attention_path(state_root: str | Path) -> Path:
    root = Path(state_root).expanduser().resolve()
    return root / "operations-v2" / "current-attention.json"


def record_current_attention_projection(
    path: str | Path,
    projection: Mapping[str, Any],
) -> Path:
    value = validate_current_attention_projection(projection)
    target = Path(path)
    if target.exists() and target.is_symlink():
        raise CurrentAttentionProjectionError("attention output path unsafe")
    return atomic_write_json(target, value)


def read_current_attention_projection(
    state_root: str | Path,
    *,
    now: datetime,
    expected_runtime_source: str,
    fresh_after_seconds: int = 180,
) -> dict[str, Any]:
    path = current_attention_path(state_root)
    if path.is_symlink() or not path.is_file():
        return {"source_state": "UNAVAILABLE", "items": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        value = validate_current_attention_projection(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, CurrentAttentionProjectionError):
        return {"source_state": "INVALID", "items": []}
    generated = _timestamp(value["generated_at"])
    current = now.astimezone(timezone.utc)
    if generated > current or (current - generated).total_seconds() > fresh_after_seconds:
        return {"source_state": "STALE", "items": []}
    expected = str(expected_runtime_source or "").strip()
    if expected and value["runtime_source_identity"] != expected:
        return {"source_state": "RUNTIME_MISMATCH", "items": []}
    return {
        "source_state": CURRENT_ATTENTION_SOURCE_V1,
        "items": [dict(item) for item in value["items"]],
    }


def attention_projection_to_dashboard_alerts(
    projection: Mapping[str, Any],
) -> list[dict[str, str]]:
    source_state = str(projection.get("source_state") or "UNAVAILABLE")
    if source_state != CURRENT_ATTENTION_SOURCE_V1:
        return [{
            "kind": "ATTENTION_DELIVERY",
            "severity": "ERROR",
            "title": f"attention delivery {source_state}",
            "detail": "current attention feed is not safely available",
            "source_ref": "operations-v2/current-attention.json",
        }]
    alerts: list[dict[str, str]] = []
    for item in projection.get("items", []):
        state = str(item.get("state") or "UNKNOWN").upper()
        severity = "ERROR" if state in {"BLOCKED", "FAILED", "UNKNOWN"} else "WARNING"
        gate = str(item.get("current_gate") or "")
        reason = str(item.get("reason") or state)
        detail = f"{gate}: {reason}" if gate else reason
        event_id = str(item.get("event_id") or "")
        alerts.append({
            "kind": "USER_ATTENTION",
            "severity": severity,
            "title": f"{item.get('project_id')} / {state}",
            "detail": detail,
            "source_ref": f"attention:{event_id}" if event_id else "attention:current-state",
        })
    return alerts
