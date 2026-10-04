"""Read-only process lifecycle diagnostics; this module owns no cleanup authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from runtime.orchestrator.durable_io import atomic_write_json


class ProcessLifecycleDiagnosticError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessLifecycleDiagnosticV1:
    pid: int
    owner_ref: str
    owner_state_exists: bool
    lock_exists: bool
    expected_lifecycle_state: str
    last_semantic_progress: str
    status: str
    orphan_suspicion_reason: str
    recommended_action: str
    cleanup_authorization_required: bool
    process_kind: str = ""
    age_seconds: float | None = None
    max_lifetime_seconds: float | None = None


def collect_process_ownership_facts(
    *,
    pid: int,
    owner_ref: str,
    owner_state_path: str | Path,
    lock_path: str | Path,
    expected_lifecycle_state: str = "UNKNOWN",
    last_semantic_progress: str = "",
    command_digest: str = "",
) -> dict[str, Any]:
    """Collect read-only ownership facts; never signals or reaps a process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProcessLifecycleDiagnosticError("valid pid is required")
    state = Path(owner_state_path)
    lock = Path(lock_path)
    return {
        "pid": pid,
        "owner_ref": str(owner_ref),
        "owner_state_path": str(state),
        "owner_state_exists": state.exists() and not state.is_symlink(),
        "lock_path": str(lock),
        "lock_exists": lock.exists() and not lock.is_symlink(),
        "expected_lifecycle_state": str(expected_lifecycle_state),
        "last_semantic_progress": str(last_semantic_progress),
        "command_digest": str(command_digest),
        "collection_mode": "READ_ONLY",
    }


def diagnose_process_lifecycle(
    facts: Mapping[str, Any], *, now: datetime
) -> ProcessLifecycleDiagnosticV1:
    if not isinstance(facts, Mapping):
        raise ProcessLifecycleDiagnosticError("process facts must be a mapping")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ProcessLifecycleDiagnosticError("timezone-aware now is required")
    pid = facts.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProcessLifecycleDiagnosticError("valid pid is required")
    owner_ref = str(facts.get("owner_ref") or "").strip()
    owner_state_exists = bool(facts.get("owner_state_exists"))
    lock_exists = bool(facts.get("lock_exists"))
    expected = str(facts.get("expected_lifecycle_state") or "UNKNOWN").strip()
    progress = str(facts.get("last_semantic_progress") or "").strip()
    kind = str(facts.get("process_kind") or "").strip()
    age_raw = facts.get("age_seconds")
    max_raw = facts.get("max_lifetime_seconds")
    age = float(age_raw) if isinstance(age_raw, (int, float)) and not isinstance(age_raw, bool) else None
    max_lifetime = float(max_raw) if isinstance(max_raw, (int, float)) and not isinstance(max_raw, bool) else None
    if age is not None and age < 0:
        raise ProcessLifecycleDiagnosticError("process age is invalid")
    if max_lifetime is not None and max_lifetime <= 0:
        raise ProcessLifecycleDiagnosticError("process lifetime bound is invalid")
    if not owner_ref:
        raise ProcessLifecycleDiagnosticError("owner reference is required")
    if max_lifetime is not None and age is not None and age > max_lifetime:
        status = "ORPHAN_SUSPECTED"
        reason = "process exceeded bounded lifetime"
        action = "review process ownership and authorize cleanup if confirmed"
        approval = True
    elif not owner_state_exists and not lock_exists:
        status = "ORPHAN_SUSPECTED"
        reason = "owner state and lock are both missing"
        action = "review process ownership and authorize cleanup if confirmed"
        approval = True
    elif not owner_state_exists or not lock_exists:
        status = "OWNERSHIP_DEGRADED"
        reason = "process ownership evidence is incomplete"
        action = "review owner state and lock consistency"
        approval = False
    else:
        status = "OWNED"
        reason = ""
        action = "none"
        approval = False
    return ProcessLifecycleDiagnosticV1(
        pid=pid,
        owner_ref=owner_ref,
        owner_state_exists=owner_state_exists,
        lock_exists=lock_exists,
        expected_lifecycle_state=expected,
        last_semantic_progress=progress,
        status=status,
        orphan_suspicion_reason=reason,
        recommended_action=action,
        cleanup_authorization_required=approval,
        process_kind=kind,
        age_seconds=age,
        max_lifetime_seconds=max_lifetime,
    )


def _arg_after(argv: list[str], name: str) -> str:
    try:
        index = argv.index(name)
    except ValueError:
        return ""
    return argv[index + 1] if index + 1 < len(argv) else ""


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _proc_observation(proc_root: Path, pid: int) -> tuple[list[str], int, float] | None:
    base = proc_root / str(pid)
    try:
        argv = [item.decode("utf-8", "replace") for item in (base / "cmdline").read_bytes().split(b"\0") if item]
        stat = (base / "stat").read_text(encoding="utf-8")
        uptime = float((proc_root / "uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None
    if not argv or ")" not in stat:
        return None
    rest = stat[stat.rfind(")") + 2 :].split()
    if len(rest) <= 19:
        return None
    try:
        ppid = int(rest[1])
        start_ticks = int(rest[19])
        hz = int(os.sysconf("SC_CLK_TCK"))
    except (ValueError, OSError):
        return None
    return argv, ppid, max(0.0, uptime - (start_ticks / hz))


def discover_managed_process_lifecycle(
    *, proc_root: str | Path = "/proc", now: datetime | None = None
) -> tuple[ProcessLifecycleDiagnosticV1, ...]:
    """Discover only Harness-owned/proof/smoke process shapes; never mutates them."""
    root = Path(proc_root)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ProcessLifecycleDiagnosticError("timezone-aware now is required")
    if not root.is_dir():
        raise ProcessLifecycleDiagnosticError("proc root is unavailable")
    rows: list[ProcessLifecycleDiagnosticV1] = []
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        observed = _proc_observation(root, pid)
        if observed is None:
            continue
        argv, ppid, age = observed
        command = " ".join(argv)
        facts: dict[str, Any] | None = None
        if "runtime.orchestrator.production_full_plan_entry" in command and "--job" in argv:
            job_path = Path(_arg_after(argv, "--job")).expanduser()
            job = _read_json(job_path)
            state_path: Path | None = None
            lock_path: Path | None = None
            state: dict[str, Any] = {}
            if job:
                state_root = str(job.get("harness_state_root") or job.get("harness_root") or "")
                project_id = str(job.get("project_id") or "")
                run_id = str(job.get("run_id") or "")
                if state_root and project_id and run_id:
                    base = Path(state_root).expanduser().resolve() / "_workspace" / "production-full-plan" / project_id / run_id
                    state_path = base / "state.json"
                    lock_path = base / "supervisor.lock"
                    state = _read_json(state_path)
            terminal = str(state.get("state") or "") in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
            facts = {
                "pid": pid,
                "owner_ref": str(job_path),
                "owner_state_exists": bool(state_path and state_path.is_file()),
                "lock_exists": bool(lock_path and lock_path.exists()),
                "expected_lifecycle_state": str(state.get("state") or "FULL_PLAN"),
                "last_semantic_progress": str(state.get("last_semantic_progress_at") or state.get("last_progress_at") or ""),
                "process_kind": "FULL_PLAN",
                "age_seconds": age,
                "max_lifetime_seconds": 120.0 if terminal else None,
                "parent_pid": ppid,
            }
        elif "runtime.orchestrator.host_runner_entry" in command and "--socket" in argv:
            socket_path = _arg_after(argv, "--socket")
            ledger_path = _arg_after(argv, "--ledger")
            timeout_text = _arg_after(argv, "--timeout")
            try:
                timeout = float(timeout_text) if timeout_text else 1800.0
            except ValueError:
                timeout = 1800.0
            facts = {
                "pid": pid,
                "owner_ref": ledger_path or socket_path or command[:512],
                "owner_state_exists": bool(ledger_path and Path(ledger_path).expanduser().exists()),
                "lock_exists": bool(socket_path and Path(socket_path).expanduser().exists()),
                "expected_lifecycle_state": "HOST_GATEWAY_LISTENER",
                "last_semantic_progress": "",
                "process_kind": "HOST_GATEWAY",
                "age_seconds": age,
                "max_lifetime_seconds": max(30.0, timeout + 60.0),
                "parent_pid": ppid,
            }
        elif "ai-office-dashboard" in command and any(arg.startswith("/tmp/") for arg in argv):
            owner = next((arg for arg in argv if arg.startswith("/tmp/")), command[:512])
            facts = {
                "pid": pid,
                "owner_ref": owner,
                "owner_state_exists": False,
                "lock_exists": False,
                "expected_lifecycle_state": "TEMPORARY_SMOKE",
                "last_semantic_progress": "",
                "process_kind": "AI_OFFICE_SMOKE",
                "age_seconds": age,
                "max_lifetime_seconds": 3600.0,
                "parent_pid": ppid,
            }
        if facts is not None:
            rows.append(diagnose_process_lifecycle(facts, now=current))
    return tuple(sorted(rows, key=lambda item: item.pid))


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def process_lifecycle_latest_path(state_root: str | Path) -> Path:
    return Path(state_root).expanduser().resolve() / "_workspace" / "operations-health" / "process-lifecycle-latest.json"


def record_process_lifecycle_snapshot(
    state_root: str | Path,
    *,
    diagnostics: tuple[ProcessLifecycleDiagnosticV1, ...] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    root = Path(state_root).expanduser().resolve()
    rows = diagnostics if diagnostics is not None else discover_managed_process_lifecycle()
    unsigned = {
        "schema_version": "orchestration.process-lifecycle-snapshot.v1",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "blocking_count": sum(1 for item in rows if item.status != "OWNED"),
        "diagnostics": [asdict(item) for item in rows],
    }
    payload = {**unsigned, "snapshot_sha256": _digest(unsigned)}
    base = root / "_workspace" / "operations-health" / "process-lifecycle"
    base.mkdir(parents=True, exist_ok=True)
    immutable = base / f"{payload['snapshot_sha256']}.json"
    if not immutable.exists():
        atomic_write_json(immutable, payload)
    latest = process_lifecycle_latest_path(root)
    latest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(latest, payload)
    return payload


def load_process_lifecycle_snapshot(
    path: str | Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 180,
) -> dict[str, Any]:
    if stale_after_seconds <= 0:
        raise ProcessLifecycleDiagnosticError("process lifecycle stale threshold must be positive")
    source = Path(path).expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot is missing or unsafe")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "orchestration.process-lifecycle-snapshot.v1":
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot schema mismatch")
    unsigned = {key: item for key, item in value.items() if key != "snapshot_sha256"}
    if str(value.get("snapshot_sha256") or "") != _digest(unsigned):
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot digest mismatch")
    try:
        observed = datetime.fromisoformat(str(value.get("observed_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot timestamp invalid") from exc
    if observed.tzinfo is None:
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot timestamp is naive")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - observed.astimezone(timezone.utc)).total_seconds()
    if age < -5 or age > stale_after_seconds:
        raise ProcessLifecycleDiagnosticError("process lifecycle snapshot is stale")
    diagnostics = value.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise ProcessLifecycleDiagnosticError("process lifecycle diagnostics are invalid")
    blocking = sum(
        1 for item in diagnostics
        if isinstance(item, Mapping) and str(item.get("status") or "") != "OWNED"
    )
    if blocking != value.get("blocking_count"):
        raise ProcessLifecycleDiagnosticError("process lifecycle blocking count mismatch")
    return value
