"""GPT Operator bridge for resuming a durable Full Plan provider wait.

The bridge does not select a provider, create an approval, or execute a patch.
It binds an already-authorized Manual Action to the registered durable job,
then reopens WAITING_PROVIDER so the canonical Full Plan entry can continue.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .durable_io import atomic_write_json
from .production_full_plan_entry import (
    canonical_job_path,
    load_job,
    load_registered_job,
    transient_systemd_command,
)
from .production_run_authority import RunAuthorityError, bind_manual_action_paths
from .production_full_plan_runner import DurableFullPlanSupervisor
from .production_manual_action import validate_action_package

_SHA40_64 = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class FullPlanOperatorResumeError(ValueError):
    pass


def _load_regular_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    if source.is_symlink() or not source.is_file():
        raise FullPlanOperatorResumeError(f"unsafe or missing JSON: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullPlanOperatorResumeError(f"malformed JSON: {source}") from exc
    if not isinstance(value, dict):
        raise FullPlanOperatorResumeError(f"JSON object required: {source}")
    return value


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_text(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=20,
    )
    if completed.returncode != 0:
        raise FullPlanOperatorResumeError("Git verification failed")
    return completed.stdout.strip()


def _canonical_registered_job(job_path: str | Path) -> tuple[Path, dict[str, Any]]:
    requested = load_job(job_path)
    canonical = canonical_job_path(requested)
    if canonical.is_symlink() or not canonical.is_file():
        raise FullPlanOperatorResumeError("durable Full Plan job is not registered")
    registered = load_registered_job(canonical)
    identity = ("project_root", "harness_root", "project_id", "run_id")
    if any(str(requested.get(key)) != str(registered.get(key)) for key in identity):
        raise FullPlanOperatorResumeError("registered Full Plan job identity mismatch")
    return canonical, registered


def _gate_spec(job: Mapping[str, Any], gate_id: str) -> dict[str, Any]:
    matches = [dict(item) for item in job.get("gates", []) if item.get("gate_id") == gate_id]
    if len(matches) != 1:
        raise FullPlanOperatorResumeError("requested Gate is not uniquely bound in job")
    return matches[0]


def _expected_lv_run_id(gate_run_id: str, lv_order: list[str], lv_id: str) -> str:
    if lv_id not in lv_order:
        raise FullPlanOperatorResumeError("LV is outside current Gate")
    index = lv_order.index(lv_id)
    return gate_run_id if index == 0 else f"{gate_run_id}-{lv_id.lower()}"


def _validate_source_state(root: Path, spec: Mapping[str, Any], action: Mapping[str, Any]) -> None:
    if _git_text(root, "status", "--porcelain=v1", "-uall"):
        raise FullPlanOperatorResumeError("operator resume requires a clean worktree")
    branch = _git_text(root, "branch", "--show-current")
    if branch != str(spec.get("branch", "")):
        raise FullPlanOperatorResumeError("operator resume branch mismatch")
    head = _git_text(root, "rev-parse", "HEAD")
    source_head = str(action.get("source_head", ""))
    if not _SHA40_64.fullmatch(source_head) or head != source_head:
        raise FullPlanOperatorResumeError("manual action source HEAD must equal current HEAD")


def _bind_manual_action_and_resume_locked(
    *,
    job_path: str | Path,
    gate_id: str,
    lv_id: str,
    action_path: str | Path,
    authorization_path: str | Path,
    launch: bool = False,
) -> dict[str, Any]:
    canonical, job = _canonical_registered_job(job_path)
    root = Path(str(job["project_root"])).resolve()
    harness = Path(str(job["harness_root"])).resolve()
    gate_ids = [str(item["gate_id"]) for item in job["gates"]]
    supervisor = DurableFullPlanSupervisor(
        harness, project_id=str(job["project_id"]), run_id=str(job["run_id"]),
        gates=gate_ids, authority_core_sha256=str(job.get("authority_core_sha256") or ""),
        **dict(job.get("policy") or {}),
    )
    state, _ = supervisor.load()
    if state.get("state") != "WAITING_PROVIDER":
        raise FullPlanOperatorResumeError("Full Plan is not waiting for provider authority")
    if state.get("current_gate") != gate_id:
        raise FullPlanOperatorResumeError("operator resume Gate does not match durable state")
    active = [item for item in state.get("queue", []) if item.get("gate_id") == gate_id and item.get("status") == "READY"]
    if len(active) != 1:
        raise FullPlanOperatorResumeError("WAITING_PROVIDER must have exactly one active Gate item")
    gate_run_id = str(active[0].get("gate_run_id", ""))
    if not gate_run_id:
        raise FullPlanOperatorResumeError("durable Gate run identity is missing")

    from .gate_orchestrator import load_gate_plan

    plan = load_gate_plan(root, gate_id)
    if plan.project_id != str(job["project_id"]):
        raise FullPlanOperatorResumeError("Gate plan project identity mismatch")
    lv_order = [item.lv_id for item in plan.lvs]
    selected = next((item for item in plan.lvs if item.lv_id == lv_id), None)
    if selected is None:
        raise FullPlanOperatorResumeError("LV is outside current Gate")
    expected_run_id = _expected_lv_run_id(gate_run_id, lv_order, lv_id)

    action_file = Path(action_path).resolve()
    auth_file = Path(authorization_path).resolve()
    action = _load_regular_json(action_file)
    authorization = _load_regular_json(auth_file)
    if action.get("run_id") != expected_run_id:
        raise FullPlanOperatorResumeError("manual action run ID does not match durable LV identity")
    if action.get("project_id") != plan.project_id or action.get("gate_id") != gate_id or action.get("lv_id") != lv_id:
        raise FullPlanOperatorResumeError("manual action project/Gate/LV identity mismatch")
    if action.get("plan_sha256") != plan.canonical_plan_sha256:
        raise FullPlanOperatorResumeError("manual action plan binding mismatch")
    if action.get("validation_ids") != list(selected.tests):
        raise FullPlanOperatorResumeError("manual action validation binding mismatch")
    _validate_source_state(root, _gate_spec(job, gate_id), action)

    manifest = {
        "project_id": plan.project_id,
        "run_id": expected_run_id,
        "gate_id": gate_id,
        "lv_id": lv_id,
        "canonical_plan_sha256": plan.canonical_plan_sha256,
        "source_head": str(action["source_head"]),
        "owned_files": list(selected.owned_files),
    }
    try:
        validate_action_package(action, authorization, manifest)
    except Exception as exc:
        raise FullPlanOperatorResumeError(f"manual action validation failed: {exc}") from exc

    spec = _gate_spec(job, gate_id)
    package_paths = dict(spec.get("manual_action_package_paths_by_lv") or {})
    auth_paths = dict(spec.get("manual_action_authorization_paths_by_lv") or {})
    old_package = package_paths.get(lv_id)
    old_auth = auth_paths.get(lv_id)
    if old_package not in {None, str(action_file)} or old_auth not in {None, str(auth_file)}:
        raise FullPlanOperatorResumeError("conflicting Manual Action is already bound for LV")
    try:
        bind_manual_action_paths(
            job, gate_id=gate_id, lv_id=lv_id,
            action_path=str(action_file), authorization_path=str(auth_file),
        )
    except RunAuthorityError as exc:
        if str(exc) == "RUNTIME_BINDING_CONFLICT":
            raise FullPlanOperatorResumeError("conflicting Manual Action is already bound for LV") from exc
        raise FullPlanOperatorResumeError(str(exc)) from exc

    resumed = supervisor.resume_wait("WAITING_PROVIDER")
    launch_result: dict[str, Any] = {"requested": False, "returncode": None}
    if launch:
        command = transient_systemd_command(canonical)
        env = dict(os.environ)
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20, env=env)
        launch_result = {
            "requested": True,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
        if completed.returncode != 0:
            raise FullPlanOperatorResumeError("durable Full Plan relaunch failed")

    receipt = {
        "schema_version": "orchestration.full-plan-operator-resume.v1",
        "project_id": str(job["project_id"]),
        "run_id": str(job["run_id"]),
        "gate_id": gate_id,
        "lv_id": lv_id,
        "lv_run_id": expected_run_id,
        "from_state": "WAITING_PROVIDER",
        "to_state": str(resumed.get("state", "")),
        "action_package_sha256": _digest(action),
        "authorization_sha256": _digest(authorization),
        "registered_job": str(canonical),
        "launch": launch_result,
    }
    receipt["receipt_sha256"] = _digest(receipt)
    receipt_path = supervisor.base / "operator-resume" / f"{gate_id}-{lv_id}.json"
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}



@contextmanager
def _operator_resume_lock(base: Path) -> Iterator[None]:
    base.mkdir(parents=True, exist_ok=True)
    if base.is_symlink():
        raise FullPlanOperatorResumeError("operator resume state root is unsafe")
    lock_path = base / "operator-resume.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise FullPlanOperatorResumeError("operator resume lock is unsafe") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def bind_manual_action_and_resume(
    *, job_path: str | Path, gate_id: str, lv_id: str,
    action_path: str | Path, authorization_path: str | Path, launch: bool = False,
) -> dict[str, Any]:
    canonical, job = _canonical_registered_job(job_path)
    base = (Path(str(job["harness_root"])).resolve() / "_workspace" / "production-full-plan"
            / str(job["project_id"]) / str(job["run_id"]))
    with _operator_resume_lock(base):
        return _bind_manual_action_and_resume_locked(
            job_path=canonical, gate_id=gate_id, lv_id=lv_id,
            action_path=action_path, authorization_path=authorization_path, launch=launch,
        )

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind GPT Manual Action and resume a durable Full Plan provider wait")
    parser.add_argument("--job", required=True)
    parser.add_argument("--gate-id", required=True)
    parser.add_argument("--lv-id", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = bind_manual_action_and_resume(
            job_path=args.job,
            gate_id=args.gate_id,
            lv_id=args.lv_id,
            action_path=args.action,
            authorization_path=args.authorization,
            launch=args.launch,
        )
    except FullPlanOperatorResumeError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "RESUME_BOUND", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
