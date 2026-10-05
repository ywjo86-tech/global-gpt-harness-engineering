"""Bounded consumer for Jarvis Memory/LLMWiki compact status."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_V1 = "jarvis.memory-llmwiki-compact-status.v1"
CANONICAL_SOURCE = "CANONICAL_JARVIS_MEMORY_COMPACT_V1"
DEFAULT_MAX_AGE_SECONDS = 180


class JarvisMemoryCompactStatusError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    unsigned = {key: child for key, child in value.items() if key != "status_sha256"}
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _unavailable(source_state: str) -> dict[str, str]:
    return {
        "webapp": "UNKNOWN",
        "memory": "UNAVAILABLE",
        "llmwiki": "UNAVAILABLE",
        "source_state": source_state,
    }


def _validate_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise JarvisMemoryCompactStatusError("compact status mapping required")
    payload = dict(value)
    required = {
        "schema_version", "producer_source_head", "generated_at", "memory", "llmwiki",
        "memory_read_only", "llmwiki_read_only", "write_policy",
        "raw_text_included", "source_state", "status_sha256",
    }
    if set(payload) != required:
        raise JarvisMemoryCompactStatusError("compact status shape mismatch")
    if payload["schema_version"] != SCHEMA_V1:
        raise JarvisMemoryCompactStatusError("compact status schema mismatch")
    head = str(payload["producer_source_head"] or "").strip().lower()
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise JarvisMemoryCompactStatusError("producer_source_head invalid")
    try:
        stamp = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise JarvisMemoryCompactStatusError("generated_at invalid") from exc
    if stamp.tzinfo is None:
        raise JarvisMemoryCompactStatusError("generated_at must be timezone-aware")
    if payload["memory"] not in {"AVAILABLE", "UNAVAILABLE"}:
        raise JarvisMemoryCompactStatusError("memory status invalid")
    if payload["llmwiki"] not in {"AVAILABLE", "UNAVAILABLE"}:
        raise JarvisMemoryCompactStatusError("llmwiki status invalid")
    if payload["memory_read_only"] is not True or payload["llmwiki_read_only"] is not True:
        raise JarvisMemoryCompactStatusError("read-only invariant violated")
    if payload["write_policy"] != "APPROVAL_REQUIRED":
        raise JarvisMemoryCompactStatusError("write policy mismatch")
    if payload["raw_text_included"] is not False:
        raise JarvisMemoryCompactStatusError("raw text forbidden")
    if payload["source_state"] != CANONICAL_SOURCE:
        raise JarvisMemoryCompactStatusError("source state mismatch")
    digest = payload.get("status_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or digest != _digest(payload):
        raise JarvisMemoryCompactStatusError("compact status digest mismatch")
    payload["_generated_at_utc"] = stamp.astimezone(timezone.utc)
    return payload


def read_operations_dashboard_jarvis_status(
    state_root: str | Path,
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    expected_producer_head: str | None = None,
) -> dict[str, str] | None:
    root = Path(state_root).expanduser().resolve()
    path = root / "operations-v2" / "jarvis-memory-compact-status.json"
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        return _unavailable("INVALID_JARVIS_MEMORY_COMPACT_V1")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        payload = _validate_snapshot(value)
    except (OSError, UnicodeError, json.JSONDecodeError, JarvisMemoryCompactStatusError):
        return _unavailable("INVALID_JARVIS_MEMORY_COMPACT_V1")

    if expected_producer_head:
        expected = str(expected_producer_head).strip().lower()
        if len(expected) != 40 or any(ch not in "0123456789abcdef" for ch in expected):
            return _unavailable("INVALID_JARVIS_MEMORY_COMPACT_V1")
        if str(payload["producer_source_head"]).lower() != expected:
            return _unavailable("MISMATCH_JARVIS_MEMORY_COMPACT_V1")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - payload["_generated_at_utc"]).total_seconds()
    if age < -30:
        return _unavailable("INVALID_JARVIS_MEMORY_COMPACT_V1")
    if age > max_age_seconds:
        return _unavailable("STALE_JARVIS_MEMORY_COMPACT_V1")

    return {
        "webapp": "UNKNOWN",
        "memory": str(payload["memory"]),
        "llmwiki": str(payload["llmwiki"]),
        "source_state": CANONICAL_SOURCE,
    }
