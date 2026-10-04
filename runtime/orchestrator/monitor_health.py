"""Durable read-only monitor health receipts for operational acceptance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json

MONITOR_HEALTH_SCHEMA_V1 = "orchestration.monitor-health-receipt.v1"


class MonitorHealthError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class MonitorHealthReceiptV1:
    schema_version: str
    monitor_name: str
    scanned_at: str
    runtime_source_identity: str
    search_root: str
    registered_job_count: int
    pending_current_event_count: int
    result: str
    evidence_refs: tuple[str, ...]
    receipt_sha256: str

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_refs"] = list(self.evidence_refs)
        value.pop("receipt_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        value = self.unsigned_dict()
        value["receipt_sha256"] = self.receipt_sha256
        return value


def build_monitor_health_receipt(
    *,
    monitor_name: str,
    runtime_source_identity: str,
    search_root: str | Path,
    registered_job_count: int,
    pending_current_event_count: int,
    result: str,
    evidence_refs: tuple[str, ...] = (),
    scanned_at: str | None = None,
) -> MonitorHealthReceiptV1:
    name = str(monitor_name or "").strip()
    identity = str(runtime_source_identity or "").strip()
    outcome = str(result or "").strip().upper()
    if not name or not identity or outcome not in {"PASS", "WARN", "BLOCKED"}:
        raise MonitorHealthError("monitor receipt identity/result invalid")
    if isinstance(registered_job_count, bool) or registered_job_count < 0:
        raise MonitorHealthError("registered job count invalid")
    if isinstance(pending_current_event_count, bool) or pending_current_event_count < 0:
        raise MonitorHealthError("pending event count invalid")
    unsigned = {
        "schema_version": MONITOR_HEALTH_SCHEMA_V1,
        "monitor_name": name,
        "scanned_at": scanned_at or _now(),
        "runtime_source_identity": identity,
        "search_root": str(Path(search_root)),
        "registered_job_count": int(registered_job_count),
        "pending_current_event_count": int(pending_current_event_count),
        "result": outcome,
        "evidence_refs": [str(item) for item in evidence_refs if str(item)],
    }
    return MonitorHealthReceiptV1(
        schema_version=unsigned["schema_version"],
        monitor_name=name,
        scanned_at=unsigned["scanned_at"],
        runtime_source_identity=identity,
        search_root=unsigned["search_root"],
        registered_job_count=unsigned["registered_job_count"],
        pending_current_event_count=unsigned["pending_current_event_count"],
        result=outcome,
        evidence_refs=tuple(unsigned["evidence_refs"]),
        receipt_sha256=_digest(unsigned),
    )


def load_monitor_health_receipt(value: Mapping[str, Any] | str | Path) -> MonitorHealthReceiptV1:
    if isinstance(value, (str, Path)):
        path = Path(value)
        if path.is_symlink() or not path.is_file():
            raise MonitorHealthError("monitor receipt path unsafe")
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = dict(value)
    if not isinstance(raw, Mapping) or raw.get("schema_version") != MONITOR_HEALTH_SCHEMA_V1:
        raise MonitorHealthError("monitor receipt schema mismatch")
    refs = raw.get("evidence_refs")
    if not isinstance(refs, list):
        raise MonitorHealthError("monitor receipt refs invalid")
    receipt = MonitorHealthReceiptV1(
        schema_version=str(raw["schema_version"]),
        monitor_name=str(raw["monitor_name"]),
        scanned_at=str(raw["scanned_at"]),
        runtime_source_identity=str(raw["runtime_source_identity"]),
        search_root=str(raw["search_root"]),
        registered_job_count=int(raw["registered_job_count"]),
        pending_current_event_count=int(raw["pending_current_event_count"]),
        result=str(raw["result"]),
        evidence_refs=tuple(str(item) for item in refs),
        receipt_sha256=str(raw["receipt_sha256"]),
    )
    if receipt.receipt_sha256 != _digest(receipt.unsigned_dict()):
        raise MonitorHealthError("monitor receipt digest mismatch")
    return receipt


def record_monitor_health_receipt(path: str | Path, receipt: MonitorHealthReceiptV1) -> None:
    load_monitor_health_receipt(receipt.to_dict())
    atomic_write_json(Path(path), receipt.to_dict())


def evaluate_monitor_health_receipt(
    value: Mapping[str, Any] | str | Path | None,
    *,
    monitor_name: str,
    now: datetime,
    fresh_after_seconds: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    if value is None:
        return None, [f"{monitor_name}:MONITOR_RECEIPT_MISSING"]
    if not isinstance(now, datetime) or now.tzinfo is None or fresh_after_seconds <= 0:
        raise MonitorHealthError("fresh receipt evaluation requires aware now and positive threshold")
    try:
        receipt = load_monitor_health_receipt(value)
        scanned = datetime.fromisoformat(receipt.scanned_at)
    except (MonitorHealthError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, [f"{monitor_name}:MONITOR_RECEIPT_INVALID:{exc}"]
    failures: list[str] = []
    if receipt.monitor_name != monitor_name:
        failures.append(f"{monitor_name}:MONITOR_RECEIPT_NAME_MISMATCH")
    if scanned.tzinfo is None or scanned > now:
        failures.append(f"{monitor_name}:MONITOR_RECEIPT_TIME_INVALID")
    elif (now - scanned).total_seconds() > fresh_after_seconds:
        failures.append(f"{monitor_name}:MONITOR_RECEIPT_STALE")
    if receipt.result != "PASS":
        failures.append(f"{monitor_name}:MONITOR_RECEIPT_{receipt.result}")
    return receipt.to_dict(), failures
