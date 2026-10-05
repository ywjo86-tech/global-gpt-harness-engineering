"""Read the privacy-bounded Jarvis compact status for Dashboard V2."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

COMPACT_STATUS_SCHEMA_V1 = "jarvis.ai-office-compact-status.v1"
COMPACT_STATUS_SOURCE_V1 = "CANONICAL_JARVIS_COMPACT_STATUS_V1"
_ALLOWED_STATUS = {"AVAILABLE", "DEGRADED", "UNAVAILABLE", "UNKNOWN"}


class OperationsDashboardJarvisStatusError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    unsigned = {k: v for k, v in value.items() if k != "status_digest"}
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _source_head(value: object) -> str:
    item = str(value or "").strip().lower()
    if len(item) != 40 or any(ch not in "0123456789abcdef" for ch in item):
        raise OperationsDashboardJarvisStatusError("Jarvis compact status publisher head invalid")
    return item


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def read_operations_dashboard_jarvis_status(
    state_root: str | Path,
    *,
    now: datetime | None = None,
    max_age_seconds: int = 180,
    future_tolerance_seconds: int = 30,
    expected_publisher_head: str | None = None,
) -> dict[str, Any] | None:
    root = Path(state_root).expanduser().resolve()
    path = root / "operations-v2" / "jarvis-compact-status.json"
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise OperationsDashboardJarvisStatusError("unsafe Jarvis compact status path")
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds <= 0:
        raise OperationsDashboardJarvisStatusError("invalid Jarvis compact status max age")

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status unreadable") from exc

    expected = {
        "schema_version", "generated_at", "publisher_source_head",
        "webapp", "memory", "llmwiki", "source_state", "status_digest",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status shape mismatch")
    if value["schema_version"] != COMPACT_STATUS_SCHEMA_V1:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status schema mismatch")
    published_head = _source_head(value["publisher_source_head"])
    expected_head = expected_publisher_head
    if expected_head is None:
        expected_head = os.getenv("AI_OFFICE_JARVIS_COMPACT_STATUS_EXPECTED_PUBLISHER_HEAD")
    if not expected_head:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status expected publisher head required")
    if published_head != _source_head(expected_head):
        raise OperationsDashboardJarvisStatusError("Jarvis compact status publisher head mismatch")
    for key in ("webapp", "memory", "llmwiki"):
        status = value.get(key)
        if status not in _ALLOWED_STATUS:
            raise OperationsDashboardJarvisStatusError(f"Jarvis compact status {key} invalid")
    if value.get("source_state") != COMPACT_STATUS_SOURCE_V1:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status source mismatch")
    digest = value.get("status_digest")
    if not isinstance(digest, str) or len(digest) != 64 or digest != _digest(value):
        raise OperationsDashboardJarvisStatusError("Jarvis compact status digest mismatch")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated = _parse_timestamp(value["generated_at"])
    age = (current - generated).total_seconds()
    if age < -future_tolerance_seconds:
        raise OperationsDashboardJarvisStatusError("Jarvis compact status timestamp is in the future")
    if age > max_age_seconds:
        return {
            "webapp": "UNKNOWN",
            "memory": "UNKNOWN",
            "llmwiki": "UNKNOWN",
            "source_state": "STALE",
        }
    return {
        "webapp": value["webapp"],
        "memory": value["memory"],
        "llmwiki": value["llmwiki"],
        "source_state": COMPACT_STATUS_SOURCE_V1,
    }
