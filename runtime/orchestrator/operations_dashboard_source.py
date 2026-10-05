"""Bounded source adapter for AI Office Dashboard V2.

This module never reads raw Full Plan state. It consumes AI Office typed state
snapshots through AIOfficeStateStore.load(), then projects them into the
existing OperationsReadModelV1 contract.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.ai_office.state_store import AIOfficeStateStore, AIOfficeStateStoreError

from .operations_dashboard_departments import read_operations_dashboard_departments
from .operations_dashboard_schedule import read_operations_dashboard_today_schedule
from .operations_dashboard_reports import read_operations_dashboard_recent_reports
from .operations_dashboard_jarvis_status import read_operations_dashboard_jarvis_status
from .operations_dashboard_projection import (
    InvalidCurrentWorkObservationV1,
    build_operations_dashboard_projection,
)
from .operations_read_model import (
    OPERATIONS_READ_MODEL_SCHEMA_V1,
    OperationsReadModelV1,
    SourceIdentityV1,
    normalize_operations_state,
    resolve_freshness,
)


class OperationsDashboardSourceError(ValueError):
    pass


def _safe_bootstrap_identity(path: Path) -> tuple[str, str]:
    if path.is_symlink() or not path.is_file():
        raise OperationsDashboardSourceError("unsafe AI Office snapshot")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsDashboardSourceError("AI Office snapshot bootstrap unreadable") from exc
    if not isinstance(value, dict):
        raise OperationsDashboardSourceError("AI Office snapshot bootstrap invalid")
    project_id = value.get("project_id")
    run_id = value.get("run_id")
    if not isinstance(project_id, str) or not project_id or not isinstance(run_id, str) or not run_id:
        raise OperationsDashboardSourceError("AI Office snapshot identity missing")
    return project_id, run_id


def _source_head(baseline_ref: str) -> str:
    value = str(baseline_ref or "")
    if value.startswith("head:") and len(value) > 5:
        return value[5:]
    return "UNKNOWN"


def _snapshot_read_model(
    *,
    state_root: Path,
    path: Path,
    now: datetime,
) -> OperationsReadModelV1:
    project_id, run_id = _safe_bootstrap_identity(path)
    store = AIOfficeStateStore(state_root, project_id=project_id, run_id=run_id)
    if store.snapshot_path.resolve() != path.resolve():
        raise OperationsDashboardSourceError("AI Office snapshot path/identity mismatch")
    try:
        snapshot = store.load()
    except AIOfficeStateStoreError as exc:
        raise OperationsDashboardSourceError("AI Office snapshot canonical validation failed") from exc

    observed = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    source = SourceIdentityV1(
        source_component="AI_OFFICE_STATE_STORE",
        source_version=snapshot.schema_version,
        source_head=_source_head(snapshot.baseline_ref),
        source_timestamp=observed,
    )
    normalized, human = normalize_operations_state(snapshot.workflow_state)
    return OperationsReadModelV1(
        schema_version=OPERATIONS_READ_MODEL_SCHEMA_V1,
        project_id=snapshot.project_id,
        run_id=snapshot.run_id,
        task_id="",
        gate_id="",
        raw_state=snapshot.workflow_state,
        normalized_state=normalized,
        human_state=human,
        progress=None,
        progress_source="",
        current_work="",
        outcome="",
        impact="",
        next_step="",
        approval_required=bool(snapshot.pending_approval_ref),
        approval_refs=(snapshot.pending_approval_ref,) if snapshot.pending_approval_ref else (),
        checkpoint_refs=(),
        evidence_refs=snapshot.workflow_refs,
        sources=(source,),
        freshness=resolve_freshness((source,), now),
        diagnostic_health=None,
        operational_acceptance=None,
    )


def _synthetic_invalid_identity(path: Path) -> tuple[str, str]:
    # Only used when the JSON is too damaged to expose its own identity. The
    # directory name is never treated as authority; it is a bounded diagnostic
    # label so corruption remains visible instead of disappearing.
    label = path.parent.name.strip() or "unknown-ai-office-run"
    return f"invalid:{label}", "UNKNOWN"


def discover_ai_office_operations_read_models(
    state_root: str | Path,
    *,
    now: datetime | None = None,
) -> tuple[tuple[OperationsReadModelV1, ...], tuple[InvalidCurrentWorkObservationV1, ...]]:
    root = Path(state_root).expanduser().resolve()
    base = root / "_workspace" / "ai-office"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not base.is_dir():
        return (), ()

    models: list[OperationsReadModelV1] = []
    invalid: list[InvalidCurrentWorkObservationV1] = []
    for path in sorted(base.glob("*/snapshot.json")):
        if path.is_symlink() or not path.is_file():
            continue
        observed = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        try:
            models.append(_snapshot_read_model(state_root=root, path=path, now=current))
        except (OperationsDashboardSourceError, OSError, ValueError) as exc:
            try:
                project_id, run_id = _safe_bootstrap_identity(path)
            except OperationsDashboardSourceError:
                project_id, run_id = _synthetic_invalid_identity(path)
            invalid.append(
                InvalidCurrentWorkObservationV1(
                    project_id=project_id,
                    run_id=run_id,
                    source_timestamp=observed,
                    reason=str(exc),
                    source_ref=str(path),
                )
            )
    return tuple(models), tuple(invalid)


def _read_health_value(path: Path, *keys: str) -> str:
    if path.is_symlink() or not path.is_file():
        return "UNAVAILABLE"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "UNAVAILABLE"
    if not isinstance(value, dict):
        return "UNAVAILABLE"
    for key in keys:
        raw = value.get(key)
        if raw is not None:
            return str(raw)
    return "UNKNOWN"


def read_operations_dashboard_health(state_root: str | Path) -> dict[str, str]:
    root = Path(state_root).expanduser().resolve() / "operations-v2"
    return {
        "attention": _read_health_value(root / "attention-health.json", "result", "status"),
        "reconcile": _read_health_value(root / "reconcile-timer-health.json", "result", "status"),
        "post_change": _read_health_value(root / "post-change-gate.json", "status", "result"),
        "acceptance": _read_health_value(root / "operational-acceptance.json", "status", "result"),
    }


def _cpu_percent() -> float | None:
    path = Path("/proc/stat")
    if not path.is_file():
        return None

    def sample() -> tuple[int, int] | None:
        try:
            fields = path.read_text(encoding="utf-8").splitlines()[0].split()
            values = [int(item) for item in fields[1:]]
        except (OSError, ValueError, IndexError):
            return None
        if not values:
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, sum(values)

    first = sample()
    if first is None:
        return None
    time.sleep(0.03)
    second = sample()
    if second is None:
        return None
    total = second[1] - first[1]
    idle = second[0] - first[0]
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, (1.0 - idle / total) * 100.0)), 1)


def _memory_percent() -> float | None:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if rest:
                values[key] = int(rest.strip().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return round((1.0 - available / total) * 100.0, 1)


def read_host_resource_projection() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage("/")
        storage = round(usage.used / usage.total * 100.0, 1) if usage.total else None
    except OSError:
        storage = None
    return {
        "cpu_percent": _cpu_percent(),
        "memory_percent": _memory_percent(),
        "storage_percent": storage,
        "source": "linux_proc_and_statvfs",
    }


def build_live_operations_dashboard_projection(
    state_root: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    models, invalid = discover_ai_office_operations_read_models(state_root, now=current)
    return build_operations_dashboard_projection(
        models,
        invalid_current=invalid,
        system_health=read_operations_dashboard_health(state_root),
        system_resources=read_host_resource_projection(),
        departments=read_operations_dashboard_departments(state_root),
        today_schedule=read_operations_dashboard_today_schedule(state_root, now=current),
        recent_reports=read_operations_dashboard_recent_reports(state_root),
        jarvis_status=read_operations_dashboard_jarvis_status(
            state_root,
            now=current,
            expected_producer_head=os.getenv("JARVIS_MEMORY_COMPACT_EXPECTED_PRODUCER_HEAD"),
        ),
        now=current,
    )
