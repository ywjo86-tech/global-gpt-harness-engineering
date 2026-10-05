"""Typed, non-authoritative aggregate projection for the AI Office List Dashboard."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .operations_read_model import OperationsReadModelV1
from .operations_dashboard_model_usage import (
    unavailable_model_usage_projection,
    validate_model_usage_projection,
)

DASHBOARD_SCHEMA_V2 = "jarvis.ai-office-dashboard-projection.v2"
DASHBOARD_SOURCE_CONTRACT_V2 = "orchestration.operations-dashboard-aggregate.v2"

_ACTIVE_STATES = {
    "QUEUED",
    "PLANNING",
    "RUNNING",
    "WAITING_DEPENDENCY",
    "RECOVERING",
}
_ISSUE_STATES = {"STALLED", "FAILED", "UNKNOWN"}
_EXPECTED_HEALTH = {
    "attention": "PASS",
    "reconcile": "PASS",
    "post_change": "PASS",
    "acceptance": "ACCEPTED",
}
_DEPARTMENTS = (
    ("financial", "Financial Office"),
    ("accelerator", "Accelerator Office"),
    ("procurement", "Procurement Office"),
    ("research", "Research Office"),
    ("content", "Content Office"),
    ("development", "Development Office"),
    ("capability", "AI Capability Acquisition"),
)
_FORBIDDEN_KEYS = {
    "provider",
    "provider_ref",
    "model_ref",
    "backend",
    "backend_ref",
    "credential",
    "credentials",
    "token",
    "api_key",
    "authorization",
    "effect_payload",
    "raw_effect_payload",
}


class OperationsDashboardProjectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InvalidCurrentWorkObservationV1:
    project_id: str
    run_id: str
    source_timestamp: str
    reason: str
    source_ref: str = ""

    def __post_init__(self) -> None:
        if not str(self.project_id).strip() or not str(self.run_id).strip():
            raise OperationsDashboardProjectionError("invalid observation identity required")
        _parse_timestamp(self.source_timestamp)
        if not str(self.reason).strip():
            raise OperationsDashboardProjectionError("invalid observation reason required")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest_unsigned(payload: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "projection_sha256"}
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise OperationsDashboardProjectionError("timezone-aware source timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsDashboardProjectionError("source timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise OperationsDashboardProjectionError("source timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _read_model_timestamp(model: OperationsReadModelV1) -> datetime:
    timestamps: list[datetime] = []
    for source in model.sources:
        try:
            timestamps.append(_parse_timestamp(source.source_timestamp))
        except OperationsDashboardProjectionError:
            continue
    if not timestamps:
        raise OperationsDashboardProjectionError(
            f"read model source timestamp unavailable: {model.project_id}/{model.run_id}"
        )
    return max(timestamps)


def _walk_forbidden(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            if name.lower() in _FORBIDDEN_KEYS:
                raise OperationsDashboardProjectionError(f"forbidden dashboard field: {path}.{name}")
            _walk_forbidden(child, f"{path}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]")


def _validate_resources(resources: Mapping[str, Any] | None) -> dict[str, Any]:
    value = dict(resources or {})
    result: dict[str, Any] = {"cpu_percent": None, "memory_percent": None, "storage_percent": None}
    for key in tuple(result):
        raw = value.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise OperationsDashboardProjectionError(f"{key} must be numeric or null")
        number = float(raw)
        if not 0.0 <= number <= 100.0:
            raise OperationsDashboardProjectionError(f"{key} out of range")
        result[key] = round(number, 1)
    result["source"] = str(value.get("source") or "UNAVAILABLE")
    model_usage = value.get("model_usage_cost")
    result["model_usage_cost"] = validate_model_usage_projection(
        model_usage if isinstance(model_usage, Mapping) else unavailable_model_usage_projection()
    )
    return result


def _department_rows(rows: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if rows is None:
        return [
            {
                "department_id": department_id,
                "display_name": display_name,
                "binding_state": "UNBOUND",
                "status": "IDLE",
                "current_work": "연결된 canonical work 없음",
                "progress": None,
                "source_state": "NO_CANONICAL_DEPARTMENT_BINDING",
            }
            for department_id, display_name in _DEPARTMENTS
        ]
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise OperationsDashboardProjectionError("department row must be a mapping")
        progress = row.get("progress")
        if progress is not None and (
            isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100
        ):
            raise OperationsDashboardProjectionError("department progress invalid")
        result.append({
            "department_id": str(row.get("department_id") or ""),
            "display_name": str(row.get("display_name") or ""),
            "binding_state": str(row.get("binding_state") or "BOUND"),
            "status": str(row.get("status") or "UNKNOWN"),
            "current_work": str(row.get("current_work") or ""),
            "progress": progress,
            "source_state": str(row.get("source_state") or "CANONICAL"),
        })
    return result


def _bounded_collection(
    value: Mapping[str, Any] | None,
    *,
    unavailable_note: str,
) -> dict[str, Any]:
    if value is None:
        return {"source_state": "UNAVAILABLE", "items": [], "note": unavailable_note}
    result = dict(value)
    items = result.get("items")
    if not isinstance(items, list):
        raise OperationsDashboardProjectionError("bounded collection items must be a list")
    result.setdefault("source_state", "CANONICAL")
    return result


def _select_current(
    read_models: Sequence[OperationsReadModelV1],
    invalid_current: Sequence[InvalidCurrentWorkObservationV1],
) -> list[dict[str, Any]]:
    candidates: dict[str, tuple[datetime, dict[str, Any]]] = {}

    for model in read_models:
        if not isinstance(model, OperationsReadModelV1):
            raise OperationsDashboardProjectionError("OperationsReadModelV1 input required")
        observed = _read_model_timestamp(model)
        row = {
            "project_id": model.project_id,
            "run_id": model.run_id,
            "state": model.normalized_state,
            "current_gate": model.gate_id,
            "current_work": model.current_work,
            "updated_at": observed.isoformat(),
            "approval_required": bool(model.approval_required),
            "freshness": model.freshness,
            "issue": None,
            "source_ref": "",
        }
        current = candidates.get(model.project_id)
        if current is None or observed > current[0]:
            candidates[model.project_id] = (observed, row)

    for invalid in invalid_current:
        if not isinstance(invalid, InvalidCurrentWorkObservationV1):
            raise OperationsDashboardProjectionError("InvalidCurrentWorkObservationV1 input required")
        observed = _parse_timestamp(invalid.source_timestamp)
        row = {
            "project_id": invalid.project_id,
            "run_id": invalid.run_id,
            "state": "UNKNOWN",
            "current_gate": None,
            "current_work": "",
            "updated_at": observed.isoformat(),
            "approval_required": False,
            "freshness": "UNKNOWN",
            "issue": "INVALID_CANONICAL_CURRENT_STATE",
            "detail": invalid.reason,
            "source_ref": invalid.source_ref,
        }
        current = candidates.get(invalid.project_id)
        if current is None or observed >= current[0]:
            candidates[invalid.project_id] = (observed, row)

    return [
        row
        for _, row in sorted(
            candidates.values(),
            key=lambda item: item[0],
            reverse=True,
        )
    ]


def validate_operations_dashboard_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise OperationsDashboardProjectionError("dashboard projection mapping required")
    value = dict(payload)
    required = {
        "schema_version",
        "source_contract",
        "generated_at",
        "summary",
        "departments",
        "today_schedule",
        "system_resources",
        "recent_requests",
        "alerts",
        "recent_reports",
        "jarvis_status",
        "system_health",
        "data_quality",
        "spatial_office",
        "projection_sha256",
    }
    if set(value) != required:
        raise OperationsDashboardProjectionError("dashboard projection shape mismatch")
    if value["schema_version"] != DASHBOARD_SCHEMA_V2:
        raise OperationsDashboardProjectionError("dashboard schema mismatch")
    if value["source_contract"] != DASHBOARD_SOURCE_CONTRACT_V2:
        raise OperationsDashboardProjectionError("dashboard source contract mismatch")
    _parse_timestamp(value["generated_at"])
    summary = value["summary"]
    if not isinstance(summary, Mapping):
        raise OperationsDashboardProjectionError("dashboard summary invalid")
    for key in ("total_work", "running", "waiting_approval", "completed_today", "issues"):
        raw = summary.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise OperationsDashboardProjectionError(f"summary.{key} invalid")
    if not isinstance(value["departments"], list):
        raise OperationsDashboardProjectionError("departments must be a list")
    if not isinstance(value["recent_requests"], list) or not isinstance(value["alerts"], list):
        raise OperationsDashboardProjectionError("dashboard rows must be lists")
    for key in ("today_schedule", "system_resources", "recent_reports", "jarvis_status", "system_health", "data_quality", "spatial_office"):
        if not isinstance(value[key], Mapping):
            raise OperationsDashboardProjectionError(f"{key} must be a mapping")
    spatial = value["spatial_office"]
    if spatial.get("status") != "HOLD_BY_USER" or spatial.get("blocks_dashboard") is not False:
        raise OperationsDashboardProjectionError("spatial office HOLD contract mismatch")
    _walk_forbidden(value)
    digest = value.get("projection_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or digest != _digest_unsigned(value):
        raise OperationsDashboardProjectionError("dashboard projection digest mismatch")
    return value


def build_operations_dashboard_projection(
    read_models: Sequence[OperationsReadModelV1],
    *,
    invalid_current: Sequence[InvalidCurrentWorkObservationV1] = (),
    system_health: Mapping[str, str] | None = None,
    system_resources: Mapping[str, Any] | None = None,
    departments: Sequence[Mapping[str, Any]] | None = None,
    today_schedule: Mapping[str, Any] | None = None,
    recent_reports: Mapping[str, Any] | None = None,
    jarvis_status: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    health = {key: str((system_health or {}).get(key) or "UNKNOWN") for key in _EXPECTED_HEALTH}
    rows = _select_current(tuple(read_models), tuple(invalid_current))

    running = sum(1 for row in rows if row["state"] in _ACTIVE_STATES)
    waiting_approval = sum(
        1 for row in rows if row["state"] == "WAITING_APPROVAL" or row["approval_required"]
    )
    kst_today = current.astimezone(ZoneInfo("Asia/Seoul")).date()
    completed_today = sum(
        1
        for row in rows
        if row["state"] == "COMPLETED"
        and _parse_timestamp(row["updated_at"]).astimezone(ZoneInfo("Asia/Seoul")).date() == kst_today
    )

    alerts: list[dict[str, Any]] = []
    invalid_ids: list[str] = []
    for row in rows:
        if row.get("issue"):
            invalid_ids.append(row["project_id"])
            alerts.append({
                "kind": "DATA_QUALITY",
                "severity": "ERROR",
                "title": f'{row["project_id"]} / canonical state invalid',
                "detail": str(row.get("detail") or row["issue"]),
                "source_ref": str(row.get("source_ref") or ""),
            })
        elif row["state"] in _ISSUE_STATES:
            alerts.append({
                "kind": "PROJECT_STATE",
                "severity": "ERROR",
                "title": f'{row["project_id"]} / {row["state"]}',
                "detail": row["current_work"] or "현재 상태 확인 필요",
                "source_ref": "",
            })

    for key, expected in _EXPECTED_HEALTH.items():
        observed = health[key]
        if observed != expected:
            alerts.append({
                "kind": "SYSTEM_HEALTH",
                "severity": "ERROR",
                "title": f"{key} {observed}",
                "detail": f"expected {expected}",
                "source_ref": "",
            })

    payload: dict[str, Any] = {
        "schema_version": DASHBOARD_SCHEMA_V2,
        "source_contract": DASHBOARD_SOURCE_CONTRACT_V2,
        "generated_at": current.isoformat(),
        "summary": {
            "total_work": len(rows),
            "running": running,
            "waiting_approval": waiting_approval,
            "completed_today": completed_today,
            "issues": len(alerts),
            "semantics": "latest typed OperationsReadModelV1 per project; retry history excluded",
        },
        "departments": _department_rows(departments),
        "today_schedule": _bounded_collection(
            today_schedule,
            unavailable_note="canonical business schedule projection not published",
        ),
        "system_resources": _validate_resources(system_resources),
        "recent_requests": rows[:5],
        "alerts": alerts[:8],
        "recent_reports": _bounded_collection(
            recent_reports,
            unavailable_note="canonical report index projection not published",
        ),
        "jarvis_status": dict(jarvis_status or {
            "webapp": "UNKNOWN",
            "memory": "UNKNOWN",
            "llmwiki": "UNKNOWN",
            "source_state": "UNBOUND",
        }),
        "system_health": health,
        "data_quality": {
            "invalid_current_projects": len(invalid_ids),
            "invalid_project_ids": invalid_ids,
        },
        "spatial_office": {
            "status": "HOLD_BY_USER",
            "blocks_dashboard": False,
        },
    }
    _walk_forbidden(payload)
    payload["projection_sha256"] = _digest_unsigned(payload)
    return validate_operations_dashboard_projection(payload)
