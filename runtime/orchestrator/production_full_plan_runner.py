"""Durable cross-Gate FULL_PLAN supervisor.

This module intentionally sits above the single-Gate production runner.  It
owns only cross-Gate continuity: durable dispatch intent, queue/lease state,
timeout/fencing, retry escalation, and startup reconciliation.  Gate meaning
and mutation authority stay in the existing Gate/Full MCP layers.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import multiprocessing as mp
import os
import signal
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .durable_io import DurableIOError, atomic_write_bytes, durable_json_save, resource_snapshot
from .production_attention import AttentionOutbox


SCHEMA_VERSION = "orchestration.production-full-plan.v1"
ACTIVE_STATES = frozenset({"READY", "DISPATCHED", "RUNNING", "VERIFYING", "RECOVERING"})
WAIT_STATES = frozenset({"WAITING_APPROVAL", "WAITING_PROVIDER", "WAITING_RESOURCE"})
TERMINAL_STATES = frozenset({"BLOCKED", "FAILED", "COMPLETED", "CANCELLED"})
ALL_STATES = ACTIVE_STATES | WAIT_STATES | TERMINAL_STATES
QUEUE_STATES = frozenset({"READY", "DISPATCHED", "RUNNING", "COMPLETED", "BLOCKED", "CANCELLED"})


class ProductionFullPlanError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160 or "/" in value or "\\" in value or ".." in value:
        raise ProductionFullPlanError(f"unsafe {label}")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _failure_class(reason: object) -> str:
    text = str(reason or "")
    artifact_markers = (
        "EVIDENCE_PUBLICATION_INVALID", "WORKER_REQUEST_REQUIRED",
        "worker.request.json", "package manifest", "evidence lineage", "recovery binding",
    )
    provider_markers = ("BLOCKED_BY_PROVIDER", "NO_ELIGIBLE_PROVIDER", "WAITING_PROVIDER", "PROVIDER_")
    if any(marker in text for marker in artifact_markers):
        return "ARTIFACT_CONTRACT_FAILURE"
    if any(marker in text for marker in provider_markers):
        return "PROVIDER_FAILURE"
    return "EXECUTION_FAILURE"


def _unsigned(state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "state_sha256"}


def _seal(state: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(state)
    value["state_sha256"] = _digest(_unsigned(value))
    return value


def _validate_state(state: Mapping[str, Any], *, project_id: str, run_id: str, gates: Sequence[str]) -> dict[str, Any]:
    value = dict(state)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ProductionFullPlanError("incompatible Full Plan state schema")
    if value.get("project_id") != project_id or value.get("run_id") != run_id or value.get("gates") != list(gates):
        raise ProductionFullPlanError("Full Plan state binding mismatch")
    if value.get("state") not in ALL_STATES:
        raise ProductionFullPlanError("invalid Full Plan state")
    digest = value.get("state_sha256")
    if not isinstance(digest, str) or digest != _digest(_unsigned(value)):
        raise ProductionFullPlanError("Full Plan state digest mismatch")
    completed = value.get("completed_gates")
    if not isinstance(completed, list) or completed != list(gates[: len(completed)]):
        raise ProductionFullPlanError("completed Gate order mismatch")
    queue = value.get("queue")
    if not isinstance(queue, list):
        raise ProductionFullPlanError("durable queue is missing")
    ids: set[str] = set()
    for item in queue:
        if not isinstance(item, dict) or item.get("status") not in QUEUE_STATES:
            raise ProductionFullPlanError("durable queue item is invalid")
        key = item.get("idempotency_key")
        if not isinstance(key, str) or not key or key in ids:
            raise ProductionFullPlanError("queue idempotency binding is invalid")
        ids.add(key)
    return value


def _set_parent_death_signal() -> None:
    """On Linux, ensure an isolated Gate child dies with its supervisor parent."""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        parent = os.getppid()
        if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM) != 0:
            return
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        # Absence of prctl is not success evidence; parent-side lease/reconcile
        # still treats an interrupted child as recovery-required.
        return


def _child_entry(connection: Any, executor: Callable[[str, str, bool], Mapping[str, Any]],
                 gate_id: str, gate_run_id: str, resume: bool) -> None:
    _set_parent_death_signal()
    try:
        result = dict(executor(gate_id, gate_run_id, resume))
        connection.send(("OK", result))
    except BaseException as exc:  # child boundary must classify every failure
        connection.send(("ERROR", {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(limit=20),
        }))
    finally:
        connection.close()


@dataclass(frozen=True)
class FullPlanResult:
    status: str
    state: dict[str, Any]
    executed_gates: tuple[str, ...]
    recovered_on_startup: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "state": self.state,
            "executed_gates": list(self.executed_gates),
            "recovered_on_startup": self.recovered_on_startup,
            "hard_stop": self.status in WAIT_STATES | TERMINAL_STATES,
        }


class DurableFullPlanSupervisor:
    """Own cross-Gate continuation without becoming a Gate/action authority."""

    def __init__(self, harness_root: str | Path, *, project_id: str, run_id: str,
                 gates: Sequence[str], retry_budget: int = 2, gate_timeout_seconds: float = 3600.0,
                 heartbeat_seconds: float = 5.0, lease_seconds: float = 20.0,
                 min_disk_free_bytes: int = 64 * 1024 * 1024, min_inode_free: int = 1024,
                 min_memory_available_bytes: int = 128 * 1024 * 1024,
                 max_cpu_load_per_cpu_milli: int = 2500,
                 max_io_pressure_full_avg10_milli: int = 50000,
                 max_queue_depth: int = 64,
                 resource_probe: Callable[[str | Path], Mapping[str, int]] | None = None):
        root = Path(harness_root).resolve()
        if not root.is_dir() or root.is_symlink():
            raise ProductionFullPlanError("unsafe harness root")
        self.root = root
        self.project_id = _safe_id(project_id, "project ID")
        self.run_id = _safe_id(run_id, "run ID")
        self.gates = tuple(_safe_id(gate, "Gate ID") for gate in gates)
        if not self.gates or len(set(self.gates)) != len(self.gates):
            raise ProductionFullPlanError("Full Plan Gate order is empty or duplicated")
        if retry_budget < 0 or gate_timeout_seconds <= 0 or heartbeat_seconds <= 0 or lease_seconds <= heartbeat_seconds:
            raise ProductionFullPlanError("invalid Full Plan runtime policy")
        self.retry_budget = retry_budget
        self.gate_timeout_seconds = float(gate_timeout_seconds)
        self.heartbeat_seconds = float(heartbeat_seconds)
        self.lease_seconds = float(lease_seconds)
        self.min_disk_free_bytes = int(min_disk_free_bytes)
        self.min_inode_free = int(min_inode_free)
        self.min_memory_available_bytes = int(min_memory_available_bytes)
        self.max_cpu_load_per_cpu_milli = int(max_cpu_load_per_cpu_milli)
        self.max_io_pressure_full_avg10_milli = int(max_io_pressure_full_avg10_milli)
        self.max_queue_depth = int(max_queue_depth)
        if min(self.min_disk_free_bytes, self.min_inode_free, self.min_memory_available_bytes, self.max_queue_depth) < 0:
            raise ProductionFullPlanError("invalid resource budget")
        self.resource_probe = resource_probe or resource_snapshot
        base = root / "_workspace" / "production-full-plan" / self.project_id / self.run_id
        self.base = base
        self.state_path = base / "state.json"
        self.events_path = base / "events.jsonl"
        self.alert_path = base / "alerts.jsonl"
        self.lock_path = base / "supervisor.lock"
        self.attention_outbox = AttentionOutbox(base, project_id=self.project_id, run_id=self.run_id)

    def _queue_item(self, gate_id: str, sequence: int, *, attempt: int = 1, resume: bool = False) -> dict[str, Any]:
        gate_run_id = f"{self.run_id}--{gate_id.lower()}"
        identity = {"run_id": self.run_id, "gate_id": gate_id, "sequence": sequence}
        return {
            "gate_id": gate_id,
            "gate_run_id": gate_run_id,
            "sequence": sequence,
            "attempt": attempt,
            "resume": resume,
            "status": "READY",
            "idempotency_key": _digest(identity),
            "created_at": _now(),
            "last_error": None,
        }

    def _initial(self) -> dict[str, Any]:
        state = {
            "schema_version": SCHEMA_VERSION,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "mode": "FULL_PLAN",
            "gates": list(self.gates),
            "completed_gates": [],
            "current_gate": self.gates[0],
            "state": "READY",
            "queue": [self._queue_item(self.gates[0], 0)],
            "lease": None,
            "epoch": 0,
            "dead_letter": [],
            "last_progress_at": _now(),
            "last_error": None,
            "recovery_count": 0,
            "terminal_reason": None,
        }
        return _seal(state)

    def _load_candidate(self, path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise ProductionFullPlanError("unsafe Full Plan state generation")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductionFullPlanError("corrupt Full Plan state generation") from exc
        if not isinstance(value, dict):
            raise ProductionFullPlanError("Full Plan state generation is not an object")
        return _validate_state(value, project_id=self.project_id, run_id=self.run_id, gates=self.gates)

    def load(self) -> tuple[dict[str, Any], bool]:
        if not self.state_path.exists() and not self.state_path.with_suffix(".json.prev").exists():
            return self._initial(), False
        errors: list[str] = []
        for recovered, candidate in ((False, self.state_path), (True, self.state_path.with_suffix(".json.prev"))):
            if not candidate.exists():
                continue
            try:
                return self._load_candidate(candidate), recovered
            except ProductionFullPlanError as exc:
                errors.append(str(exc))
        raise ProductionFullPlanError("no valid Full Plan state generation: " + "; ".join(errors))

    def _append_line(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(payload)
        row.setdefault("occurred_at", _now())
        row["event_sha256"] = _digest({key: value for key, value in row.items() if key != "event_sha256"})
        data = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(str(path), flags, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _persist(self, state: dict[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
        state["last_progress_at"] = _now()
        sealed = _seal(state)
        durable_json_save(self.state_path, sealed)
        self._append_line(self.events_path, {**dict(event), "state_sha256": sealed["state_sha256"]})
        return sealed

    def _alert(self, kind: str, state: Mapping[str, Any], **extra: Any) -> None:
        reason = str(extra.get("reason") or state.get("last_error") or kind)
        gate_id = extra.get("gate_id")
        self._append_line(self.alert_path, {"alert": kind, "run_id": self.run_id,
                                           "state": state.get("state"), **extra})
        safe_details = {
            key: value for key, value in extra.items()
            if key in {"attempt", "next_attempt", "resources", "wait_state"}
        }
        self.attention_outbox.publish(
            kind=kind, state=str(state.get("state") or "UNKNOWN"), reason=reason,
            gate_id=str(gate_id) if gate_id else None,
            state_sha256=str(state.get("state_sha256") or "") or None,
            details=safe_details,
        )

    def _acquire_run_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(str(self.lock_path), flags, 0o600)
        except OSError as exc:
            raise ProductionFullPlanError("unsafe Full Plan supervisor lock") from exc
        handle = os.fdopen(fd, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise ProductionFullPlanError("duplicate Full Plan supervisor is active") from exc
        return handle

    @staticmethod
    def _release_run_lock(handle: Any) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _active_item(self, state: Mapping[str, Any]) -> dict[str, Any] | None:
        for item in state.get("queue", []):
            if item.get("status") not in {"COMPLETED", "BLOCKED", "CANCELLED"}:
                return item
        return None

    def _resource_gate(self, state: Mapping[str, Any] | None = None) -> tuple[bool, dict[str, int]]:
        snapshot = dict(self.resource_probe(self.root))
        disk = int(snapshot.get("disk_free_bytes", -1))
        inodes = int(snapshot.get("inode_free", -1))
        memory = int(snapshot.get("memory_available_bytes", -1))
        cpu = int(snapshot.get("cpu_load_per_cpu_milli", -1))
        io_pressure = int(snapshot.get("io_pressure_full_avg10_milli", -1))
        queue_depth = len([item for item in (state or {}).get("queue", [])
                           if item.get("status") not in {"COMPLETED", "BLOCKED", "CANCELLED"}])
        snapshot["active_queue_depth"] = queue_depth
        checks = [
            disk < 0 or disk >= self.min_disk_free_bytes,
            inodes < 0 or inodes >= self.min_inode_free,
            memory < 0 or memory >= self.min_memory_available_bytes,
            cpu < 0 or cpu <= self.max_cpu_load_per_cpu_milli,
            io_pressure < 0 or io_pressure <= self.max_io_pressure_full_avg10_milli,
            queue_depth <= self.max_queue_depth,
        ]
        return all(checks), snapshot

    def reconcile_startup(self) -> tuple[dict[str, Any], bool]:
        state, recovered_generation = self.load()
        changed = recovered_generation
        if recovered_generation:
            state["recovery_count"] = int(state.get("recovery_count", 0)) + 1
            state["state"] = "RECOVERING"
            state["last_error"] = "PRIMARY_STATE_INVALID_PREVIOUS_GOOD_RESTORED"
        if state.get("state") in {"DISPATCHED", "RUNNING", "VERIFYING"}:
            item = self._active_item(state)
            if item is None:
                state["state"] = "BLOCKED"
                state["last_error"] = "ACTIVE_RUN_QUEUE_MISSING"
                state["terminal_reason"] = "STARTUP_RECONCILIATION_BLOCKED"
                state["lease"] = None
                state = self._persist(state, {"event": "STARTUP_RECONCILIATION_BLOCKED",
                                              "reason": "ACTIVE_RUN_QUEUE_MISSING"})
                self._alert("STARTUP_RECONCILIATION_BLOCKED", state, reason="ACTIVE_RUN_QUEUE_MISSING")
                return state, True
            item["status"] = "READY"
            item["resume"] = True
            item["attempt"] = int(item.get("attempt", 1)) + 1
            item["last_error"] = "SUPERVISOR_RESTART_RECONCILIATION"
            state["lease"] = None
            state["state"] = "RECOVERING"
            state["recovery_count"] = int(state.get("recovery_count", 0)) + 1
            changed = True
        if changed:
            state = self._persist(state, {"event": "STARTUP_RECONCILIATION",
                                          "recovered_previous_generation": recovered_generation})
        return state, changed

    def _classify_gate_result(self, result: Mapping[str, Any]) -> tuple[str, str | None]:
        status = str(result.get("status", ""))
        if status in {"GATE_EXIT", "COMPLETED", "PASS"}:
            next_action = result.get("next")
            if isinstance(next_action, Mapping) and next_action.get("action") == "WAIT_FOR_NEXT_GATE_USER_APPROVAL":
                return "WAITING_APPROVAL", "GATE_REQUIRES_USER_APPROVAL"
            return "COMPLETED", None
        if status == "GATE_EXECUTION_RESUME_REQUIRED":
            return "FAILED", "GATE_EXECUTION_RESUME_REQUIRED"
        if status in WAIT_STATES | TERMINAL_STATES:
            return status, str(result.get("reason") or result.get("error") or status)
        if status in {"BLOCK", "BLOCKED_BY_PROVIDER", "NO_ELIGIBLE_PROVIDER"}:
            return "WAITING_PROVIDER", str(result.get("reason") or status)
        return "FAILED", f"UNRECOGNIZED_GATE_RESULT:{status or 'EMPTY'}"

    def _handle_failure(self, state: dict[str, Any], item: dict[str, Any], reason: str,
                        *, wait_state: str | None = None) -> dict[str, Any]:
        item["last_error"] = reason
        state["last_error"] = reason
        state["lease"] = None
        failure_class = _failure_class(reason)
        if wait_state in WAIT_STATES:
            item["status"] = "READY"
            item["resume"] = True
            state["state"] = wait_state
            state = self._persist(state, {"event": wait_state, "gate_id": item["gate_id"],
                                          "reason": reason, "failure_class": failure_class})
            self._alert(wait_state, state, gate_id=item["gate_id"], reason=reason)
            return state
        attempt = int(item.get("attempt", 1))
        # Artifact/evidence contract failures must never blindly rerun a worker.
        # They require an explicit evidence-preserving recovery path.
        if failure_class == "ARTIFACT_CONTRACT_FAILURE":
            item["status"] = "BLOCKED"
            dead = {"gate_id": item["gate_id"], "gate_run_id": item["gate_run_id"],
                    "attempt": attempt, "reason": reason, "failure_class": failure_class,
                    "idempotency_key": item["idempotency_key"], "quarantined_at": _now()}
            state.setdefault("dead_letter", []).append(dead)
            state["state"] = "BLOCKED"
            state["terminal_reason"] = "ARTIFACT_CONTRACT_RECOVERY_REQUIRED"
            state = self._persist(state, {"event": "ARTIFACT_CONTRACT_BLOCKED", **dead})
            self._alert("ARTIFACT_CONTRACT_BLOCKED", state, gate_id=item["gate_id"], reason=reason)
            return state
        if attempt <= self.retry_budget:
            item["attempt"] = attempt + 1
            item["resume"] = True
            item["status"] = "READY"
            state["state"] = "RECOVERING"
            state["recovery_count"] = int(state.get("recovery_count", 0)) + 1
            return self._persist(state, {"event": "RETRY_ENQUEUED", "gate_id": item["gate_id"],
                                         "reason": reason, "failure_class": failure_class,
                                         "next_attempt": item["attempt"]})
        item["status"] = "BLOCKED"
        dead = {"gate_id": item["gate_id"], "gate_run_id": item["gate_run_id"],
                "attempt": attempt, "reason": reason, "failure_class": failure_class,
                "idempotency_key": item["idempotency_key"], "quarantined_at": _now()}
        state.setdefault("dead_letter", []).append(dead)
        state["state"] = "BLOCKED"
        state["terminal_reason"] = "RETRY_BUDGET_EXHAUSTED"
        state = self._persist(state, {"event": "DEAD_LETTER", **dead})
        self._alert("DEAD_LETTER", state, gate_id=item["gate_id"], reason=reason)
        return state

    def _run_gate_process(self, state: dict[str, Any], item: dict[str, Any],
                          executor: Callable[[str, str, bool], Mapping[str, Any]]) -> tuple[str, Mapping[str, Any]]:
        ctx = mp.get_context("fork")
        parent, child = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_child_entry, args=(child, executor, item["gate_id"], item["gate_run_id"], bool(item.get("resume"))))
        process.start()
        child.close()
        state["lease"] = {
            "epoch": int(state.get("epoch", 0)) + 1,
            "gate_id": item["gate_id"],
            "worker_pid": process.pid,
            "claimed_at": _now(),
            "heartbeat_at": _now(),
            "lease_seconds": self.lease_seconds,
        }
        state["epoch"] = state["lease"]["epoch"]
        state["state"] = "RUNNING"
        item["status"] = "RUNNING"
        self._persist(state, {"event": "WORKER_STARTED", "gate_id": item["gate_id"],
                              "worker_pid": process.pid, "epoch": state["epoch"]})
        started = time.monotonic()
        last_heartbeat = started
        while process.is_alive():
            elapsed = time.monotonic() - started
            if elapsed >= self.gate_timeout_seconds:
                process.terminate()
                process.join(timeout=2.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2.0)
                parent.close()
                return "TIMEOUT", {"reason": "GATE_EXECUTION_TIMEOUT", "elapsed_seconds": elapsed}
            now = time.monotonic()
            if now - last_heartbeat >= self.heartbeat_seconds:
                lease = dict(state.get("lease") or {})
                lease["heartbeat_at"] = _now()
                state["lease"] = lease
                self._persist(state, {"event": "HEARTBEAT", "gate_id": item["gate_id"],
                                      "worker_pid": process.pid, "epoch": state["epoch"]})
                last_heartbeat = now
            process.join(timeout=min(0.2, self.heartbeat_seconds))
        process.join(timeout=1.0)
        if parent.poll(0.2):
            kind, payload = parent.recv()
            parent.close()
            return str(kind), dict(payload)
        parent.close()
        return "ERROR", {"exception_type": "WorkerProcessExit", "message": f"exitcode={process.exitcode}"}

    def run(self, executor: Callable[[str, str, bool], Mapping[str, Any]], *,
            preflight: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None) -> FullPlanResult:
        handle = self._acquire_run_lock()
        try:
            return self._run_locked(executor, preflight=preflight)
        finally:
            self._release_run_lock(handle)

    def _run_locked(self, executor: Callable[[str, str, bool], Mapping[str, Any]], *,
                    preflight: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None) -> FullPlanResult:
        state, recovered = self.reconcile_startup()
        executed: list[str] = []
        while state["state"] not in WAIT_STATES | TERMINAL_STATES:
            item = self._active_item(state)
            if item is None:
                if len(state["completed_gates"]) == len(self.gates):
                    state["state"] = "COMPLETED"
                    state["terminal_reason"] = "ALL_GATES_COMPLETED"
                    state = self._persist(state, {"event": "FULL_PLAN_COMPLETED"})
                    break
                state["state"] = "BLOCKED"
                state["last_error"] = "ELIGIBLE_SUCCESSOR_MISSING"
                state["terminal_reason"] = "DURABLE_SUCCESSOR_MISSING"
                state = self._persist(state, {"event": "DURABLE_SUCCESSOR_MISSING",
                                              "completed_gates": list(state["completed_gates"])})
                self._alert("DURABLE_SUCCESSOR_MISSING", state, reason="ELIGIBLE_SUCCESSOR_MISSING")
                break
            resources_ok, snapshot = self._resource_gate(state)
            if not resources_ok:
                state["state"] = "WAITING_RESOURCE"
                state["last_error"] = "LOW_RESOURCE_BACKPRESSURE"
                state = self._persist(state, {"event": "WAITING_RESOURCE", "resources": snapshot,
                                              "gate_id": item["gate_id"]})
                self._alert("WAITING_RESOURCE", state, resources=snapshot, gate_id=item["gate_id"])
                break
            if preflight is not None:
                verdict = dict(preflight({"state": state, "queue_item": dict(item), "resources": snapshot}))
                if verdict.get("status") != "PASS":
                    wait_state = str(verdict.get("state", "BLOCKED"))
                    reason = str(verdict.get("reason", "PREFLIGHT_BLOCKED"))
                    if wait_state in WAIT_STATES:
                        state = self._handle_failure(state, item, reason, wait_state=wait_state)
                    else:
                        item["status"] = "BLOCKED"
                        state["state"] = "BLOCKED"
                        state["last_error"] = reason
                        state["terminal_reason"] = "PREFLIGHT_BLOCKED"
                        state = self._persist(state, {"event": "PREFLIGHT_BLOCKED", "reason": reason,
                                                      "gate_id": item["gate_id"]})
                        self._alert("PREFLIGHT_BLOCKED", state, gate_id=item["gate_id"], reason=reason)
                    break
            item["status"] = "DISPATCHED"
            state["state"] = "DISPATCHED"
            state = self._persist(state, {"event": "DISPATCH_INTENT_COMMITTED", "gate_id": item["gate_id"],
                                          "idempotency_key": item["idempotency_key"], "attempt": item["attempt"]})
            kind, payload = self._run_gate_process(state, item, executor)
            if kind != "OK":
                reason = str(payload.get("reason") or payload.get("message") or kind)
                state = self._handle_failure(state, item, reason)
                if state["state"] == "RECOVERING":
                    continue
                break
            state["state"] = "VERIFYING"
            state = self._persist(state, {"event": "GATE_RESULT_RECEIVED", "gate_id": item["gate_id"],
                                          "result_digest": _digest(payload)})
            classification, reason = self._classify_gate_result(payload)
            if classification != "COMPLETED":
                if classification in WAIT_STATES:
                    state = self._handle_failure(state, item, reason or classification, wait_state=classification)
                elif classification == "CANCELLED":
                    item["status"] = "CANCELLED"; state["state"] = "CANCELLED"; state["terminal_reason"] = reason
                    state = self._persist(state, {"event": "CANCELLED", "gate_id": item["gate_id"], "reason": reason})
                else:
                    state = self._handle_failure(state, item, reason or classification)
                if state["state"] == "RECOVERING":
                    continue
                break
            # Atomic handoff: Gate completion and successor dispatch intent are
            # one canonical state generation.  A crash after this write cannot
            # lose the next eligible Gate.
            item["status"] = "COMPLETED"
            if item["gate_id"] not in state["completed_gates"]:
                state["completed_gates"].append(item["gate_id"])
            executed.append(item["gate_id"])
            state["lease"] = None
            state["last_error"] = None
            if len(state["completed_gates"]) == len(self.gates):
                state["state"] = "COMPLETED"
                state["current_gate"] = None
                state["terminal_reason"] = "ALL_GATES_COMPLETED"
                state = self._persist(state, {"event": "FULL_PLAN_COMPLETED", "gate_id": item["gate_id"]})
                break
            next_gate = self.gates[len(state["completed_gates"])]
            state["current_gate"] = next_gate
            state["queue"].append(self._queue_item(next_gate, len(state["completed_gates"])))
            state["state"] = "READY"
            state = self._persist(state, {"event": "GATE_COMPLETED_AND_SUCCESSOR_ENQUEUED",
                                          "completed_gate": item["gate_id"], "next_gate": next_gate,
                                          "next_idempotency_key": state["queue"][-1]["idempotency_key"]})
        return FullPlanResult(str(state["state"]), state, tuple(executed), recovered)

    def resume_recoverable_block(self, *, expected_failure_class: str = "ARTIFACT_CONTRACT_FAILURE") -> dict[str, Any]:
        """Explicitly reopen a blocked run only after an evidence-preserving repair exists."""
        if expected_failure_class != "ARTIFACT_CONTRACT_FAILURE":
            raise ProductionFullPlanError("unsupported blocked recovery class")
        handle = self._acquire_run_lock()
        try:
            state, _ = self.load()
            if state.get("state") != "BLOCKED":
                raise ProductionFullPlanError("Full Plan run is not blocked")
            reason = str(state.get("last_error") or "")
            if _failure_class(reason) != expected_failure_class:
                raise ProductionFullPlanError("blocked failure class mismatch")
            candidates = [item for item in state.get("queue", []) if item.get("status") == "BLOCKED"]
            if len(candidates) != 1:
                raise ProductionFullPlanError("blocked recovery requires exactly one quarantined queue item")
            item = candidates[0]
            item["status"] = "READY"
            item["resume"] = True
            item["attempt"] = int(item.get("attempt", 1)) + 1
            item["last_error"] = None
            state["state"] = "RECOVERING"
            state["terminal_reason"] = None
            state["last_error"] = None
            state["lease"] = None
            state["recovery_count"] = int(state.get("recovery_count", 0)) + 1
            return self._persist(state, {"event":"EXPLICIT_ARTIFACT_RECOVERY_RESUME",
                                         "gate_id":item["gate_id"], "attempt":item["attempt"],
                                         "failure_class":expected_failure_class})
        finally:
            self._release_run_lock(handle)

    def resume_wait(self, expected_state: str) -> dict[str, Any]:
        handle = self._acquire_run_lock()
        try:
            return self._resume_wait_locked(expected_state)
        finally:
            self._release_run_lock(handle)

    def _resume_wait_locked(self, expected_state: str) -> dict[str, Any]:
        if expected_state not in WAIT_STATES:
            raise ProductionFullPlanError("resume_wait requires an explicit wait state")
        state, _ = self.load()
        if state.get("state") != expected_state:
            raise ProductionFullPlanError("Full Plan wait-state mismatch")
        item = self._active_item(state)
        if item is None:
            raise ProductionFullPlanError("wait state has no queue item")
        item["status"] = "READY"
        item["resume"] = True
        state["state"] = "RECOVERING"
        state["last_error"] = None
        return self._persist(state, {"event": "WAIT_RESUMED", "from_state": expected_state,
                                     "gate_id": item["gate_id"]})

    def cancel(self, reason: str) -> dict[str, Any]:
        handle = self._acquire_run_lock()
        try:
            return self._cancel_locked(reason)
        finally:
            self._release_run_lock(handle)

    def _cancel_locked(self, reason: str) -> dict[str, Any]:
        state, _ = self.load()
        item = self._active_item(state)
        if item is not None:
            item["status"] = "CANCELLED"
        state["state"] = "CANCELLED"
        state["terminal_reason"] = reason or "USER_CANCELLED"
        state["lease"] = None
        return self._persist(state, {"event": "CANCELLED", "reason": state["terminal_reason"]})


def run_production_full_plan(*, harness_root: str | Path, project_id: str, run_id: str,
                             gates: Sequence[str], executor: Callable[[str, str, bool], Mapping[str, Any]],
                             **policy: Any) -> dict[str, Any]:
    """Real production entrypoint for cross-Gate FULL_PLAN continuation."""
    supervisor = DurableFullPlanSupervisor(harness_root, project_id=project_id, run_id=run_id,
                                           gates=gates, **policy)
    return supervisor.run(executor).to_dict()
