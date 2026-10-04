"""Durable operational acceptance decision over completed Full Plan execution."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from runtime.diagnostics.process_lifecycle import (
    ProcessLifecycleDiagnosticError,
    load_process_lifecycle_snapshot,
)
from .durable_io import atomic_write_json
from .harness_state_root import job_state_root
from .monitor_health import monitor_health_path
from .operational_post_change_gate import evaluate_post_change_gate
from .production_full_plan_entry import load_job
from .production_full_plan_runner import DurableFullPlanSupervisor

SCHEMA_VERSION = "orchestration.operational-acceptance.v1"


class OperationalAcceptanceError(ValueError):
    pass


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _default_diagnostic_config() -> Path:
    configured = str(os.environ.get("GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG") or "").strip()
    return Path(configured).expanduser().resolve() if configured else (
        Path.home() / ".config" / "gch" / "read-only-host-diagnostic.json"
    ).resolve()


def _state_for_job(job: Mapping[str, Any]) -> dict[str, Any]:
    gates = [str(item["gate_id"]) for item in job["gates"]]
    supervisor = DurableFullPlanSupervisor(
        job_state_root(job),
        project_id=str(job["project_id"]),
        run_id=str(job["run_id"]),
        gates=gates,
        authority_core_sha256=str(job.get("authority_core_sha256") or ""),
        **dict(job.get("policy") or {}),
    )
    state, _ = supervisor.load()
    return state


def acceptance_latest_path(state_root: str | Path, project_id: str, run_id: str) -> Path:
    return (
        Path(state_root).expanduser().resolve()
        / "_workspace" / "operational-acceptance" / project_id / run_id / "latest.json"
    )


def load_latest_acceptance(state_root: str | Path, project_id: str, run_id: str) -> dict[str, Any] | None:
    path = acceptance_latest_path(state_root, project_id, run_id)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return None
    unsigned = {key: item for key, item in value.items() if key != "record_sha256"}
    if str(value.get("record_sha256") or "") != _digest(unsigned):
        return None
    return value


def evaluate_operational_environment(
    state_root: str | Path,
    *,
    monitor_health_receipt_path: str | Path | None = None,
    process_snapshot_path: str | Path | None = None,
    diagnostic_config: str | Path | None = None,
    stale_after_seconds: int = 180,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(state_root).expanduser().resolve()
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise OperationalAcceptanceError("operational acceptance clock must be timezone-aware")
    monitor_path = Path(
        monitor_health_receipt_path if monitor_health_receipt_path is not None else monitor_health_path(root)
    ).expanduser().resolve()
    process_path = Path(
        process_snapshot_path
        if process_snapshot_path is not None
        else root / "_workspace" / "operations-health" / "process-lifecycle-latest.json"
    ).expanduser().resolve()
    config = Path(diagnostic_config).expanduser().resolve() if diagnostic_config is not None else _default_diagnostic_config()
    gate = evaluate_post_change_gate(
        diagnostic_config=config,
        monitor_health_path=monitor_path,
        require_external_monitor_flags=False,
        stale_after_seconds=stale_after_seconds,
    )
    failures = list(gate.get("failures") or [])
    process_snapshot: dict[str, Any] | None = None
    try:
        process_snapshot = load_process_lifecycle_snapshot(
            process_path, now=current, stale_after_seconds=stale_after_seconds,
        )
    except ProcessLifecycleDiagnosticError as exc:
        failures.append(f"PROCESS_LIFECYCLE_HEALTH_INVALID:{exc}")
    if process_snapshot is not None and int(process_snapshot.get("blocking_count") or 0) > 0:
        failures.append("PROCESS_LIFECYCLE_BLOCKED")
    return {
        "gate": gate,
        "process_snapshot": process_snapshot,
        "failures": sorted(dict.fromkeys(str(item) for item in failures)),
        "evaluated_at": current.astimezone(timezone.utc).isoformat(timespec="seconds"),
    }


def record_operational_acceptance(
    job_path: str | Path,
    *,
    monitor_health_receipt_path: str | Path | None = None,
    process_snapshot_path: str | Path | None = None,
    diagnostic_config: str | Path | None = None,
    stale_after_seconds: int = 180,
    now: datetime | None = None,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    job = load_job(job_path)
    state = _state_for_job(job)
    if str(state.get("state") or "") != "COMPLETED":
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise OperationalAcceptanceError("operational acceptance clock must be timezone-aware")

    state_root = job_state_root(job)
    env = dict(environment) if environment is not None else evaluate_operational_environment(
        state_root,
        monitor_health_receipt_path=monitor_health_receipt_path,
        process_snapshot_path=process_snapshot_path,
        diagnostic_config=diagnostic_config,
        stale_after_seconds=stale_after_seconds,
        now=current,
    )
    gate = dict(env.get("gate") or {})
    process_snapshot = env.get("process_snapshot") if isinstance(env.get("process_snapshot"), Mapping) else None
    failures = list(env.get("failures") or [])
    monitor_payload = gate.get("attention_monitor_health") if isinstance(gate.get("attention_monitor_health"), Mapping) else {}
    material = {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(job["project_id"]),
        "run_id": str(job["run_id"]),
        "authority_core_sha256": str(job.get("authority_core_sha256") or ""),
        "execution_state": str(state.get("state") or ""),
        "terminal_reason": str(state.get("terminal_reason") or ""),
        "terminal_state_sha256": str(state.get("state_sha256") or ""),
        "post_change_status": str(gate.get("status") or "BLOCKED"),
        "post_change_failures": sorted(str(item) for item in gate.get("failures") or []),
        "monitor_health_receipt_sha256": str(monitor_payload.get("receipt_sha256") or ""),
        "process_lifecycle_snapshot_sha256": str((process_snapshot or {}).get("snapshot_sha256") or ""),
        "process_lifecycle_blocking_count": int((process_snapshot or {}).get("blocking_count") or 0),
        "status": "ACCEPTED" if not failures else "BLOCKED",
        "failures": sorted(dict.fromkeys(str(item) for item in failures)),
    }
    decision_digest = _digest(material)
    latest = load_latest_acceptance(state_root, material["project_id"], material["run_id"])
    if latest is not None and latest.get("decision_sha256") == decision_digest:
        return latest

    unsigned = {
        **material,
        "decision_sha256": decision_digest,
        "evaluated_at": str(env.get("evaluated_at") or current.astimezone(timezone.utc).isoformat(timespec="seconds")),
    }
    record = {**unsigned, "record_sha256": _digest(unsigned)}
    base = acceptance_latest_path(state_root, material["project_id"], material["run_id"]).parent
    base.mkdir(parents=True, exist_ok=True)
    immutable = base / f"{record['record_sha256']}.json"
    if not immutable.exists():
        atomic_write_json(immutable, record)
    atomic_write_json(base / "latest.json", record)
    return record
