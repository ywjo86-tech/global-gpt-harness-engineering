"""Typed business schedule adapter for AI Office Dashboard V2."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from runtime.ai_office.business_schedule import AIOfficeBusinessScheduleStore

_KST = ZoneInfo("Asia/Seoul")


def read_operations_dashboard_today_schedule(
    state_root: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    store = AIOfficeBusinessScheduleStore(state_root)
    if not store.root.exists() and not store.root.is_symlink():
        return None

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = current.astimezone(_KST).date()
    selected = []
    for item in store.load_items():
        stamp = datetime.fromisoformat(item.start_at).astimezone(_KST)
        if stamp.date() != today:
            continue
        selected.append((stamp, item))

    selected.sort(key=lambda pair: (pair[0], pair[1].item_id))
    items = [
        {
            "time": stamp.strftime("%H:%M"),
            "title": item.title,
            "status": item.status,
        }
        for stamp, item in selected[:20]
    ]
    return {
        "source_state": "CANONICAL_BUSINESS_SCHEDULE_V1",
        "items": items,
        "note": "typed AI Office business schedule; Asia/Seoul day boundary",
    }
