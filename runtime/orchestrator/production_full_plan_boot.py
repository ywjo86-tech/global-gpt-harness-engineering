"""Boot-time one-shot reconciliation for durable authorized FULL_PLAN jobs."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .production_full_plan_entry import (
    load_job, load_registered_job, recover_registered_job_state_after_external_binding_drift, transient_systemd_command,
)
from .production_run_authority import AUTO_RECONCILE_OWNER, RunAuthorityError, resolve_execution_owner
from .runtime_migration_handoff import MigrationHandoffError, MigrationPhase, discover_predecessor_transactions
from .production_full_plan_runner import ACTIVE_STATES, TERMINAL_STATES, WAIT_STATES, DurableFullPlanSupervisor, ProductionFullPlanError
from .production_attention import AttentionOutbox
from .harness_state_root import discovery_roots, job_dedupe_key, job_state_root
from .wait_recovery import (
    WaitRecoveryError, classify_wait_recovery, evaluate_provider_wait_recovery,
    evaluate_resource_wait_recovery, load_active_provider_wait_recovery_evidence,
)


class FullPlanBootError(ValueError):
    pass


def _unit_name(project_id: str, run_id: str) -> str:
    raw = f"fullplan-{project_id}-{run_id}"
    value = re.sub(r"[^A-Za-z0-9_.@-]", "-", raw)
    return value[:220]


def _systemd_env() -> dict[str, str]:
    uid = os.getuid()
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def _unit_active(unit: str) -> bool:
    completed = subprocess.run(
        ["systemctl", "--user", "is-active", unit], capture_output=True, text=True,
        check=False, timeout=10, env=_systemd_env(),
    )
    return completed.stdout.strip() in {"active", "activating", "reloading"}


def _execution_owner_gate(job_path: str | Path, job: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        execution_owner = resolve_execution_owner(job)
    except RunAuthorityError as exc:
        return {
            "job": str(job_path),
            "action": "BLOCKED",
            "state": "UNKNOWN",
            "reason": str(exc),
            "launched": False,
        }
    if execution_owner != AUTO_RECONCILE_OWNER:
        return {
            "job": str(job_path),
            "action": "SKIP_EXTERNAL_OWNER",
            "state": "UNREAD",
            "execution_owner": execution_owner,
            "launched": False,
        }
    return None


def discover_registered_jobs(search_root: str | Path, *, legacy_roots: tuple[str | Path, ...] = ()) -> list[Path]:
    found: list[Path] = []
    seen: set[tuple[str, str, str]] = set()
    for root in discovery_roots(search_root, legacy_roots):
        if not root.is_dir():
            continue
        for path in root.rglob("*.job.json"):
            if "production-full-plan-jobs" not in path.parts or path.is_symlink() or not path.is_file():
                continue
            try:
                job = load_job(path)
            except Exception:
                key = ("INVALID", str(path.resolve()), "")
            else:
                key = job_dedupe_key(job, source_path=path)
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def discover_jobs(harness_root: str | Path) -> list[Path]:
    # Backward-compatible alias for recursive registered-job discovery.
    return discover_registered_jobs(harness_root)


def _migration_successor_is_registered(job: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    if state.get("migration_successor_verified") is not True:
        return False
    successor_run_id = str(state.get("migration_successor_run_id") or "")
    successor_sha = str(state.get("migration_successor_state_sha256") or "")
    if not successor_run_id or len(successor_sha) != 64:
        return False
    path = job_state_root(job) / "_workspace" / "production-full-plan-jobs" / str(job["project_id"]) / f"{successor_run_id}.job.json"
    if path.is_symlink() or not path.is_file():
        return False
    try:
        successor = load_registered_job(path)
        if successor.get("project_id") != job.get("project_id") or successor.get("run_id") != successor_run_id:
            return False
        gates = [str(item["gate_id"]) for item in successor["gates"]]
        sup = DurableFullPlanSupervisor(
            job_state_root(successor), project_id=successor["project_id"], run_id=successor["run_id"], gates=gates,
            authority_core_sha256=str(successor.get("authority_core_sha256") or ""), **dict(successor.get("policy") or {}),
        )
        return sup.state_path.is_file() and not sup.state_path.is_symlink()
    except Exception:
        return False


def _incomplete_migrations(job: Mapping[str, Any]):
    rows = discover_predecessor_transactions(str(job_state_root(job)), str(job["project_id"]), str(job["run_id"]))
    terminal = {MigrationPhase.PREDECESSOR_CLOSED, MigrationPhase.ROLLED_BACK}
    return tuple(tx for tx in rows if tx.phase not in terminal)

def _git_head(project_root: str | Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(Path(project_root).resolve()), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _attempt_typed_wait_recovery(
    job: Mapping[str, Any], state: Mapping[str, Any], supervisor: DurableFullPlanSupervisor,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Evaluate one wait generation without acquiring any foreign authority."""
    try:
        assessment = classify_wait_recovery(state)
    except WaitRecoveryError as exc:
        return None, {"status": "NOT_ELIGIBLE", "reason": str(exc)}
    if not assessment.auto_recoverable:
        return None, {"status": "NOT_ELIGIBLE", "owner": assessment.owner, "reason": assessment.reason}
    expected_sha = str(state.get("state_sha256") or "")
    expected_epoch = int(state.get("epoch", 0))
    if assessment.owner == "RESOURCE_RECOVERY":
        resources_ok, snapshot = supervisor._resource_gate(state)
        decision = evaluate_resource_wait_recovery(
            state, resources_ok=resources_ok, expected_state_sha256=expected_sha, expected_epoch=expected_epoch,
        )
        if not decision.resume_allowed:
            return None, {"status": "WAIT", "owner": assessment.owner, "reason": decision.reason, "resources": snapshot}
        try:
            resumed = supervisor.resume_wait_cas(
                "WAITING_RESOURCE", expected_state_sha256=expected_sha, expected_epoch=expected_epoch)
        except ProductionFullPlanError as exc:
            return None, {"status": "STALE", "owner": assessment.owner, "reason": str(exc)}
        return resumed, {"status": "RECOVERED", "owner": assessment.owner, "resources": snapshot}
    if assessment.owner == "PROVIDER_RECOVERY":
        candidates = [
            item for item in state.get("queue", [])
            if item.get("gate_id") == state.get("current_gate")
            and item.get("status") not in {"COMPLETED", "BLOCKED", "CANCELLED"}
        ]
        if len(candidates) != 1:
            return None, {"status": "WAIT", "owner": assessment.owner, "reason": "PROVIDER_WAIT_QUEUE_AMBIGUOUS"}
        gate_run_id = str(candidates[0].get("gate_run_id") or "")
        evidence = load_active_provider_wait_recovery_evidence(
            job_state_root(job), project_id=str(job["project_id"]), gate_run_id=gate_run_id)
        if evidence is None:
            return None, {"status": "WAIT", "owner": assessment.owner, "reason": "PROVIDER_WAIT_EVIDENCE_MISSING"}
        from .provider_runtime_binding import ProviderRuntimeBindingError, collect_production_provider_eligibility
        try:
            fresh = collect_production_provider_eligibility(
                str(job["project_root"]), str(evidence["lv_run_id"]),
                required_capabilities=tuple(evidence.get("required_capabilities", ())),
                extra_evidence_refs=("full-plan-wait-recovery",),
            )
        except ProviderRuntimeBindingError as exc:
            return None, {"status": "WAIT", "owner": assessment.owner, "reason": f"PROVIDER_FACT_REFRESH_FAILED:{exc}"}
        decision = evaluate_provider_wait_recovery(
            evidence, fresh_snapshot=fresh, current_head=_git_head(str(job["project_root"])))
        if not decision.resume_allowed:
            return None, {
                "status": "WAIT", "owner": assessment.owner, "reason": decision.reason,
                "router_request_sha256": decision.router_request_sha256,
                "fresh_router_request_sha256": decision.fresh_router_request_sha256,
            }
        try:
            resumed = supervisor.resume_wait_cas(
                "WAITING_PROVIDER", expected_state_sha256=expected_sha, expected_epoch=expected_epoch)
        except ProductionFullPlanError as exc:
            return None, {"status": "STALE", "owner": assessment.owner, "reason": str(exc)}
        return resumed, {
            "status": "RECOVERED", "owner": assessment.owner,
            "router_request_sha256": decision.router_request_sha256,
            "fresh_router_request_sha256": decision.fresh_router_request_sha256,
            "router_decision": dict(decision.router_decision),
        }
    return None, {"status": "NOT_ELIGIBLE", "owner": assessment.owner, "reason": assessment.reason}


def reconcile_job(job_path: str | Path, *, launch: bool = True) -> dict[str, Any]:
    external_binding_drift = ""
    preloaded_state: dict[str, Any] | None = None
    try:
        job = load_job(job_path)
    except Exception as load_exc:
        try:
            job, preloaded_state = recover_registered_job_state_after_external_binding_drift(job_path)
        except Exception:
            return {"job": str(job_path), "action": "BLOCKED", "state": "UNKNOWN",
                    "reason": f"external binding drift could not be safely reconciled: {load_exc}",
                    "external_binding_drift": True, "launched": False}
        owner_result = _execution_owner_gate(job_path, job)
        if owner_result is not None:
            return owner_result
        status = str(preloaded_state.get("state") or "")
        if status not in TERMINAL_STATES:
            gates = [str(item["gate_id"]) for item in job["gates"]]
            supervisor = DurableFullPlanSupervisor(
                job_state_root(job), project_id=job["project_id"], run_id=job["run_id"], gates=gates,
                authority_core_sha256=str(job.get("authority_core_sha256") or ""), **dict(job.get("policy") or {}),
            )
            reason = f"external binding drift on nonterminal job: {load_exc}"
            AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
                kind="STATE_RECONCILIATION_BLOCKED", state=status, reason=reason,
                gate_id=str(preloaded_state.get("current_gate") or "") or None,
                state_sha256=str(preloaded_state.get("state_sha256") or "") or None,
                details={"source": "boot_reconciler", "external_binding_drift": True},
            )
            return {"job": str(job_path), "action": "BLOCKED", "state": status, "reason": reason, "external_binding_drift": True, "launched": False}
        external_binding_drift = str(load_exc)
    else:
        owner_result = _execution_owner_gate(job_path, job)
        if owner_result is not None:
            return owner_result
    gates = [str(item["gate_id"]) for item in job["gates"]]
    supervisor = DurableFullPlanSupervisor(
        job_state_root(job), project_id=job["project_id"], run_id=job["run_id"], gates=gates,
        authority_core_sha256=str(job.get("authority_core_sha256") or ""),
        **dict(job.get("policy") or {}),
    )
    try:
        if preloaded_state is None:
            state, recovered = supervisor.load()
        else:
            state, recovered = preloaded_state, False
    except ProductionFullPlanError as exc:
        AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
            kind="STATE_RECONCILIATION_BLOCKED", state="UNKNOWN", reason=str(exc),
            details={"source": "boot_reconciler"},
        )
        return {"job": str(job_path), "action": "BLOCKED", "reason": str(exc), "launched": False}
    status = str(state.get("state"))
    try:
        incomplete_migrations = _incomplete_migrations(job)
    except MigrationHandoffError as exc:
        incomplete_migrations = ()
        AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
            kind="RUNTIME_MIGRATION_RECOVERY_REQUIRED", state=status, reason=f"migration evidence invalid: {exc}",
            gate_id=str(state.get("current_gate") or "") or None, state_sha256=str(state.get("state_sha256") or "") or None,
            details={"source": "periodic_reconciler"},
        )
        return {"job": str(job_path), "action": "MIGRATION_RECOVERY_REQUIRED", "state": status, "launched": False}
    if incomplete_migrations:
        tx = incomplete_migrations[-1]
        AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
            kind="RUNTIME_MIGRATION_RECOVERY_REQUIRED", state=status,
            reason=f"runtime migration {tx.migration_id} requires recovery at phase {tx.phase.value}",
            gate_id=str(state.get("current_gate") or "") or None, state_sha256=str(state.get("state_sha256") or "") or None,
            details={"source": "periodic_reconciler"},
        )
        return {"job": str(job_path), "action": "MIGRATION_RECOVERY_REQUIRED", "state": status,
                "migration_id": tx.migration_id, "migration_phase": tx.phase.value, "launched": False}
    wait_recovery = None
    if status in WAIT_STATES:
        resumed, wait_recovery = _attempt_typed_wait_recovery(job, state, supervisor)
        if resumed is None:
            AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
                kind=status, state=status, reason=str(state.get("last_error") or status),
                gate_id=str(state.get("current_gate") or "") or None,
                state_sha256=str(state.get("state_sha256") or "") or None,
                details={"source": "periodic_reconciler", "wait_recovery": wait_recovery},
            )
            return {"job": str(job_path), "action": "PRESERVE_WAIT", "state": status,
                    "wait_recovery": wait_recovery,
                    "recovered_previous_generation": recovered, "launched": False}
        state = resumed
        status = str(state.get("state"))
    if status in TERMINAL_STATES:
        terminal_reason = str(state.get("terminal_reason") or "")
        if status == "CANCELLED" and (
            terminal_reason == "RUNTIME_ACTIVATION_MIGRATION"
            or (terminal_reason == "MIGRATED_TO_SUCCESSOR" and not _migration_successor_is_registered(job, state))
        ):
            AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
                kind="RUNTIME_MIGRATION_ORPHANED", state=status,
                reason="runtime migration predecessor is terminal without a verified successor",
                gate_id=str(state.get("current_gate") or "") or None,
                state_sha256=str(state.get("state_sha256") or "") or None,
                details={"source": "periodic_reconciler"},
            )
        if status in {"BLOCKED", "FAILED"}:
            AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
                kind=status, state=status, reason=str(state.get("last_error") or state.get("terminal_reason") or status),
                gate_id=str(state.get("current_gate") or "") or None,
                state_sha256=str(state.get("state_sha256") or "") or None,
                details={"source": "periodic_reconciler"},
            )
        return {"job": str(job_path), "action": "SKIP_TERMINAL", "state": status,
                "recovered_previous_generation": recovered, "external_binding_drift": bool(external_binding_drift), "launched": False}
    if status not in ACTIVE_STATES:
        return {"job": str(job_path), "action": "BLOCKED", "state": status,
                "reason": "UNRECOGNIZED_ACTIVE_STATE", "launched": False}
    unit = _unit_name(str(job["project_id"]), str(job["run_id"]))
    if _unit_active(unit):
        return {"job": str(job_path), "action": "ALREADY_ACTIVE", "state": status,
                "unit": unit, "launched": False}
    command = transient_systemd_command(job_path, unit_name=unit)
    if not launch:
        result = {"job": str(job_path), "action": "WOULD_RESUME", "state": status,
                  "unit": unit, "command": command, "launched": False}
        if wait_recovery is not None:
            result["wait_recovery"] = wait_recovery
        return result
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    if completed.returncode != 0:
        AttentionOutbox(supervisor.base, project_id=str(job["project_id"]), run_id=str(job["run_id"])).publish(
            kind="SUPERVISOR_LAUNCH_FAILED", state=status,
            reason=(completed.stderr.strip() or f"systemd-run exit {completed.returncode}"),
            details={"source": "periodic_reconciler"},
        )
    return {"job": str(job_path), "action": "RESUME_REQUESTED" if completed.returncode == 0 else "LAUNCH_FAILED",
            "state": status, "unit": unit, "returncode": completed.returncode,
            "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(),
            "launched": completed.returncode == 0}


def reconcile_all(search_root: str | Path, *, launch: bool = True) -> dict[str, Any]:
    jobs = discover_registered_jobs(search_root)
    results: list[dict[str, Any]] = []
    for path in jobs:
        try:
            results.append(reconcile_job(path, launch=launch))
        except Exception as exc:
            results.append({"job": str(path), "action": "BLOCKED", "reason": str(exc), "launched": False})
    resolved = str(Path(search_root).resolve())
    return {
        "schema_version": "orchestration.production-full-plan-boot-reconcile.v1",
        "search_root": resolved,
        "harness_root": resolved,
        "jobs_found": len(jobs),
        "resume_requested": sum(1 for item in results if item["action"] == "RESUME_REQUESTED"),
        "blocked": sum(1 for item in results if item["action"] in {"BLOCKED", "LAUNCH_FAILED", "MIGRATION_RECOVERY_REQUIRED"}),
        "results": results,
    }


def systemd_user_unit(
    *, runtime_root: str | Path | None = None, search_root: str | Path | None = None,
    harness_root: str | Path | None = None, python_executable: str = "/usr/bin/python3",
    preserve_runtime_path: bool = False, preserve_root_path: bool | None = None,
    diagnostic_environment: Mapping[str, str] | None = None,
) -> str:
    source = runtime_root if runtime_root is not None else harness_root
    if source is None:
        raise FullPlanBootError("runtime root is required")
    preserve = preserve_runtime_path if preserve_root_path is None else bool(preserve_root_path)
    raw_runtime = Path(source).expanduser()
    runtime = raw_runtime.absolute() if preserve else raw_runtime.resolve()
    jobs = Path(search_root if search_root is not None else (harness_root or source)).expanduser().resolve()
    diag_lines = ""
    if diagnostic_environment:
        allowed={"GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED","GCH_DIAGNOSTIC_CONFIG"}
        for key,value in diagnostic_environment.items():
            if key not in allowed or "\n" in value or "\0" in value: raise FullPlanBootError("unsafe diagnostic environment")
            if key=="GCH_DIAGNOSTIC_CONFIG" and not Path(value).is_absolute(): raise FullPlanBootError("diagnostic config path must be absolute")
            diag_lines += f"Environment={key}={value}\n"
    return f'''[Unit]
Description=Global GPT Harness Full Plan boot reconciliation
After=default.target

[Service]
Type=oneshot
{diag_lines}WorkingDirectory={runtime}
ExecStart={python_executable} -m runtime.orchestrator.production_full_plan_boot --search-root {jobs}

[Install]
WantedBy=default.target
'''


def _active_jobs_under(root: Path) -> list[str]:
    active: list[str] = []
    if not root.is_dir():
        return active
    for job_path in discover_jobs(root):
        try:
            job = load_job(job_path)
            gates = [str(item["gate_id"]) for item in job["gates"]]
            state, _ = DurableFullPlanSupervisor(
                job_state_root(job), project_id=job["project_id"], run_id=job["run_id"], gates=gates,
                authority_core_sha256=str(job.get("authority_core_sha256") or ""),
                **dict(job.get("policy") or {}),
            ).load()
        except Exception:
            active.append(str(job_path))
            continue
        if str(state.get("state")) not in TERMINAL_STATES:
            active.append(str(job_path))
    return active


def ensure_runtime_link(harness_root: str | Path, runtime_link: str | Path) -> Path:
    target = Path(harness_root).resolve()
    link = Path(runtime_link).expanduser().absolute()
    if not target.is_dir() or target.is_symlink():
        raise FullPlanBootError("runtime link target is unsafe")
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        if not link.is_symlink():
            raise FullPlanBootError("runtime link path is not a symlink")
        try:
            current = link.resolve(strict=True)
        except FileNotFoundError:
            current = None
        if current == target:
            return link
        if current is not None:
            active = _active_jobs_under(current)
            if active:
                raise FullPlanBootError("cannot retarget runtime link while active Full Plan jobs exist")
    temporary = link.with_name(link.name + f".tmp-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    os.symlink(str(target), str(temporary))
    os.replace(temporary, link)
    fd = os.open(str(link.parent), getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return link


def systemd_user_timer(*, service_unit_name: str = "global-gpt-harness-full-plan-reconcile.service",
                       interval_seconds: int = 60) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", service_unit_name):
        raise FullPlanBootError("unsafe reconcile service unit name")
    if interval_seconds < 30:
        raise FullPlanBootError("reconcile interval must be at least 30 seconds")
    return f'''[Unit]\nDescription=Global GPT Harness Full Plan periodic reconciliation\n\n[Timer]\nOnBootSec=30s\nOnUnitActiveSec={interval_seconds}s\nAccuracySec=10s\nPersistent=true\nUnit={service_unit_name}\n\n[Install]\nWantedBy=timers.target\n'''


def install_user_unit(
    *, harness_root: str | Path, unit_name: str = "global-gpt-harness-full-plan-reconcile.service",
    python_executable: str | None = None, runtime_link: str | Path | None = None,
    search_root: str | Path | None = None, diagnostic_environment: Mapping[str, str] | None = None,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", unit_name):
        raise FullPlanBootError("unsafe boot reconcile unit name")
    interpreter = str(Path(python_executable or sys.executable).resolve())
    if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
        raise FullPlanBootError("boot reconcile Python executable is invalid")
    target = Path.home() / ".config" / "systemd" / "user" / unit_name
    target.parent.mkdir(parents=True, exist_ok=True)
    from .durable_io import atomic_write_text
    runtime_root: str | Path = harness_root
    preserve_runtime_path = False
    if runtime_link is not None:
        runtime_root = ensure_runtime_link(harness_root, runtime_link)
        preserve_runtime_path = True
    atomic_write_text(target, systemd_user_unit(
        runtime_root=runtime_root, search_root=search_root or harness_root,
        python_executable=interpreter, preserve_runtime_path=preserve_runtime_path, diagnostic_environment=diagnostic_environment))
    env = _systemd_env()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=20, env=env)
    subprocess.run(["systemctl", "--user", "enable", unit_name], check=True, timeout=20, env=env)
    return target


def install_reconcile_timer(*, service_unit_name: str = "global-gpt-harness-full-plan-reconcile.service",
                            timer_unit_name: str = "global-gpt-harness-full-plan-reconcile.timer",
                            interval_seconds: int = 60) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.timer", timer_unit_name):
        raise FullPlanBootError("unsafe reconcile timer unit name")
    target = Path.home() / ".config" / "systemd" / "user" / timer_unit_name
    target.parent.mkdir(parents=True, exist_ok=True)
    from .durable_io import atomic_write_text
    atomic_write_text(target, systemd_user_timer(
        service_unit_name=service_unit_name, interval_seconds=interval_seconds))
    env = _systemd_env()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=20, env=env)
    subprocess.run(["systemctl", "--user", "enable", "--now", timer_unit_name], check=True, timeout=20, env=env)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile authorized active FULL_PLAN runs after boot")
    parser.add_argument("--search-root")
    parser.add_argument("--harness-root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--install-user-unit", action="store_true")
    parser.add_argument("--runtime-link")
    parser.add_argument("--install-reconcile-timer", action="store_true")
    parser.add_argument("--reconcile-interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    search_root = args.search_root or args.harness_root
    if not search_root:
        parser.error("one of --search-root or --harness-root is required")
    if args.install_user_unit:
        print(install_user_unit(
            harness_root=args.harness_root or search_root, runtime_link=args.runtime_link,
            search_root=search_root,
        ))
        return 0
    if args.install_reconcile_timer:
        print(install_reconcile_timer(interval_seconds=args.reconcile_interval_seconds))
        return 0
    result = reconcile_all(search_root, launch=not args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
