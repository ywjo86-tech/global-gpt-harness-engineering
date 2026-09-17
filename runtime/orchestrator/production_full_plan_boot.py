"""Boot-time one-shot reconciliation for durable authorized FULL_PLAN jobs."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .production_full_plan_entry import load_job, transient_systemd_command
from .production_full_plan_runner import ACTIVE_STATES, TERMINAL_STATES, WAIT_STATES, DurableFullPlanSupervisor, ProductionFullPlanError


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


def discover_jobs(harness_root: str | Path) -> list[Path]:
    root = Path(harness_root).resolve()
    registry = root / "_workspace" / "production-full-plan-jobs"
    if not registry.exists():
        return []
    return sorted(path for path in registry.glob("*/*.job.json") if path.is_file() and not path.is_symlink())


def reconcile_job(job_path: str | Path, *, launch: bool = True) -> dict[str, Any]:
    job = load_job(job_path)
    gates = [str(item["gate_id"]) for item in job["gates"]]
    supervisor = DurableFullPlanSupervisor(
        job["harness_root"], project_id=job["project_id"], run_id=job["run_id"], gates=gates,
        **dict(job.get("policy") or {}),
    )
    try:
        state, recovered = supervisor.load()
    except ProductionFullPlanError as exc:
        return {"job": str(job_path), "action": "BLOCKED", "reason": str(exc), "launched": False}
    status = str(state.get("state"))
    if status in WAIT_STATES:
        return {"job": str(job_path), "action": "PRESERVE_WAIT", "state": status,
                "recovered_previous_generation": recovered, "launched": False}
    if status in TERMINAL_STATES:
        return {"job": str(job_path), "action": "SKIP_TERMINAL", "state": status,
                "recovered_previous_generation": recovered, "launched": False}
    if status not in ACTIVE_STATES:
        return {"job": str(job_path), "action": "BLOCKED", "state": status,
                "reason": "UNRECOGNIZED_ACTIVE_STATE", "launched": False}
    unit = _unit_name(str(job["project_id"]), str(job["run_id"]))
    if _unit_active(unit):
        return {"job": str(job_path), "action": "ALREADY_ACTIVE", "state": status,
                "unit": unit, "launched": False}
    command = transient_systemd_command(job_path, unit_name=unit)
    if not launch:
        return {"job": str(job_path), "action": "WOULD_RESUME", "state": status,
                "unit": unit, "command": command, "launched": False}
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    return {"job": str(job_path), "action": "RESUME_REQUESTED" if completed.returncode == 0 else "LAUNCH_FAILED",
            "state": status, "unit": unit, "returncode": completed.returncode,
            "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(),
            "launched": completed.returncode == 0}


def reconcile_all(harness_root: str | Path, *, launch: bool = True) -> dict[str, Any]:
    jobs = discover_jobs(harness_root)
    results = [reconcile_job(path, launch=launch) for path in jobs]
    return {
        "schema_version": "orchestration.production-full-plan-boot-reconcile.v1",
        "harness_root": str(Path(harness_root).resolve()),
        "jobs_found": len(jobs),
        "resume_requested": sum(1 for item in results if item["action"] == "RESUME_REQUESTED"),
        "blocked": sum(1 for item in results if item["action"] in {"BLOCKED", "LAUNCH_FAILED"}),
        "results": results,
    }


def systemd_user_unit(*, harness_root: str | Path, python_executable: str = "/usr/bin/python3") -> str:
    root = Path(harness_root).resolve()
    return f'''[Unit]\nDescription=Global GPT Harness Full Plan boot reconciliation\nAfter=default.target\n\n[Service]\nType=oneshot\nWorkingDirectory={root}\nExecStart={python_executable} -m runtime.orchestrator.production_full_plan_boot --harness-root {root}\n\n[Install]\nWantedBy=default.target\n'''


def install_user_unit(*, harness_root: str | Path, unit_name: str = "global-gpt-harness-full-plan-reconcile.service",
                      python_executable: str | None = None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", unit_name):
        raise FullPlanBootError("unsafe boot reconcile unit name")
    interpreter = str(Path(python_executable or sys.executable).resolve())
    if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
        raise FullPlanBootError("boot reconcile Python executable is invalid")
    target = Path.home() / ".config" / "systemd" / "user" / unit_name
    target.parent.mkdir(parents=True, exist_ok=True)
    from .durable_io import atomic_write_text
    atomic_write_text(target, systemd_user_unit(harness_root=harness_root, python_executable=interpreter))
    env = _systemd_env()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=20, env=env)
    subprocess.run(["systemctl", "--user", "enable", unit_name], check=True, timeout=20, env=env)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile authorized active FULL_PLAN runs after boot")
    parser.add_argument("--harness-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--install-user-unit", action="store_true")
    args = parser.parse_args(argv)
    if args.install_user_unit:
        print(install_user_unit(harness_root=args.harness_root))
        return 0
    result = reconcile_all(args.harness_root, launch=not args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
