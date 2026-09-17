"""Bound production entrypoint for durable cross-Gate FULL_PLAN execution."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError
from .durable_io import atomic_write_json

JOB_SCHEMA = "orchestration.production-full-plan-job.v1"


class FullPlanJobError(ValueError):
    pass


def _load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise FullPlanJobError(f"unsafe or missing JSON: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullPlanJobError(f"malformed JSON: {source}") from exc
    if not isinstance(value, dict):
        raise FullPlanJobError(f"JSON object required: {source}")
    return value


def load_job(path: str | Path) -> dict[str, Any]:
    job = _load_json(path)
    if job.get("schema_version") != JOB_SCHEMA:
        raise FullPlanJobError("unsupported Full Plan job schema")
    required = {"project_root", "harness_root", "project_id", "run_id", "gates"}
    if not required.issubset(job):
        raise FullPlanJobError("Full Plan job is incomplete")
    gates = job.get("gates")
    if not isinstance(gates, list) or not gates:
        raise FullPlanJobError("Full Plan job Gate list is empty")
    ids: list[str] = []
    for gate in gates:
        if not isinstance(gate, dict) or not isinstance(gate.get("gate_id"), str):
            raise FullPlanJobError("Full Plan Gate job entry is invalid")
        gate_id = gate["gate_id"]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", gate_id):
            raise FullPlanJobError("unsafe Gate ID in Full Plan job")
        ids.append(gate_id)
        for field in ("approval_evidence", "requirements_sha256", "branch", "head"):
            if field not in gate or not isinstance(gate[field], str) or not gate[field]:
                raise FullPlanJobError(f"Gate job field is missing: {field}")
        if gate.get("full_plan_opt_in") is not True or gate.get("project_final_validation") is not True:
            raise FullPlanJobError("Gate job requires explicit FULL_PLAN opt-in and final validation")
    if len(set(ids)) != len(ids):
        raise FullPlanJobError("Full Plan job contains duplicate Gates")
    return job


def _git_common_dir(project_root: Path) -> str:
    probe = subprocess.run(["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, check=False, timeout=10)
    if probe.returncode != 0 or not probe.stdout.strip():
        raise FullPlanJobError("project is not a readable Git worktree")
    common = Path(probe.stdout.strip())
    if not common.is_absolute():
        common = (project_root / common).resolve()
    return str(common)


def canonical_job_path(job: Mapping[str, Any]) -> Path:
    harness = Path(str(job["harness_root"])).resolve()
    return harness / "_workspace" / "production-full-plan-jobs" / str(job["project_id"]) / f"{job['run_id']}.job.json"


def register_job(job: Mapping[str, Any]) -> Path:
    """Persist the authorized job so a boot reconciler can rediscover it."""
    path = canonical_job_path(job)
    atomic_write_json(path, dict(job))
    return path


def preflight_job(job: Mapping[str, Any]) -> dict[str, Any]:
    project = Path(str(job["project_root"])).resolve()
    harness = Path(str(job["harness_root"])).resolve()
    if not project.is_dir() or project.is_symlink() or not harness.is_dir() or harness.is_symlink():
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "PROJECT_OR_HARNESS_ROOT_INVALID"}
    python_executable = Path(str(job.get("python_executable") or sys.executable)).resolve()
    if not python_executable.is_file() or not os.access(python_executable, os.X_OK):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "PYTHON_EXECUTABLE_INVALID"}
    required_modules = job.get("required_python_modules", [])
    if not isinstance(required_modules, list) or any(not isinstance(x, str) or not x for x in required_modules):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "REQUIRED_PYTHON_MODULES_INVALID"}
    for module in required_modules:
        probe = subprocess.run([str(python_executable), "-c", f"import {module}"], capture_output=True, text=True, check=False, timeout=20)
        if probe.returncode != 0:
            return {"status": "BLOCK", "state": "BLOCKED", "reason": f"MISSING_PYTHON_MODULE:{module}"}
    required_executables = job.get("required_executables", ["git"])
    if not isinstance(required_executables, list) or any(not isinstance(x, str) or not x for x in required_executables):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "REQUIRED_EXECUTABLES_INVALID"}
    missing = [name for name in required_executables if shutil.which(name) is None]
    if missing:
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "MISSING_EXECUTABLE:" + ",".join(missing)}
    try:
        common = _git_common_dir(project)
    except FullPlanJobError as exc:
        return {"status": "BLOCK", "state": "BLOCKED", "reason": str(exc)}
    expected_common = job.get("git_common_dir")
    if expected_common and Path(str(expected_common)).resolve() != Path(common).resolve():
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "GIT_COMMON_DIR_MISMATCH"}
    expected_branch = job.get("expected_branch")
    if expected_branch:
        probe = subprocess.run(["git", "-C", str(project), "branch", "--show-current"],
                               capture_output=True, text=True, check=False, timeout=10)
        if probe.returncode != 0 or probe.stdout.strip() != expected_branch:
            return {"status": "BLOCK", "state": "BLOCKED", "reason": "GIT_BRANCH_MISMATCH"}
    return {"status": "PASS", "git_common_dir": common, "python": str(python_executable)}


def build_gate_executor(job: Mapping[str, Any]):
    project_root = str(Path(str(job["project_root"])).resolve())
    harness_root = str(Path(str(job["harness_root"])).resolve())
    specs = {str(item["gate_id"]): dict(item) for item in job["gates"]}

    def execute(gate_id: str, gate_run_id: str, resume: bool) -> Mapping[str, Any]:
        from .gate_orchestrator import FULL_PLAN, execute_gate
        spec = specs[gate_id]
        requirement_evidence = None
        evidence_path = spec.get("requirement_evidence_path")
        if evidence_path:
            requirement_evidence = _load_json(evidence_path)
        return execute_gate(
            project_root,
            gate_id,
            gate_run_id,
            harness_root=harness_root,
            approval_evidence=spec["approval_evidence"],
            requirements_sha256=spec["requirements_sha256"],
            branch=spec["branch"],
            head=spec["head"],
            mode=FULL_PLAN,
            resume=resume,
            full_plan_opt_in=spec["full_plan_opt_in"],
            project_final_validation=spec["project_final_validation"],
            requirement_evidence=requirement_evidence,
        )
    return execute


def run_job(path: str | Path) -> dict[str, Any]:
    job = load_job(path)
    register_job(job)
    gate_ids = [str(item["gate_id"]) for item in job["gates"]]
    policy = dict(job.get("policy") or {})
    supervisor = DurableFullPlanSupervisor(
        job["harness_root"], project_id=job["project_id"], run_id=job["run_id"], gates=gate_ids, **policy,
    )
    return supervisor.run(build_gate_executor(job), preflight=lambda _: preflight_job(job)).to_dict()


def transient_systemd_command(job_path: str | Path, *, unit_name: str | None = None) -> list[str]:
    job = load_job(job_path)
    unit = unit_name or f"fullplan-{job['project_id']}-{job['run_id']}"
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", unit):
        raise FullPlanJobError("unsafe systemd unit name")
    uid = os.getuid()
    runtime_dir = f"/run/user/{uid}"
    bus = f"unix:path={runtime_dir}/bus"
    return [
        "env", f"XDG_RUNTIME_DIR={runtime_dir}", f"DBUS_SESSION_BUS_ADDRESS={bus}",
        "systemd-run", "--user", f"--unit={unit}", "--collect",
        f"--working-directory={Path(str(job['harness_root'])).resolve()}",
        "--property=Restart=on-failure", "--property=RestartSec=5s",
        "--property=RestartPreventExitStatus=2 3",
        str(job.get("python_executable") or sys.executable), "-m", "runtime.orchestrator.production_full_plan_entry",
        "--job", str(Path(job_path).resolve()),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a durable authorized FULL_PLAN job")
    parser.add_argument("--job", required=True)
    parser.add_argument("--launch-transient", action="store_true")
    parser.add_argument("--unit-name")
    parser.add_argument("--print-launch-command", action="store_true")
    args = parser.parse_args(argv)
    if args.launch_transient or args.print_launch_command:
        register_job(load_job(args.job))
        command = transient_systemd_command(args.job, unit_name=args.unit_name)
        if args.print_launch_command:
            print(json.dumps(command, ensure_ascii=False))
            return 0
        completed = subprocess.run(command, check=False)
        return int(completed.returncode)
    try:
        result = run_job(args.job)
    except (FullPlanJobError, ProductionFullPlanError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "hard_stop": True}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "COMPLETED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
