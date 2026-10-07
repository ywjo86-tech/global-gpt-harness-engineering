"""Bound production entrypoint for durable cross-Gate FULL_PLAN execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .production_full_plan_runner import (
    DurableFullPlanSupervisor, ProductionFullPlanError, validate_recovery_successor_binding,
)
from .operator_exit_guard import assess_operator_turn_exit
from .durable_io import atomic_write_json
from .contract_adapter import MAPPING_ROOT_ENV, sha256_file
from .harness_state_root import job_state_root
from .runtime_release import RuntimeReleaseError, verify_runtime_release
from .production_run_authority import (
    AUTO_RECONCILE_OWNER, RunAuthorityError, bind_manual_action_paths, extract_runtime_bindings,
    merge_runtime_bindings, resolve_execution_owner, seal_authority_core, validate_authority_core,
    validate_executor_runtime,
)

JOB_SCHEMA = "orchestration.production-full-plan-job.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")


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


def _approval_proof_is_fresh(
    value: Mapping[str, Any], *, now: datetime | None = None,
) -> bool:
    if value.get("status") != "APPROVED" or value.get("revoked_at") is not None:
        return False
    issued_raw = value.get("issued_at")
    expires_raw = value.get("expires_at")
    if not isinstance(issued_raw, str) or not isinstance(expires_raw, str):
        return False
    try:
        issued = datetime.fromisoformat(issued_raw.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if issued.tzinfo is None or expires.tzinfo is None or expires <= issued:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return False
    return issued <= current.astimezone(timezone.utc) < expires


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
        adoption_digest = gate.get("adopted_prefix_evidence_sha256")
        if (adoption_path is None) != (adoption_digest is None):
            raise FullPlanJobError("Gate job prefix adoption evidence binding is incomplete")
        if adoption_path is not None:
            if not isinstance(adoption_path, str) or not adoption_path:
                raise FullPlanJobError("Gate job adopted_prefix_evidence_path is invalid")
            if not isinstance(adoption_digest, str) or not _SHA256.fullmatch(adoption_digest):
                raise FullPlanJobError("Gate job adopted prefix evidence digest is invalid")
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
        approval_digest = gate.get("approval_evidence_sha256")
        if approval_digest is not None and (not isinstance(approval_digest, str) or not _SHA256.fullmatch(approval_digest)):
            raise FullPlanJobError("Gate job approval evidence digest is invalid")
        engine_digest = gate.get("requirement_evidence_sha256")
        if engine_digest is not None:
            if not gate.get("requirement_evidence_path") or not isinstance(engine_digest, str) or not _SHA256.fullmatch(engine_digest):
                raise FullPlanJobError("Gate job engine requirement evidence digest is invalid")
        evidence_digests_by_lv = gate.get("requirement_evidence_sha256_by_lv")
        if evidence_digests_by_lv is not None:
            if (not isinstance(evidence_digests_by_lv, dict) or evidence_paths_by_lv is None
                    or set(evidence_digests_by_lv) != set(evidence_paths_by_lv)
                    or any(not isinstance(k, str) or not k or not isinstance(v, str) or not _SHA256.fullmatch(v)
                           for k, v in evidence_digests_by_lv.items())):
                raise FullPlanJobError("Gate job requirement evidence digest coverage mismatch")
    if len(set(ids)) != len(ids):
        raise FullPlanJobError("Full Plan job contains duplicate Gates")
    expected_head = job.get("expected_head")
    if expected_head is not None and (not isinstance(expected_head, str) or not _HEAD.fullmatch(expected_head)):
        raise FullPlanJobError("Full Plan job expected HEAD is invalid")
    release_digest = job.get("runtime_release_digest")
    release_head = job.get("runtime_release_source_head")
    if (release_digest is None) != (release_head is None):
        raise FullPlanJobError("Full Plan job runtime release binding is incomplete")
    if release_digest is not None:
        if (not isinstance(release_digest, str) or not _SHA256.fullmatch(release_digest)
                or not isinstance(release_head, str) or not _HEAD.fullmatch(release_head)):
            raise FullPlanJobError("Full Plan job runtime release binding is invalid")
    for field in ("activation_binding_digest", "executable_authority_bundle_digest", "ai_office_context_digest"):
        value = job.get(field)
        if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
            raise FullPlanJobError(f"Full Plan job {field} is invalid")
    recovery_successor = job.get("recovery_successor")
    if recovery_successor is not None:
        try:
            validate_recovery_successor_binding(
                recovery_successor,
                project_id=str(job["project_id"]),
                successor_run_id=str(job["run_id"]),
            )
        except ProductionFullPlanError as exc:
            raise FullPlanJobError(str(exc)) from exc
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


def _materialize_initial_registered_state(job: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a stable initial state before the registered job becomes discoverable."""
    gate_ids = [str(item["gate_id"]) for item in job["gates"]]
    supervisor = DurableFullPlanSupervisor(
        job_state_root(job), project_id=job["project_id"], run_id=job["run_id"], gates=gate_ids,
        authority_core_sha256=str(job.get("authority_core_sha256") or ""), **dict(job.get("policy") or {}),
    )
    current = supervisor.state_path
    previous = supervisor.state_path.with_suffix(".json.prev")
    if current.is_symlink() or previous.is_symlink():
        raise ProductionFullPlanError("unsafe Full Plan state generation")
    durable_exists = current.is_file() or previous.is_file()
    if canonical_job_path(job).exists() and not durable_exists:
        raise ProductionFullPlanError("durable Full Plan state is unavailable for registered job")
    handle = supervisor._acquire_run_lock()
    try:
        state, _ = supervisor.load()
        if durable_exists:
            return state
        return supervisor._persist(
            state,
            {"event": "INITIAL_STATE_MATERIALIZED", "source": "register_job"},
            semantic=False,
        )
    finally:
        supervisor._release_run_lock(handle)


def register_job(job: Mapping[str, Any]) -> Path:
    """Persist an immutable authority core and controlled runtime bindings."""
    incoming_bindings = extract_runtime_bindings(job)
    sealed = seal_authority_core(job)
    path = canonical_job_path(sealed)
    publish_new = False
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
        publish_new = True
    try:
        _materialize_initial_registered_state(sealed)
    except ProductionFullPlanError as exc:
        raise FullPlanJobError(str(exc)) from exc
    if publish_new:
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



def _verified_resume_checkpoint_head(
    job: Mapping[str, Any],
    resume_context: Mapping[str, Any] | None,
    current_head: str,
) -> bool:
    """Accept only the exact checkpoint sealed by this run's WORKER event."""
    if not isinstance(resume_context, Mapping):
        return False
    queue_item = resume_context.get("queue_item")
    state = resume_context.get("state")
    if not isinstance(queue_item, Mapping) or not isinstance(state, Mapping):
        return False
    if queue_item.get("resume") is not True:
        return False

    gate_id = str(queue_item.get("gate_id") or "")
    gate_run_id = str(queue_item.get("gate_run_id") or "")
    project_id = str(job.get("project_id") or "")
    expected_head = str(job.get("expected_head") or "")
    safe_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
    if (
        not safe_id.fullmatch(project_id)
        or not safe_id.fullmatch(gate_id)
        or not safe_id.fullmatch(gate_run_id)
        or gate_id != str(state.get("current_gate") or "")
        or not _HEAD.fullmatch(current_head)
        or not _HEAD.fullmatch(expected_head)
    ):
        return False

    project = Path(str(job["project_root"])).resolve()
    ancestry = subprocess.run(
        ["git", "-C", str(project), "merge-base", "--is-ancestor", expected_head, current_head],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if ancestry.returncode != 0:
        return False
    dirty = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain=v1", "-uall"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if dirty.returncode != 0 or dirty.stdout.strip():
        return False

    state_root = job_state_root(job)
    run_root = state_root / "_workspace" / "orchestration-runs"
    resume_root = state_root / "_workspace" / "global-gate-resume"
    if (
        run_root.is_symlink() or resume_root.is_symlink()
        or not run_root.is_dir() or not resume_root.is_dir()
    ):
        return False

    def has_symlink_component(base: Path, target: Path) -> bool:
        try:
            relative = target.relative_to(base)
        except ValueError:
            return True
        cursor = base
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return True
        return False

    run_candidates = [run_root / gate_run_id]
    run_candidates.extend(
        sorted(
            path for path in run_root.glob(f"{gate_run_id}-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    matches = 0
    for run_candidate in run_candidates:
        if (
            run_candidate.is_symlink() or not run_candidate.is_dir()
            or has_symlink_component(run_root, run_candidate)
        ):
            continue
        for result_path in sorted(run_candidate.glob("*/worker.result.json")):
            if (
                result_path.is_symlink() or not result_path.is_file()
                or has_symlink_component(run_root, result_path)
            ):
                continue
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(result, dict) or result.get("status") not in {"completed", "COMPLETED"}:
                continue

            lv_id = str(result.get("lv_id") or "")
            run_id = str(result.get("run_id") or "")
            checkpoint = str(result.get("checkpoint_commit") or "")
            baseline = str(result.get("baseline_head") or "")
            tree = str(result.get("current_tree") or "")
            if (
                not safe_id.fullmatch(lv_id)
                or not safe_id.fullmatch(run_id)
                or str(result.get("project_id") or "") != project_id
                or str(result.get("gate_id") or "") != gate_id
                or checkpoint != current_head
                or not _HEAD.fullmatch(baseline)
                or not _HEAD.fullmatch(tree)
            ):
                continue
            tree_probe = subprocess.run(
                ["git", "-C", str(project), "rev-parse", f"{current_head}^{{tree}}"],
                capture_output=True, text=True, check=False, timeout=10,
            )
            if tree_probe.returncode != 0 or tree_probe.stdout.strip() != tree:
                continue

            result_sha = sha256_file(result_path)
            event_pattern = f"*/{project_id}/{gate_id}/{lv_id}/{run_id}/events/000001.json"
            event_ones = sorted(resume_root.glob(event_pattern))
            verified = False
            for event_one in event_ones:
                if (
                    event_one.is_symlink() or not event_one.is_file()
                    or has_symlink_component(resume_root, event_one)
                ):
                    continue
                try:
                    first = _load_json(event_one)
                    from .resume_store import ResumeStore, RunBinding
                    binding = RunBinding(**dict(first.get("binding") or {}))
                    if (
                        binding.project_id != project_id
                        or binding.gate_id != gate_id
                        or binding.lv_id != lv_id
                        or binding.run_id != run_id
                        or binding.head != expected_head
                        or binding.branch != str(job.get("expected_branch") or "")
                    ):
                        continue
                    store = ResumeStore(event_one.parents[5], binding)
                    records = store.verify()
                except (FullPlanJobError, TypeError, ValueError, OSError):
                    continue
                if any(
                    record.get("lifecycle") == "WORKER"
                    and record.get("evidence_sha256") == result_sha
                    and isinstance(record.get("stage_payload"), Mapping)
                    and str(record["stage_payload"].get("checkpoint_commit") or "") == current_head
                    for record in records
                ):
                    verified = True
                    break
            if verified:
                matches += 1
    return matches == 1



def _verified_pre_result_partial_resume_head(
    job: Mapping[str, Any],
    resume_context: Mapping[str, Any] | None,
    current_head: str,
) -> bool:
    """Accept dirty resume only when the exact sealed pre-result partial source validates."""
    if not isinstance(resume_context, Mapping):
        return False
    queue_item = resume_context.get("queue_item")
    state = resume_context.get("state")
    if not isinstance(queue_item, Mapping) or not isinstance(state, Mapping):
        return False
    if queue_item.get("resume") is not True:
        return False

    gate_id = str(queue_item.get("gate_id") or "")
    gate_run_id = str(queue_item.get("gate_run_id") or "")
    project_id = str(job.get("project_id") or "")
    expected_head = str(job.get("expected_head") or "")
    expected_branch = str(job.get("expected_branch") or "")
    safe_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
    if (
        not safe_id.fullmatch(project_id)
        or not safe_id.fullmatch(gate_id)
        or not safe_id.fullmatch(gate_run_id)
        or gate_id != str(state.get("current_gate") or "")
        or not _HEAD.fullmatch(current_head)
        or not _HEAD.fullmatch(expected_head)
        or not expected_branch
    ):
        return False

    project = Path(str(job["project_root"])).resolve()
    ancestry = subprocess.run(
        ["git", "-C", str(project), "merge-base", "--is-ancestor", expected_head, current_head],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if ancestry.returncode != 0:
        return False

    state_root = job_state_root(job)
    run_root = state_root / "_workspace" / "orchestration-runs"
    if run_root.is_symlink() or not run_root.is_dir():
        return False

    candidates = [run_root / gate_run_id]
    candidates.extend(sorted(
        path for path in run_root.glob(f"{gate_run_id}-*")
        if path.is_dir() and not path.is_symlink()
    ))
    matches = 0
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        for manifest_path in sorted(candidate.glob("*/package.manifest.json")):
            package_root = manifest_path.parent
            preflight_path = package_root / "preflight" / "preflight.evidence.json"
            request_path = package_root / "worker.request.json"
            process_path = package_root / "executor.process.json"
            worker_result = package_root / "worker.result.json"
            if (
                manifest_path.is_symlink()
                or not preflight_path.is_file() or preflight_path.is_symlink()
                or not request_path.is_file() or request_path.is_symlink()
                or not process_path.is_file() or process_path.is_symlink()
                or worker_result.exists() or worker_result.is_symlink()
            ):
                continue
            try:
                manifest = _load_json(manifest_path)
            except FullPlanJobError:
                continue
            if (
                str(manifest.get("project_id") or "") != project_id
                or str(manifest.get("gate_id") or "") != gate_id
                or str(manifest.get("source_head") or "") != current_head
                or not str(manifest.get("run_id") or "").startswith(gate_run_id)
            ):
                continue
            approval_event_id = str(manifest.get("approval_id") or "")
            if not approval_event_id:
                continue
            try:
                from .recovery_contract import RecoveryError, prepare_pre_result_partial_recovery
                verified = prepare_pre_result_partial_recovery(
                    state_root,
                    project_root=project,
                    package_manifest_path=manifest_path,
                    preflight_path=preflight_path,
                    worker_request_path=request_path,
                    process_path=process_path,
                    approval_event_id=approval_event_id,
                    branch=expected_branch,
                    baseline_head=expected_head,
                    seal=False,
                )
            except (RecoveryError, OSError, ValueError, subprocess.SubprocessError):
                continue
            source = verified.get("source") if isinstance(verified, Mapping) else None
            if (
                verified.get("verified_only") is True
                and isinstance(source, Mapping)
                and str(source.get("current_head") or "") == current_head
                and str(source.get("source_head") or "") == current_head
            ):
                matches += 1
    return matches == 1


def _verified_completed_gate_lineage_head(
    job: Mapping[str, Any],
    resume_context: Mapping[str, Any] | None,
    current_head: str,
) -> dict[str, str] | None:
    """Accept a successor Gate only at the exact sealed terminal HEAD of the prior Gate."""
    if not isinstance(resume_context, Mapping):
        return None
    queue_item = resume_context.get("queue_item")
    state = resume_context.get("state")
    if not isinstance(queue_item, Mapping) or not isinstance(state, Mapping):
        return None
    if queue_item.get("resume") is True:
        return None

    completed = state.get("completed_gates")
    gate_ids = [str(item.get("gate_id") or "") for item in job.get("gates", []) if isinstance(item, Mapping)]
    if (
        not isinstance(completed, list) or not completed
        or completed != gate_ids[:len(completed)]
        or len(completed) >= len(gate_ids)
    ):
        return None
    current_gate = gate_ids[len(completed)]
    previous_gate = completed[-1]
    if (
        str(queue_item.get("gate_id") or "") != current_gate
        or str(state.get("current_gate") or "") != current_gate
    ):
        return None

    project_id = str(job.get("project_id") or "")
    full_run_id = str(job.get("run_id") or "")
    expected_head = str(job.get("expected_head") or "")
    expected_branch = str(job.get("expected_branch") or "")
    safe_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
    if (
        not safe_id.fullmatch(project_id)
        or not safe_id.fullmatch(full_run_id)
        or not safe_id.fullmatch(previous_gate)
        or not _HEAD.fullmatch(current_head)
        or not _HEAD.fullmatch(expected_head)
        or not expected_branch
    ):
        return None

    project = Path(str(job["project_root"])).resolve()
    ancestry = subprocess.run(
        ["git", "-C", str(project), "merge-base", "--is-ancestor", expected_head, current_head],
        capture_output=True, text=True, check=False, timeout=10,
    )
    dirty = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain=v1", "-uall"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if ancestry.returncode != 0 or dirty.returncode != 0 or dirty.stdout.strip():
        return None

    state_root = job_state_root(job)
    artifact_root = state_root / "_workspace" / "global-gate" / project_id / "artifact"
    run_root = state_root / "_workspace" / "orchestration-runs"
    resume_root = state_root / "_workspace" / "global-gate-resume"
    if any(path.is_symlink() or not path.is_dir() for path in (artifact_root, run_root, resume_root)):
        return None

    def has_symlink_component(base: Path, target: Path) -> bool:
        try:
            relative = target.relative_to(base)
        except ValueError:
            return True
        cursor = base
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return True
        return None

    previous_gate_run_id = f"{full_run_id}--{previous_gate.lower()}"
    candidates: list[dict[str, str]] = []
    for handoff_path in sorted(artifact_root.glob(f"{previous_gate_run_id}*.handoff.json")):
        if (
            handoff_path.is_symlink() or not handoff_path.is_file()
            or has_symlink_component(artifact_root, handoff_path)
        ):
            continue
        try:
            handoff = _load_json(handoff_path)
        except FullPlanJobError:
            continue
        unsigned = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
        handoff_sha = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        lv_id = str(handoff.get("lv") or "")
        run_id = str(handoff.get("run_id") or "")
        plan_sha = str(handoff.get("canonical_plan_sha256") or "")
        if (
            handoff.get("handoff_sha256") != handoff_sha
            or handoff.get("project") != project_id
            or handoff.get("gate") != previous_gate
            or handoff.get("branch") != expected_branch
            or handoff.get("remaining_plan_items") != []
            or handoff.get("hard_stop") is not True
            or not safe_id.fullmatch(lv_id)
            or not safe_id.fullmatch(run_id)
            or not (run_id == previous_gate_run_id or run_id.startswith(previous_gate_run_id + "-"))
            or not _SHA256.fullmatch(plan_sha)
        ):
            continue

        result_path = run_root / run_id / lv_id / "worker.result.json"
        if (
            result_path.is_symlink() or not result_path.is_file()
            or has_symlink_component(run_root, result_path)
        ):
            continue
        try:
            result = _load_json(result_path)
        except FullPlanJobError:
            continue
        baseline = str(result.get("baseline_head") or "")
        tree = str(result.get("current_tree") or "")
        if (
            result.get("status") not in {"completed", "COMPLETED"}
            or result.get("project_id") != project_id
            or result.get("gate_id") != previous_gate
            or result.get("lv_id") != lv_id
            or result.get("run_id") != run_id
            or result.get("plan_sha256") != plan_sha
            or result.get("checkpoint_commit") != current_head
            or str(result.get("current_head") or current_head) != current_head
            or not _HEAD.fullmatch(baseline)
            or not _HEAD.fullmatch(tree)
        ):
            continue
        result_sha = sha256_file(result_path)
        if handoff.get("head") != baseline:
            continue
        if handoff.get("artifact_sha256") != result_sha:
            continue
        if isinstance(handoff.get("review"), Mapping) and handoff["review"].get("worker_result_sha256") != result_sha:
            continue

        baseline_from_approval = subprocess.run(
            ["git", "-C", str(project), "merge-base", "--is-ancestor", expected_head, baseline],
            capture_output=True, text=True, check=False, timeout=10,
        )
        baseline_to_checkpoint = subprocess.run(
            ["git", "-C", str(project), "merge-base", "--is-ancestor", baseline, current_head],
            capture_output=True, text=True, check=False, timeout=10,
        )
        tree_probe = subprocess.run(
            ["git", "-C", str(project), "rev-parse", f"{current_head}^{{tree}}"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        if (
            baseline_from_approval.returncode != 0
            or baseline_to_checkpoint.returncode != 0
            or tree_probe.returncode != 0
            or tree_probe.stdout.strip() != tree
        ):
            continue

        event_pattern = f"*/{project_id}/{previous_gate}/{lv_id}/{run_id}/events/000001.json"
        verified = False
        for event_one in sorted(resume_root.glob(event_pattern)):
            if (
                event_one.is_symlink() or not event_one.is_file()
                or has_symlink_component(resume_root, event_one)
            ):
                continue
            try:
                first = _load_json(event_one)
                from .resume_store import ResumeStore, RunBinding
                binding = RunBinding(**dict(first.get("binding") or {}))
                if (
                    binding.project_id != project_id
                    or binding.gate_id != previous_gate
                    or binding.lv_id != lv_id
                    or binding.run_id != run_id
                    or binding.head != baseline
                    or binding.branch != expected_branch
                    or binding.plan_sha256 != plan_sha
                ):
                    continue
                records = ResumeStore(event_one.parents[5], binding).verify()
            except (FullPlanJobError, TypeError, ValueError, OSError):
                continue
            semantic_records = [
                record for record in records
                if not (
                    record.get("lifecycle") == "WORKER"
                    and not (
                        isinstance(record.get("stage_payload"), Mapping)
                        and isinstance(record["stage_payload"].get("checkpoint_commit"), str)
                        and record["stage_payload"].get("checkpoint_commit")
                    )
                )
            ]
            lifecycles = [str(record.get("lifecycle") or "") for record in semantic_records]
            if (
                len(semantic_records) < 7
                or lifecycles[:3] != ["PACKAGE", "PREFLIGHT", "WORKER"]
                or lifecycles[-3:] != ["CHECKPOINT", "EXIT", "HANDOFF"]
                or any(stage not in {"REVIEW", "REMEDIATION"} for stage in lifecycles[3:-3])
                or "REVIEW" not in lifecycles[3:-3]
            ):
                continue
            worker_record = semantic_records[2]
            checkpoint_record, exit_record, handoff_record = semantic_records[-3:]
            review_records = [record for record in semantic_records[3:-3] if record.get("lifecycle") == "REVIEW"]
            if (
                worker_record.get("evidence_sha256") != result_sha
                or not isinstance(worker_record.get("stage_payload"), Mapping)
                or str(worker_record["stage_payload"].get("checkpoint_commit") or "") != current_head
                or not review_records
                or not isinstance(review_records[-1].get("stage_payload"), Mapping)
                or review_records[-1]["stage_payload"].get("status") != "PASS"
                or checkpoint_record.get("checkpoint") is not True
                or not isinstance(exit_record.get("stage_payload"), Mapping)
                or exit_record["stage_payload"].get("status") != "EXITED"
                or handoff_record.get("evidence_sha256") != handoff_sha
                or not isinstance(handoff_record.get("stage_payload"), Mapping)
                or handoff_record["stage_payload"].get("status") != "SEALED"
            ):
                continue
            verified = True
            break
        if verified:
            candidates.append({
                "lineage_kind": "SEALED_PREVIOUS_GATE",
                "current_head": current_head,
                "predecessor_digest": handoff_sha,
                "predecessor_lv": lv_id,
                "predecessor_run_id": run_id,
            })
    return candidates[0] if len(candidates) == 1 else None


def _source_lineage_for_context(
    job: Mapping[str, Any],
    resume_context: Mapping[str, Any] | None,
    current_head: str,
) -> dict[str, str] | None:
    """Return one verified source-lineage token for the active Gate."""
    if job.get("recovery_successor") is not None:
        return _recovery_successor_source_lineage(job, resume_context, current_head)
    if _verified_resume_checkpoint_head(job, resume_context, current_head):
        queue_item = dict((resume_context or {}).get("queue_item") or {})
        gate_id = str(queue_item.get("gate_id") or "")
        gate_run_id = str(queue_item.get("gate_run_id") or "")
        run_root = job_state_root(job) / "_workspace" / "orchestration-runs"
        candidates: list[dict[str, str]] = []
        run_candidates = [run_root / gate_run_id]
        run_candidates.extend(sorted(path for path in run_root.glob(f"{gate_run_id}-*") if path.is_dir() and not path.is_symlink()))
        for run_candidate in run_candidates:
            for result_path in sorted(run_candidate.glob("*/worker.result.json")):
                if result_path.is_symlink() or not result_path.is_file():
                    continue
                try:
                    result = _load_json(result_path)
                except FullPlanJobError:
                    continue
                if (
                    result.get("status") not in {"completed", "COMPLETED"}
                    or result.get("project_id") != job.get("project_id")
                    or result.get("gate_id") != gate_id
                    or result.get("checkpoint_commit") != current_head
                ):
                    continue
                candidates.append({
                    "lineage_kind": "SEALED_WORKER_CHECKPOINT",
                    "current_head": current_head,
                    "predecessor_digest": sha256_file(result_path),
                    "predecessor_lv": str(result.get("lv_id") or ""),
                    "predecessor_run_id": str(result.get("run_id") or ""),
                })
        if len(candidates) == 1:
            return candidates[0]
        return None

    completed_gate_lineage = _verified_completed_gate_lineage_head(
        job, resume_context, current_head
    )
    if completed_gate_lineage is not None:
        return completed_gate_lineage
    return None



def _digest_without_field(value: Mapping[str, Any], field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != field}
    return hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _verified_recovery_artifact_path(
    state_root: Path, relative: object, expected_sha: object,
) -> Path | None:
    if (
        not isinstance(relative, str)
        or not isinstance(expected_sha, str)
        or not _SHA256.fullmatch(expected_sha)
        or "\\" in relative
    ):
        return None
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None
    path = state_root.joinpath(*relative_path.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(state_root)
    except (OSError, ValueError):
        return None
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected_sha:
        return None
    return path


def _chained_pre_result_source_path(
    state_root: Path,
    recovery_root: Path,
    record: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> Path | None:
    """Verify an append-only recovery chain and return its original pre-result source."""
    attempt = record.get("recovery_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 3:
        return None
    identity_fields = (
        "project_id", "gate_id", "lv_id", "run_id", "approval_event_id",
        "plan_sha256", "branch", "baseline_head", "current_head",
        "active_transition_sha256", "source_binding_kind",
    )
    chain_identity = {field: record.get(field) for field in identity_fields}
    chain_sources = record.get("source_shas")
    if not isinstance(chain_sources, Mapping) or not chain_sources:
        return None
    for relative, expected_sha in chain_sources.items():
        if _verified_recovery_artifact_path(state_root, relative, expected_sha) is None:
            return None

    current = dict(record)
    current_checkpoint = dict(checkpoint)
    seen_hashes: set[str] = set()
    while True:
        current_hash = current.get("record_hash")
        current_attempt = current.get("recovery_attempt")
        if (
            not isinstance(current_hash, str)
            or not _SHA256.fullmatch(current_hash)
            or current_hash in seen_hashes
            or current_hash != _digest_without_field(current, "record_hash")
            or not isinstance(current_attempt, int)
            or isinstance(current_attempt, bool)
            or current_attempt < 2
            or current.get("rejected_attempt") != current_attempt - 1
            or current.get("source_binding_kind") != "PRE_RESULT_PARTIAL_SOURCE"
            or current.get("hard_stop") is not True
            or any(current.get(field) != chain_identity[field] for field in identity_fields)
            or current.get("source_shas") != chain_sources
        ):
            return None
        seen_hashes.add(current_hash)
        if (
            current_checkpoint.get("checkpoint_sha256") != _digest_without_field(
                current_checkpoint, "checkpoint_sha256"
            )
            or current_checkpoint.get("recovery_id") != current.get("recovery_id")
            or current_checkpoint.get("recovery_record_hash") != current_hash
            or current_checkpoint.get("rejected_attempt") != current_attempt - 1
            or current_checkpoint.get("next_attempt") != current_attempt
            or current_checkpoint.get("source_binding_kind") != "PRE_RESULT_PARTIAL_SOURCE"
            or any(
                current_checkpoint.get(field) != current.get(field)
                for field in ("project_id", "gate_id", "lv_id", "run_id")
            )
        ):
            return None

        rejected = current.get("rejected_artifacts")
        if current_attempt == 2:
            if (
                current.get("predecessor") is not None
                or current.get("rejection_reason_code") != "REJECTED_PRE_RESULT_PARTIAL"
                or not isinstance(rejected, Mapping)
                or len(rejected) != 1
            ):
                return None
            relative, expected_sha = next(iter(rejected.items()))
            source_path = _verified_recovery_artifact_path(
                state_root, relative, expected_sha
            )
            if (
                source_path is None
                or expected_sha != current.get("active_transition_sha256")
                or chain_sources.get(relative) != expected_sha
            ):
                return None
            return source_path

        if (
            current.get("rejection_reason_code") != "REJECTED_RECOVERY_ATTEMPT_INCOMPLETE"
            or current.get("missing_bindings") != ["worker.result"]
            or not isinstance(rejected, Mapping)
            or len(rejected) != 3
        ):
            return None
        rejected_paths = {Path(str(relative)).name: (relative, sha) for relative, sha in rejected.items()}
        if set(rejected_paths) != {"package.json", "preflight.json", "worker.request.json"}:
            return None
        parents: set[Path] = set()
        for relative, expected_sha in rejected.items():
            verified = _verified_recovery_artifact_path(state_root, relative, expected_sha)
            if verified is None:
                return None
            parents.add(Path(str(relative)).parent)
        if len(parents) != 1:
            return None
        parent = next(iter(parents))
        expected_parent = Path("_workspace") / "orchestration-runs" / str(current["run_id"])
        expected_attempt = f"attempt-{current_attempt - 1:02d}"
        if (
            parent.parent != expected_parent
            or parent.name not in {expected_attempt, f"{expected_attempt}-{current['lv_id']}"}
            or current.get("supersedes") != rejected_paths["worker.request.json"][1]
        ):
            return None

        predecessor_hash = current.get("predecessor")
        if not isinstance(predecessor_hash, str) or not _SHA256.fullmatch(predecessor_hash):
            return None
        candidates: list[dict[str, Any]] = []
        for candidate_path in sorted(recovery_root.glob("*.json")):
            if candidate_path.name.endswith(".checkpoint.json") or candidate_path.is_symlink():
                continue
            try:
                candidate = _load_json(candidate_path)
            except FullPlanJobError:
                continue
            if candidate.get("record_hash") == predecessor_hash:
                candidates.append(candidate)
        if len(candidates) != 1:
            return None
        predecessor = candidates[0]
        if predecessor.get("recovery_attempt") != current_attempt - 1:
            return None
        predecessor_checkpoint_path = recovery_root / f"{predecessor.get('recovery_id')}.checkpoint.json"
        if predecessor_checkpoint_path.is_symlink() or not predecessor_checkpoint_path.is_file():
            return None
        try:
            predecessor_checkpoint = _load_json(predecessor_checkpoint_path)
        except FullPlanJobError:
            return None
        current = predecessor
        current_checkpoint = predecessor_checkpoint


def _verified_recovery_successor_binding(
    job: Mapping[str, Any],
    resume_context: Mapping[str, Any] | None,
    current_head: str,
) -> bool:
    raw = job.get("recovery_successor")
    if raw is None:
        return True
    try:
        binding = validate_recovery_successor_binding(
            raw,
            project_id=str(job.get("project_id") or ""),
            successor_run_id=str(job.get("run_id") or ""),
        )
    except ProductionFullPlanError:
        return False
    if (
        str(job.get("approval_ref") or "") != binding["approval_ref"]
        or str(job.get("activation_binding_digest") or "") != binding["binding_sha256"]
        or str(job.get("runtime_release_digest") or "") != binding["target_runtime_release_digest"]
        or str(job.get("runtime_release_source_head") or "") != binding["target_runtime_source_head"]
        or current_head != binding["current_head"]
        or not isinstance(resume_context, Mapping)
    ):
        return False
    state = resume_context.get("state")
    queue_item = resume_context.get("queue_item")
    if not isinstance(state, Mapping) or not isinstance(queue_item, Mapping):
        return False
    if dict(state.get("recovery_successor") or {}) != binding:
        return False
    if (
        str(state.get("current_gate") or "") != binding["gate_id"]
        or queue_item.get("resume") is not True
        or str(queue_item.get("gate_id") or "") != binding["gate_id"]
        or str(queue_item.get("gate_run_id") or "") != binding["predecessor_gate_run_id"]
    ):
        return False

    state_root = job_state_root(job)
    proof_relative = Path(binding["approval_proof_path"])
    proof_path = state_root.joinpath(*proof_relative.parts)
    try:
        resolved_proof = proof_path.resolve(strict=True)
        resolved_proof.relative_to(state_root)
    except (OSError, ValueError):
        return False
    if proof_path.is_symlink() or not proof_path.is_file():
        return False
    try:
        proof_value = _load_json(proof_path)
    except FullPlanJobError:
        return False
    if (
        sha256_file(proof_path) != binding["approval_proof_sha256"]
        or proof_value.get("approval_ref") != binding["approval_ref"]
        or not _approval_proof_is_fresh(proof_value)
        or not isinstance(proof_value.get("proof"), Mapping)
    ):
        return False
    project_id = str(job["project_id"])
    predecessor_run_id = binding["predecessor_run_id"]
    predecessor_job_path = (
        state_root / "_workspace" / "production-full-plan-jobs" / project_id
        / f"{predecessor_run_id}.job.json"
    )
    if predecessor_job_path.is_symlink() or not predecessor_job_path.is_file():
        return False
    try:
        predecessor_job = _load_json(predecessor_job_path)
        predecessor_authority = validate_authority_core(predecessor_job)
        predecessor_gates = [str(item["gate_id"]) for item in predecessor_job["gates"]]
        predecessor_supervisor = DurableFullPlanSupervisor(
            job_state_root(predecessor_job),
            project_id=project_id,
            run_id=predecessor_run_id,
            gates=predecessor_gates,
            authority_core_sha256=predecessor_authority,
            **dict(predecessor_job.get("policy") or {}),
        )
        predecessor_state, _ = predecessor_supervisor.load()
    except (FullPlanJobError, RunAuthorityError, ProductionFullPlanError, KeyError, TypeError, ValueError, OSError):
        return False
    if (
        predecessor_job.get("project_id") != project_id
        or predecessor_authority != binding["predecessor_authority_sha256"]
        or predecessor_state.get("state_sha256") != binding["predecessor_state_sha256"]
        or predecessor_state.get("state") != "BLOCKED"
        or predecessor_state.get("terminal_reason") != "PREFLIGHT_BLOCKED"
        or predecessor_state.get("last_error") != "SOURCE_HEAD_MISMATCH"
        or predecessor_state.get("current_gate") != binding["gate_id"]
        or predecessor_state.get("lease") is not None
    ):
        return False
    blocked = [
        item for item in predecessor_state.get("queue", [])
        if isinstance(item, Mapping)
        and item.get("status") == "BLOCKED"
        and item.get("gate_id") == binding["gate_id"]
    ]
    if (
        len(blocked) != 1
        or blocked[0].get("resume") is not True
        or blocked[0].get("gate_run_id") != binding["predecessor_gate_run_id"]
    ):
        return False

    recovery_root = (
        state_root / "_workspace" / "global-gate" / project_id / "recovery"
    )
    record_path = recovery_root / f"{binding['recovery_id']}.json"
    checkpoint_path = recovery_root / f"{binding['recovery_id']}.checkpoint.json"
    if (
        record_path.is_symlink() or checkpoint_path.is_symlink()
        or not record_path.is_file() or not checkpoint_path.is_file()
    ):
        return False
    try:
        record = _load_json(record_path)
        checkpoint = _load_json(checkpoint_path)
    except FullPlanJobError:
        return False

    if (
        record.get("record_hash") != binding["recovery_record_hash"]
        or record.get("record_hash") != _digest_without_field(record, "record_hash")
        or checkpoint.get("checkpoint_sha256") != binding["recovery_checkpoint_sha256"]
        or checkpoint.get("checkpoint_sha256") != _digest_without_field(checkpoint, "checkpoint_sha256")
        or record.get("recovery_id") != binding["recovery_id"]
        or checkpoint.get("recovery_id") != binding["recovery_id"]
        or checkpoint.get("recovery_record_hash") != binding["recovery_record_hash"]
        or record.get("gate_id") != binding["gate_id"]
        or checkpoint.get("gate_id") != binding["gate_id"]
        or record.get("current_head") != binding["current_head"]
        or record.get("baseline_head") != str(job.get("expected_head") or "")
        or record.get("branch") != str(job.get("expected_branch") or "")
        or record.get("source_binding_kind") != "PRE_RESULT_PARTIAL_SOURCE"
        or checkpoint.get("source_binding_kind") != "PRE_RESULT_PARTIAL_SOURCE"
    ):
        return False
    recovery_attempt = record.get("recovery_attempt")
    if isinstance(recovery_attempt, int) and not isinstance(recovery_attempt, bool) and recovery_attempt >= 3:
        source_path = _chained_pre_result_source_path(
            state_root, recovery_root, record, checkpoint
        )
        if source_path is None:
            return False
        expected_file_sha = str(record.get("active_transition_sha256") or "")
    else:
        rejected = record.get("rejected_artifacts")
        if not isinstance(rejected, Mapping) or len(rejected) != 1:
            return False
        relative, expected_file_sha = next(iter(rejected.items()))
        source_path = _verified_recovery_artifact_path(
            state_root, relative, expected_file_sha
        )
        if source_path is None:
            return False
    try:
        source = _load_json(source_path)
    except FullPlanJobError:
        return False
    actual_file_sha = sha256_file(source_path)
    source_unsigned = {key: item for key, item in source.items() if key != "source_payload_sha256"}
    source_payload_sha = hashlib.sha256(
        json.dumps(source_unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if (
        actual_file_sha != expected_file_sha
        or record.get("active_transition_sha256") != actual_file_sha
        or source.get("source_payload_sha256") != binding["recovery_source_payload_sha256"]
        or source.get("source_payload_sha256") != source_payload_sha
        or record.get("project_id") != project_id
        or checkpoint.get("project_id") != project_id
        or source.get("project_id") != project_id
        or not isinstance(source.get("lv_id"), str)
        or not source.get("lv_id")
        or record.get("lv_id") != source.get("lv_id")
        or checkpoint.get("lv_id") != source.get("lv_id")
        or record.get("run_id") != checkpoint.get("run_id")
        or record.get("run_id") != source.get("run_id")
        or source.get("current_head") != binding["current_head"]
        or source.get("source_head") != binding["current_head"]
        or source.get("gate_id") != binding["gate_id"]
        or not str(source.get("run_id") or "").startswith(binding["predecessor_gate_run_id"])
    ):
        return False
    return True


def _recovery_successor_source_lineage(
    job: Mapping[str, Any],
    resume_context: Mapping[str, Any] | None,
    current_head: str,
) -> dict[str, str] | None:
    if not _verified_recovery_successor_binding(job, resume_context, current_head):
        return None
    try:
        binding = validate_recovery_successor_binding(
            job["recovery_successor"],
            project_id=str(job["project_id"]),
            successor_run_id=str(job["run_id"]),
        )
    except (KeyError, ProductionFullPlanError):
        return None
    state_root = job_state_root(job)
    record_path = (
        state_root / "_workspace" / "global-gate" / str(job["project_id"])
        / "recovery" / f"{binding['recovery_id']}.json"
    )
    if record_path.is_symlink() or not record_path.is_file():
        return None
    try:
        record = _load_json(record_path)
    except FullPlanJobError:
        return None
    lv_id = str(record.get("lv_id") or "")
    predecessor_run_id = str(record.get("run_id") or "")
    if (
        not lv_id
        or not predecessor_run_id
        or record.get("record_hash") != binding["recovery_record_hash"]
        or record.get("source_binding_kind") != "PRE_RESULT_PARTIAL_SOURCE"
        or record.get("current_head") != current_head
    ):
        return None
    return {
        "lineage_kind": "SEALED_PRE_RESULT_PARTIAL_RECOVERY",
        "current_head": current_head,
        "predecessor_digest": binding["recovery_record_hash"],
        "predecessor_lv": lv_id,
        "predecessor_run_id": predecessor_run_id,
    }


def preflight_job(job: Mapping[str, Any], *, resume_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    expected_head = job.get("expected_head")
    current_head = ""
    if expected_head or job.get("recovery_successor") is not None:
        probe = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                               capture_output=True, text=True, check=False, timeout=10)
        current_head = probe.stdout.strip() if probe.returncode == 0 else ""
    if job.get("recovery_successor") is not None and not _verified_recovery_successor_binding(
        job, resume_context, current_head
    ):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "RECOVERY_SUCCESSOR_BINDING_MISMATCH"}
    if expected_head:
        if (
            current_head != expected_head
            and not _verified_resume_checkpoint_head(job, resume_context, current_head)
            and not _verified_pre_result_partial_resume_head(job, resume_context, current_head)
            and not _verified_completed_gate_lineage_head(job, resume_context, current_head)
        ):
            return {"status": "BLOCK", "state": "BLOCKED", "reason": "SOURCE_HEAD_MISMATCH"}
    release_digest = str(job.get("runtime_release_digest") or "")
    release_head = str(job.get("runtime_release_source_head") or "")
    if release_digest or release_head:
        if not (_SHA256.fullmatch(release_digest) and _HEAD.fullmatch(release_head)):
            return {"status": "BLOCK", "state": "BLOCKED", "reason": "RUNTIME_RELEASE_BINDING_INVALID"}
        runtime = Path(str(job.get("runtime_code_root") or job["harness_root"])).resolve()
        try:
            release = verify_runtime_release(runtime, release_head)
        except (RuntimeReleaseError, OSError, ValueError):
            return {"status": "BLOCK", "state": "BLOCKED", "reason": "RUNTIME_RELEASE_DRIFT"}
        if release.manifest_sha256 != release_digest:
            return {"status": "BLOCK", "state": "BLOCKED", "reason": "RUNTIME_RELEASE_DRIFT"}
    for gate in job.get("gates", []):
        checks: list[tuple[object, object, str]] = []
        if "approval_evidence_sha256" in gate:
            checks.append((gate.get("approval_evidence"), gate.get("approval_evidence_sha256"), "approval"))
        if "requirement_evidence_sha256" in gate:
            checks.append((gate.get("requirement_evidence_path"), gate.get("requirement_evidence_sha256"), "engine_requirement"))
        if "requirement_evidence_sha256_by_lv" in gate:
            for lv_id, evidence_path in dict(gate.get("requirement_evidence_paths_by_lv") or {}).items():
                expected = dict(gate.get("requirement_evidence_sha256_by_lv") or {}).get(lv_id)
                checks.append((evidence_path, expected, f"project_requirement:{lv_id}"))
        if "adopted_prefix_evidence_sha256" in gate:
            checks.append((gate.get("adopted_prefix_evidence_path"), gate.get("adopted_prefix_evidence_sha256"), "prefix_adoption"))
        for evidence_path, expected, label in checks:
            source = Path(str(evidence_path or ""))
            if (not isinstance(expected, str) or not _SHA256.fullmatch(expected)
                    or source.is_symlink() or not source.is_file()):
                reason = "PREFIX_ADOPTION_EVIDENCE_DRIFT" if label == "prefix_adoption" else f"GATE_AUTHORITY_EVIDENCE_DRIFT:{gate['gate_id']}:{label}"
                return {"status": "BLOCK", "state": "BLOCKED", "reason": reason}
            try:
                actual = sha256_file(source)
            except OSError:
                reason = "PREFIX_ADOPTION_EVIDENCE_DRIFT" if label == "prefix_adoption" else f"GATE_AUTHORITY_EVIDENCE_DRIFT:{gate['gate_id']}:{label}"
                return {"status": "BLOCK", "state": "BLOCKED", "reason": reason}
            if actual != expected:
                reason = "PREFIX_ADOPTION_EVIDENCE_DRIFT" if label == "prefix_adoption" else f"GATE_AUTHORITY_EVIDENCE_DRIFT:{gate['gate_id']}:{label}"
                return {"status": "BLOCK", "state": "BLOCKED", "reason": reason}
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
    if job.get("executor_kind") == "DCC_LIVE_AUTO_CANARY":
        from .live_auto_canary import build_live_auto_canary_executor
        return build_live_auto_canary_executor(job)
    project_root = str(Path(str(job["project_root"])).resolve())
    harness_root = str(job_state_root(job))
    specs = {str(item["gate_id"]): dict(item) for item in job["gates"]}

    def execute(gate_id: str, gate_run_id: str, resume: bool) -> Mapping[str, Any]:
        from .gate_orchestrator import FULL_PLAN, execute_gate
        spec = specs[gate_id]
        source_lineage = None
        head_probe = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        current_head = head_probe.stdout.strip() if head_probe.returncode == 0 else ""
        if current_head and current_head != str(spec["head"]):
            gates = [str(item["gate_id"]) for item in job["gates"]]
            supervisor = DurableFullPlanSupervisor(
                job_state_root(job), project_id=job["project_id"], run_id=job["run_id"],
                gates=gates, authority_core_sha256=str(job.get("authority_core_sha256") or ""),
                **dict(job.get("policy") or {}),
            )
            state, _ = supervisor.load()
            queue_items = [
                item for item in state.get("queue", [])
                if isinstance(item, Mapping) and item.get("gate_id") == gate_id
            ]
            if len(queue_items) != 1:
                raise FullPlanJobError("active Gate queue lineage is missing or ambiguous")
            source_lineage = _source_lineage_for_context(
                job,
                {"state": state, "queue_item": dict(queue_items[0])},
                current_head,
            )
            if source_lineage is None:
                raise FullPlanJobError("sealed Full Plan source lineage is required")
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
            source_lineage=source_lineage,
        )
    return execute


def run_job(path: str | Path) -> dict[str, Any]:
    requested = load_job(path)
    canonical = register_job(requested)
    job = load_registered_job(canonical)
    try:
        execution_owner = resolve_execution_owner(job)
    except RunAuthorityError as exc:
        raise FullPlanJobError(str(exc)) from exc
    if execution_owner != AUTO_RECONCILE_OWNER:
        raise FullPlanJobError(
            f"EXECUTION_OWNER_MISMATCH: generic Full Plan runner requires {AUTO_RECONCILE_OWNER}"
        )
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
        result = supervisor.run(
            build_gate_executor(job),
            preflight=lambda context: preflight_job(job, resume_context=context),
        ).to_dict()
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