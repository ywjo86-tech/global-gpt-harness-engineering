"""Canonical OfficeReportV1 index adapter for AI Office Dashboard V2."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from runtime.ai_office.report_index import AIOfficeReportIndexStore

_KST = ZoneInfo("Asia/Seoul")


def read_operations_dashboard_recent_reports(
    state_root: str | Path,
    *,
    limit: int = 20,
) -> dict[str, Any] | None:
    store = AIOfficeReportIndexStore(state_root)
    if not store.registry_path.exists() and not store.registry_path.is_symlink():
        return None
    entries = store.load_entries()
    items = []
    for entry in entries[:limit]:
        published = datetime.fromisoformat(entry.published_at).astimezone(_KST)
        items.append({
            "title": entry.title,
            "date": published.strftime("%Y-%m-%d"),
        })
    return {
        "source_state": "CANONICAL_OFFICE_REPORT_INDEX_V1",
        "items": items,
        "note": "verified OfficeReportV1 index only",
    }
