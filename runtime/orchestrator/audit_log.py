from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_audit_event(log_path: str | Path, event_type: str, message: str, **fields: Any) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(fields, ensure_ascii=False)
    line = f"{_utc_now()} | {event_type} | {message} | {payload}"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text((existing + ("\n" if existing else "") + line).rstrip() + "\n", encoding="utf-8")


def read_recent_audit_events(log_path: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = Path(log_path)
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    recent = lines[-limit:]
    events: list[dict[str, Any]] = []
    for line in recent:
        parts = [part.strip() for part in line.split("|", 3)]
        if len(parts) < 4:
            events.append({"raw": line})
            continue
        timestamp, event_type, message, json_payload = parts
        try:
            fields = json.loads(json_payload)
        except json.JSONDecodeError:
            fields = {"raw": json_payload}
        events.append(
            {
                "timestamp": timestamp,
                "event_type": event_type,
                "message": message,
                "fields": fields,
            }
        )
    return events
