"""Bound production entrypoint for durable cross-Gate FULL_PLAN execution."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .production_full_plan_runner import DurableFullPlanSupervisor, ProductionFullPlanError
from .operator_exit_guard import assess_operator_turn_exit
from .durable_io import atomic_write_json
from .contract_adapter import MAPPING_ROOT_ENV
from .harness_state_root import job_state_root
from .production_run_authority import (
    RunAuthorityError, bind_manual_action_paths, extract_runtime_bindings,
    merge_runtime_bindings, seal_authority_core, validate_authority_core,
    validate_executor_runtime,
)

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
        adoption_path = gate.get("adopted_prefix_evidence_path")
        if adoption_path is not None and (not isinstance(adoption_path, str) or not adoption_path):
            raise FullPlanJobError("Gate job adopted_prefix_evidence_path is invalid")
        for field in ("manual_action_package_paths_by_lv", "manual_action_authorization_paths_by_lv"):
            manual_paths = gate.get(field)
            if manual_paths is not None:
                if not isinstance(manual_paths, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v for k, v in manual_paths.items()):
                    raise FullPlanJobError(f"Gate job {field} is invalid")
        evidence_paths_by_lv = gate.get("requirement_evidence_paths_by_lv")
        if evidence_paths_by_lv is not None:
            if (not isinstance(evidence_paths_by_lv, dict) or not evidence_paths_by_lv
                    or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                           for k, v in evidence_paths_by_lv.items())):
                raise FullPlanJobError("Gate job requirement_evidence_paths_by_lv is invalid")
    if len(set(ids)) != len(ids):
        raise FullPlanJobError("Full Plan job contains duplicate Gates")
    if job.get("executor_kind") == "GPT_OPERATOR_PLAN":
        from .operator_plan_execution import validate_operator_plan_job
        validate_operator_plan_job(job)
    state_root = job.get("harness_state_root")
    if state_root is not None and (not isinstance(state_root, str) or not state_root):
        raise FullPlanJobError("Full Plan job harness_state_root is invalid")
    mapping_root = job.get("mapping_root")
    if mapping_root is not None and (not isinstance(mapping_root, str) or not mapping_root):
        raise FullPlanJobError("Full Plan job mapping_root is invalid")
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
    state_root = job_state_root(job)
    return state_root / "_workspace" / "production-full-plan-jobs" / str(job["project_id"]) / f"{job['run_id']}.job.json"


def recover_registered_job_state_after_external_binding_drift(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover only sealed durable identity/state; never authorize execution from drifted externals."""
    source = Path(path).resolve()
    raw = _load_json(source)
    if raw.get("schema_version") != JOB_SCHEMA:
        raise FullPlanJobError("unsupported Full Plan job schema")
    required = {"project_root", "harness_root", "project_id", "run_id", "gates", "authority_core_sha256"}
    if not required.issubset(raw):
        raise FullPlanJobError("Full Plan job is incomplete")
    try:
        validate_authority_core(raw)
    except RunAuthorityError as exc:
        raise FullPlanJobError(str(exc)) from exc
    if canonical_job_path(raw).resolve() != source:
        raise FullPlanJobError("registered Full Plan job canonical path mismatch")
    gates_raw = raw.get("gates")
    if not isinstance(gates_raw, list) or not gates_raw:
        raise FullPlanJobError("Full Plan job Gate list is empty")
    gate_ids: list[str] = []
    for item in gates_raw:
        if not isinstance(item, dict) or not isinstance(item.get("gate_id"), str) or not re.fullmatch(r"[A-Za-z0-9._-]+", item["gate_id"]):
            raise FullPlanJobError("unsafe Gate ID in registered Full Plan job")
        gate_ids.append(item["gate_id"])
    supervisor = DurableFullPlanSupervisor(
        job_state_root(raw), project_id=raw["project_id"], run_id=raw["run_id"], gates=gate_ids,
        authority_core_sha256=str(raw["authority_core_sha256"]), **dict(raw.get("policy") or {}),
    )
    if supervisor.state_path.is_symlink() or not supervisor.state_path.is_file():
        raise FullPlanJobError("durable Full Plan state is unavailable for drift recovery")
    try:
        state, _ = supervisor.load()
    except ProductionFullPlanError as exc:
        raise FullPlanJobError(str(exc)) from exc
    return raw, state


def register_job(job: Mapping[str, Any]) -> Path:
    """Persist an immutable authority core and controlled runtime bindings."""
    incoming_bindings = extract_runtime_bindings(job)
    sealed = seal_authority_core(job)
    path = canonical_job_path(sealed)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise FullPlanJobError("unsafe registered Full Plan job")
        existing = _load_json(path)
        try:
            existing_sha = validate_authority_core(existing)
        except RunAuthorityError as exc:
            raise FullPlanJobError(str(exc)) from exc
        if existing_sha != sealed["authority_core_sha256"]:
            raise FullPlanJobError("RUN_ID_REBIND_FORBIDDEN")
        sealed = existing
    else:
        atomic_write_json(path, sealed)
    for gate_id, gate_bindings in incoming_bindings.items():
        packages = gate_bindings.get("manual_action_package_paths_by_lv", {})
        auths = gate_bindings.get("manual_action_authorization_paths_by_lv", {})
        if set(packages) != set(auths):
            raise FullPlanJobError("manual action package/authorization LV coverage mismatch")
        for lv_id in sorted(packages):
            try:
                bind_manual_action_paths(
                    sealed, gate_id=gate_id, lv_id=lv_id,
                    action_path=str(packages[lv_id]), authorization_path=str(auths[lv_id]),
                )
            except RunAuthorityError as exc:
                raise FullPlanJobError(str(exc)) from exc
    return path


def load_registered_job(path: str | Path) -> dict[str, Any]:
    core = load_job(path)
    try:
        validate_authority_core(core)
        return merge_runtime_bindings(core)
    except RunAuthorityError as exc:
        raise FullPlanJobError(str(exc)) from exc


def preflight_job(job: Mapping[str, Any]) -> dict[str, Any]:
    project = Path(str(job["project_root"])).resolve()
    harness = Path(str(job["harness_root"])).resolve()
    state_root = job_state_root(job)
    if (not project.is_dir() or project.is_symlink() or not harness.is_dir() or harness.is_symlink()
            or not state_root.is_dir() or state_root.is_symlink()):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "PROJECT_OR_HARNESS_ROOT_INVALID"}
    python_executable = Path(str(job.get("python_executable") or sys.executable)).expanduser()
    if not python_executable.is_absolute():
        python_executable = (Path.cwd() / python_executable).absolute()
    if not python_executable.is_file() or not os.access(python_executable, os.X_OK):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "PYTHON_EXECUTABLE_INVALID"}
    required_modules = job.get("required_python_modules", [])
    if not isinstance(required_modules, list) or any(not isinstance(x, str) or not x for x in required_modules):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "REQUIRED_PYTHON_MODULES_INVALID"}
    for module in required_modules:
        probe = subprocess.run([str(python_executable), "-c", f"import {module}"], capture_output=True, text=True, check=False, timeout=20)
        if probe.returncode != 0:
            return {"status": "BLOCK", "state": "BLOCKED", "reason": f"MISSING_PYTHON_MODULE:{module}"}
    mapping_root = job.get("mapping_root")
    if mapping_root is not None:
        candidate = Path(mapping_root)
        if (not candidate.is_absolute() or not candidate.exists() or not candidate.is_dir()
                or candidate.is_symlink() or candidate != candidate.resolve()):
            return {"status": "BLOCK", "state": "BLOCKED", "reason": "MAPPING_ROOT_INVALID"}
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
    if job.get("authority_core_sha256"):
        try:
            validate_authority_core(job)
        except RunAuthorityError as exc:
            return {"status": "BLOCK", "state": "BLOCKED", "reason": str(exc)}
        runtime_ok, runtime_reason = validate_executor_runtime(job)
        if not runtime_ok:
            return {"status": "BLOCK", "state": "BLOCKED", "reason": runtime_reason}
    return {"status": "PASS", "git_common_dir": common, "python": str(python_executable)}


def build_gate_executor(job: Mapping[str, Any]):
    if job.get("executor_kind") == "GPT_OPERATOR_PLAN":
        from .operator_plan_execution import build_operator_plan_executor
        return build_operator_plan_executor(job)
    project_root = str(Path(str(job["project_root"])).resolve())
    harness_root = str(job_state_root(job))
    specs = {str(item["gate_id"]): dict(item) for item in job["gates"]}

    def execute(gate_id: str, gate_run_id: str, resume: bool) -> Mapping[str, Any]:
        from .gate_orchestrator import FULL_PLAN, execute_gate
        spec = specs[gate_id]
        requirement_evidence = None
        evidence_path = spec.get("requirement_evidence_path")
        if evidence_path:
            requirement_evidence = _load_json(evidence_path)
        adopted_prefix_evidence = None
        adoption_path = spec.get("adopted_prefix_evidence_path")
        if adoption_path:
            adopted_prefix_evidence = _load_json(adoption_path)
        manual_action_packages_by_lv = {str(lv): _load_json(path) for lv, path in dict(spec.get("manual_action_package_paths_by_lv") or {}).items()}
        manual_action_authorizations_by_lv = {str(lv): _load_json(path) for lv, path in dict(spec.get("manual_action_authorization_paths_by_lv") or {}).items()}
        if set(manual_action_packages_by_lv) != set(manual_action_authorizations_by_lv):
            raise FullPlanJobError("manual action package/authorization LV coverage mismatch")
        project_requirement_evidence_by_lv = None
        evidence_paths_by_lv = spec.get("requirement_evidence_paths_by_lv")
        if evidence_paths_by_lv is not None:
            if not isinstance(evidence_paths_by_lv, dict):
                raise FullPlanJobError("requirement_evidence_paths_by_lv must be an object")
            project_requirement_evidence_by_lv = {}
            for lv_id, evidence_path_by_lv in evidence_paths_by_lv.items():
                envelope = _load_json(evidence_path_by_lv)
                if envelope.get("schema_version") != "orchestration.project-requirement-contract.v1" or not isinstance(envelope.get("requirements"), dict):
                    raise FullPlanJobError(f"invalid project requirement evidence: {lv_id}")
                project_requirement_evidence_by_lv[str(lv_id)] = dict(envelope["requirements"])
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
            project_requirement_evidence_by_lv=project_requirement_evidence_by_lv,
            adopted_prefix_evidence=adopted_prefix_evidence,
            manual_action_packages_by_lv=manual_action_packages_by_lv,
            manual_action_authorizations_by_lv=manual_action_authorizations_by_lv,
        )
    return execute


def run_job(path: str | Path) -> dict[str, Any]:
    requested = load_job(path)
    canonical = register_job(requested)
    job = load_registered_job(canonical)
    gate_ids = [str(item["gate_id"]) for item in job["gates"]]
    policy = dict(job.get("policy") or {})
    supervisor = DurableFullPlanSupervisor(
        job_state_root(job), project_id=job["project_id"], run_id=job["run_id"], gates=gate_ids,
        authority_core_sha256=str(job.get("authority_core_sha256") or ""), **policy,
    )
    previous_mapping_root = os.environ.get(MAPPING_ROOT_ENV)
    mapping_root = job.get("mapping_root")
    if mapping_root is not None:
        os.environ[MAPPING_ROOT_ENV] = str(mapping_root)
    try:
        result = supervisor.run(build_gate_executor(job), preflight=lambda _: preflight_job(job)).to_dict()
        result["operator_exit"] = assess_operator_turn_exit(
            result.get("state", {}),
            attention_events=supervisor.attention_outbox.pending(),
            now=datetime.now(timezone.utc),
            completion_obligations=None,
        ).to_dict()
        return result
    finally:
        if previous_mapping_root is None:
            os.environ.pop(MAPPING_ROOT_ENV, None)
        else:
            os.environ[MAPPING_ROOT_ENV] = previous_mapping_root


def transient_systemd_command(job_path: str | Path, *, unit_name: str | None = None) -> list[str]:
    job = load_job(job_path)
    unit = unit_name or f"fullplan-{job['project_id']}-{job['run_id']}"
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", unit):
        raise FullPlanJobError("unsafe systemd unit name")
    uid = os.getuid()
    runtime_dir = f"/run/user/{uid}"
    bus = f"unix:path={runtime_dir}/bus"
    diagnostic_args=[]
    for key in ("GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED","GCH_DIAGNOSTIC_CONFIG"):
        value=os.environ.get(key)
        if value is None: continue
        if "\n" in value or "\0" in value: raise FullPlanJobError("unsafe diagnostic environment")
        if key=="GCH_DIAGNOSTIC_CONFIG" and not Path(value).is_absolute(): raise FullPlanJobError("diagnostic config path must be absolute")
        diagnostic_args.append(f"--setenv={key}={value}")
    return [
        "env", f"XDG_RUNTIME_DIR={runtime_dir}", f"DBUS_SESSION_BUS_ADDRESS={bus}",
        "systemd-run", "--user", f"--unit={unit}", "--collect", *diagnostic_args,
        f"--working-directory={Path(str(job.get('runtime_code_root') or job['harness_root'])).resolve()}",
        "--property=Restart=on-failure", "--property=RestartSec=5s",
        "--property=RestartPreventExitStatus=2 3",
        "--property=KillMode=control-group", "--property=SendSIGKILL=yes",
        "--property=TimeoutStopSec=15s",
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
