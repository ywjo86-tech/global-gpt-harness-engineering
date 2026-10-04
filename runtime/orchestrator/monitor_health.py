"""Durable read-only health receipt for the Full Plan attention monitor."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json
from .production_attention_watch import discover_pending_attention, discover_registered_jobs

SCHEMA_VERSION = "orchestration.attention-monitor-health.v1"
TERMINAL_STATES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "SUPERSEDED", "RETIRED"})


class MonitorHealthError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class AttentionMonitorHealthReceiptV1:
    schema_version: str
    search_root: str
    scanned_at: str
    registered_job_count: int
    pending_attention_count: int
    current_attention_count: int
    current_event_ids: tuple[str, ...]
    status: str
    receipt_sha256: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "search_root": self.search_root,
            "scanned_at": self.scanned_at,
            "registered_job_count": self.registered_job_count,
            "pending_attention_count": self.pending_attention_count,
            "current_attention_count": self.current_attention_count,
            "current_event_ids": list(self.current_event_ids),
            "status": self.status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "receipt_sha256": self.receipt_sha256}


def monitor_health_path(state_root: str | Path) -> Path:
    return Path(state_root).expanduser().resolve() / "_workspace" / "operations-health" / "attention-monitor.json"


def record_attention_monitor_health(
    state_root: str | Path,
    *,
    search_root: str | Path | None = None,
    scanned_at: str | None = None,
) -> AttentionMonitorHealthReceiptV1:
    root = Path(state_root).expanduser().resolve()
    search = Path(search_root if search_root is not None else root).expanduser().resolve()
    jobs = discover_registered_jobs(search)
    pending = discover_pending_attention(search)
    current = [item for item in pending if str(item.get("state") or "").upper() not in TERMINAL_STATES]
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "search_root": str(search),
        "scanned_at": str(scanned_at or _now()),
        "registered_job_count": len(jobs),
        "pending_attention_count": len(pending),
        "current_attention_count": len(current),
        "current_event_ids": sorted(str(item.get("event_id") or "") for item in current if item.get("event_id")),
        "status": "HEALTHY" if not current else "BLOCKED",
    }
    receipt = AttentionMonitorHealthReceiptV1(
        schema_version=SCHEMA_VERSION,
        search_root=str(search),
        scanned_at=unsigned["scanned_at"],
        registered_job_count=len(jobs),
        pending_attention_count=len(pending),
        current_attention_count=len(current),
        current_event_ids=tuple(unsigned["current_event_ids"]),
        status=str(unsigned["status"]),
        receipt_sha256=_digest(unsigned),
    )
    path = monitor_health_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, receipt.to_dict())
    return receipt


def load_attention_monitor_health(
    path: str | Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 180,
) -> AttentionMonitorHealthReceiptV1:
    if stale_after_seconds <= 0:
        raise MonitorHealthError("monitor health stale threshold must be positive")
    source = Path(path).expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise MonitorHealthError("monitor health receipt is missing or unsafe")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MonitorHealthError("monitor health receipt is unreadable") from exc
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        raise MonitorHealthError("monitor health receipt schema mismatch")
    ids = value.get("current_event_ids")
    if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
        raise MonitorHealthError("monitor health current event ids are invalid")
    unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if str(value.get("receipt_sha256") or "") != _digest(unsigned):
        raise MonitorHealthError("monitor health receipt digest mismatch")
    try:
        observed = datetime.fromisoformat(str(value.get("scanned_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MonitorHealthError("monitor health timestamp is invalid") from exc
    if observed.tzinfo is None:
        raise MonitorHealthError("monitor health timestamp is naive")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - observed.astimezone(timezone.utc)).total_seconds()
    if age < -5 or age > stale_after_seconds:
        raise MonitorHealthError("monitor health receipt is stale")
    status = str(value.get("status") or "")
    if status not in {"HEALTHY", "BLOCKED"}:
        raise MonitorHealthError("monitor health status is invalid")
    for name in ("registered_job_count", "pending_attention_count", "current_attention_count"):
        raw = value.get(name)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise MonitorHealthError(f"monitor health {name} is invalid")
    if int(value["current_attention_count"]) != len(ids):
        raise MonitorHealthError("monitor health current event count mismatch")
    return AttentionMonitorHealthReceiptV1(
        schema_version=SCHEMA_VERSION,
        search_root=str(value.get("search_root") or ""),
        scanned_at=str(value["scanned_at"]),
        registered_job_count=int(value["registered_job_count"]),
        pending_attention_count=int(value["pending_attention_count"]),
        current_attention_count=int(value["current_attention_count"]),
        current_event_ids=tuple(ids),
        status=status,
        receipt_sha256=str(value["receipt_sha256"]),
    )
