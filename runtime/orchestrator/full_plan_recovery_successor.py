"""Fail-closed recovery successor for AUTO_RECONCILE Full Plan jobs.

This path does not mint or weaken Gate authority.  It may carry one already
approved Gate forward only when a predecessor terminal block is exactly bound
to a sealed pre-result partial recovery record.  The successor receives a
fresh run identity, runtime release, and owner approval reference while
preserving the predecessor gate_run_id solely as recovery evidence lineage.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .execution_lifecycle_v2 import (
    _build_execution_authority_bundle,
    validate_execution_authority_bundle,
)
from .gate_orchestrator import validate_global_gate_bindings
from .production_full_plan_entry import (
    FullPlanJobError,
    _approval_proof_is_fresh,
    canonical_job_path,
    load_registered_job,
    preflight_job,
    register_job,
)
from .production_full_plan_runner import (
    DurableFullPlanSupervisor,
    ProductionFullPlanError,
    RECOVERY_SUCCESSOR_BINDING_SCHEMA,
    validate_recovery_successor_binding,
)
from .production_run_authority import (
    AUTO_RECONCILE_OWNER,
    executor_runtime_identity,
    resolve_execution_owner,
    seal_authority_core,
    validate_authority_core,
)
from .recovery_contract import (
    RecoveryError,
    canonical_recovery_binding,
    prepare_pre_result_partial_recovery,
)
from .runtime_release import RuntimeReleaseError, verify_runtime_release


class FullPlanRecoverySuccessorError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        raise FullPlanRecoverySuccessorError("recovery successor Git verification failed")
    return result.stdout.strip()


def _predecessor_supervisor(job: Mapping[str, Any]) -> DurableFullPlanSupervisor:
    gates = [str(item["gate_id"]) for item in job["gates"]]
    return DurableFullPlanSupervisor(
        str(job.get("harness_state_root") or job["harness_root"]),
        project_id=str(job["project_id"]),
        run_id=str(job["run_id"]),
        gates=gates,
        authority_core_sha256=str(job["authority_core_sha256"]),
        **dict(job.get("policy") or {}),
    )


def _blocked_queue_item(state: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        dict(item)
        for item in state.get("queue", [])
        if isinstance(item, Mapping)
        and item.get("status") == "BLOCKED"
        and item.get("gate_id") == state.get("current_gate")
    ]
    if len(rows) != 1:
        raise FullPlanRecoverySuccessorError(
            "predecessor blocked queue is missing or ambiguous"
        )
    item = rows[0]
    if item.get("resume") is not True or not str(item.get("gate_run_id") or ""):
        raise FullPlanRecoverySuccessorError(
            "predecessor blocked queue lacks resume lineage"
        )
    return item



def _approval_proof_reference(
    state_root: Path,
    raw_path: str | Path,
    *,
    approval_ref: str,
) -> tuple[str, str]:
    supplied = Path(raw_path).expanduser()
    target = supplied.absolute() if supplied.is_absolute() else state_root.joinpath(*supplied.parts)
    try:
        resolved = target.resolve(strict=True)
        relative = resolved.relative_to(state_root)
    except (OSError, ValueError) as exc:
        raise FullPlanRecoverySuccessorError(
            "approval proof must be a regular file under Harness state root"
        ) from exc
    if target.is_symlink() or not target.is_file():
        raise FullPlanRecoverySuccessorError("approval proof is missing or unsafe")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullPlanRecoverySuccessorError("approval proof is malformed") from exc
    if (
        not isinstance(value, dict)
        or value.get("approval_ref") != approval_ref
        or not _approval_proof_is_fresh(value)
        or not isinstance(value.get("proof"), dict)
    ):
        raise FullPlanRecoverySuccessorError("approval proof binding mismatch")
    return relative.as_posix(), hashlib.sha256(target.read_bytes()).hexdigest()


def _validated_gate_evidence_override(
    predecessor_job: Mapping[str, Any],
    blocked_item: Mapping[str, Any],
    raw_path: str | Path,
) -> dict[str, str]:
    state_root = Path(
        str(predecessor_job.get("harness_state_root") or predecessor_job["harness_root"])
    ).resolve()
    supplied = Path(raw_path).expanduser()
    target = supplied.absolute() if supplied.is_absolute() else state_root.joinpath(*supplied.parts)
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(state_root)
    except (OSError, ValueError) as exc:
        raise FullPlanRecoverySuccessorError(
            "fresh Gate approval evidence must be a regular file under Harness state root"
        ) from exc
    if target.is_symlink() or not target.is_file():
        raise FullPlanRecoverySuccessorError("fresh Gate approval evidence is missing or unsafe")

    gate_id = str(blocked_item.get("gate_id") or "")
    matches = [
        dict(item)
        for item in predecessor_job.get("gates", [])
        if isinstance(item, Mapping) and str(item.get("gate_id") or "") == gate_id
    ]
    if len(matches) != 1:
        raise FullPlanRecoverySuccessorError(
            "fresh Gate approval evidence target is missing or ambiguous"
        )
    gate = matches[0]
    try:
        verdict = validate_global_gate_bindings(
            predecessor_job["project_root"],
            gate_id,
            requirements_sha256=str(gate["requirements_sha256"]),
            approval_evidence=resolved,
            branch=str(gate["branch"]),
            head=str(gate["head"]),
            harness_root=state_root,
            mapping_root=predecessor_job.get("mapping_root"),
        )
    except (OSError, ValueError) as exc:
        raise FullPlanRecoverySuccessorError(
            f"fresh Gate approval evidence validation failed: {exc}"
        ) from exc
    if (
        verdict.get("status") != "VALIDATED"
        or verdict.get("project_id") != predecessor_job.get("project_id")
        or verdict.get("gate_id") != gate_id
        or verdict.get("requirements_sha256") != gate.get("requirements_sha256")
        or verdict.get("plan_sha256") != predecessor_job.get("approved_plan_sha256")
    ):
        raise FullPlanRecoverySuccessorError("fresh Gate approval evidence binding mismatch")
    return {
        "gate_id": gate_id,
        "path": str(resolved),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def _seal_exact_pre_result_recovery(
    predecessor_job: Mapping[str, Any],
    predecessor_state: Mapping[str, Any],
    current_head: str,
) -> dict[str, Any]:
    state_root = Path(
        str(predecessor_job.get("harness_state_root") or predecessor_job["harness_root"])
    ).resolve()
    project = Path(str(predecessor_job["project_root"])).resolve()
    item = _blocked_queue_item(predecessor_state)
    gate_run_id = str(item["gate_run_id"])
    gate_id = str(item["gate_id"])
    run_root = state_root / "_workspace" / "orchestration-runs"
    if run_root.is_symlink() or not run_root.is_dir():
        raise FullPlanRecoverySuccessorError("orchestration run root is unsafe")

    candidates: list[tuple[Path, Path, Path, Path, str]] = []
    roots = [run_root / gate_run_id]
    roots.extend(
        sorted(
            path
            for path in run_root.glob(f"{gate_run_id}-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    for candidate in roots:
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
                or not preflight_path.is_file()
                or preflight_path.is_symlink()
                or not request_path.is_file()
                or request_path.is_symlink()
                or not process_path.is_file()
                or process_path.is_symlink()
                or worker_result.exists()
                or worker_result.is_symlink()
            ):
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(manifest, dict)
                or manifest.get("project_id") != predecessor_job.get("project_id")
                or manifest.get("gate_id") != gate_id
                or manifest.get("source_head") != current_head
                or not str(manifest.get("run_id") or "").startswith(gate_run_id)
            ):
                continue
            approval_event_id = str(manifest.get("approval_id") or "")
            if not approval_event_id:
                continue
            kwargs = {
                "project_root": project,
                "package_manifest_path": manifest_path,
                "preflight_path": preflight_path,
                "worker_request_path": request_path,
                "process_path": process_path,
                "approval_event_id": approval_event_id,
                "branch": str(predecessor_job.get("expected_branch") or ""),
                "baseline_head": str(predecessor_job.get("expected_head") or ""),
                "seal": False,
            }
            try:
                verified = prepare_pre_result_partial_recovery(state_root, **kwargs)
            except (RecoveryError, OSError, ValueError, subprocess.SubprocessError):
                continue
            source = verified.get("source")
            if (
                verified.get("verified_only") is True
                and isinstance(source, Mapping)
                and source.get("current_head") == current_head
                and source.get("source_head") == current_head
            ):
                candidates.append(
                    (
                        manifest_path,
                        preflight_path,
                        request_path,
                        process_path,
                        approval_event_id,
                    )
                )
    if len(candidates) != 1:
        raise FullPlanRecoverySuccessorError(
            "exactly one verified pre-result partial source is required"
        )
    manifest_path, preflight_path, request_path, process_path, approval_event_id = (
        candidates[0]
    )
    try:
        prepared = prepare_pre_result_partial_recovery(
            state_root,
            project_root=project,
            package_manifest_path=manifest_path,
            preflight_path=preflight_path,
            worker_request_path=request_path,
            process_path=process_path,
            approval_event_id=approval_event_id,
            branch=str(predecessor_job.get("expected_branch") or ""),
            baseline_head=str(predecessor_job.get("expected_head") or ""),
            seal=True,
        )
        canonical_recovery_binding(prepared["recovery"], prepared["checkpoint"])
    except (RecoveryError, KeyError, OSError, ValueError) as exc:
        raise FullPlanRecoverySuccessorError(
            f"pre-result recovery sealing failed: {exc}"
        ) from exc
    return prepared


def _build_binding(
    *,
    predecessor_job: Mapping[str, Any],
    predecessor_state: Mapping[str, Any],
    blocked_item: Mapping[str, Any],
    prepared: Mapping[str, Any],
    successor_run_id: str,
    approval_ref: str,
    approval_proof_path: str,
    approval_proof_sha256: str,
    target_release_digest: str,
    target_release_source_head: str,
) -> dict[str, Any]:
    recovery = prepared.get("recovery")
    checkpoint = prepared.get("checkpoint")
    source = prepared.get("source")
    if not all(isinstance(item, Mapping) for item in (recovery, checkpoint, source)):
        raise FullPlanRecoverySuccessorError("sealed recovery evidence is incomplete")
    binding = {
        "schema_version": RECOVERY_SUCCESSOR_BINDING_SCHEMA,
        "project_id": str(predecessor_job["project_id"]),
        "successor_run_id": successor_run_id,
        "predecessor_run_id": str(predecessor_job["run_id"]),
        "predecessor_authority_sha256": str(
            predecessor_job["authority_core_sha256"]
        ),
        "predecessor_state_sha256": str(predecessor_state["state_sha256"]),
        "gate_id": str(blocked_item["gate_id"]),
        "predecessor_gate_run_id": str(blocked_item["gate_run_id"]),
        "current_head": str(source["current_head"]),
        "recovery_id": str(recovery["recovery_id"]),
        "recovery_record_hash": str(recovery["record_hash"]),
        "recovery_checkpoint_sha256": str(checkpoint["checkpoint_sha256"]),
        "recovery_source_payload_sha256": str(source["source_payload_sha256"]),
        "target_runtime_release_digest": target_release_digest,
        "target_runtime_source_head": target_release_source_head,
        "approval_ref": approval_ref,
        "approval_proof_path": approval_proof_path,
        "approval_proof_sha256": approval_proof_sha256,
    }
    binding["binding_sha256"] = _digest(binding)
    try:
        return validate_recovery_successor_binding(
            binding,
            project_id=str(predecessor_job["project_id"]),
            successor_run_id=successor_run_id,
        )
    except ProductionFullPlanError as exc:
        raise FullPlanRecoverySuccessorError(str(exc)) from exc


def _build_successor_job(
    predecessor_job: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    runtime_code_root: Path,
    gate_evidence_override: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    job = copy.deepcopy(dict(predecessor_job))
    for field in ("authority_schema_version", "authority_core_sha256"):
        job.pop(field, None)
    job["run_id"] = binding["successor_run_id"]
    job["approval_ref"] = binding["approval_ref"]
    job["runtime_code_root"] = str(runtime_code_root)
    job["runtime_release_digest"] = binding["target_runtime_release_digest"]
    job["runtime_release_source_head"] = binding["target_runtime_source_head"]
    job["executor_runtime_identity"] = executor_runtime_identity(runtime_code_root)
    job["recovery_successor"] = dict(binding)
    job["activation_binding_digest"] = binding["binding_sha256"]

    if gate_evidence_override is not None:
        gate_id = str(gate_evidence_override.get("gate_id") or "")
        matches = [
            index
            for index, item in enumerate(job.get("gates", []))
            if isinstance(item, Mapping) and str(item.get("gate_id") or "") == gate_id
        ]
        if len(matches) != 1:
            raise FullPlanRecoverySuccessorError(
                "fresh Gate approval evidence target is missing or ambiguous"
            )
        gate = dict(job["gates"][matches[0]])
        gate["approval_evidence"] = str(gate_evidence_override["path"])
        gate["approval_evidence_sha256"] = str(gate_evidence_override["sha256"])
        gates = list(job["gates"])
        gates[matches[0]] = gate
        job["gates"] = gates

    lifecycle = dict(job.get("lifecycle_binding") or {})
    if (
        lifecycle.get("schema_version") != "orchestration.lifecycle-binding.v1"
        or lifecycle.get("lifecycle_mode") != "V2"
        or lifecycle.get("bound_at_activation") is not True
        or lifecycle.get("migration_allowed") is not False
    ):
        raise FullPlanRecoverySuccessorError(
            "recovery successor requires an existing activation-bound V2 job"
        )
    lifecycle["runtime_release_digest"] = binding["target_runtime_release_digest"]
    job["lifecycle_binding"] = lifecycle
    job["execution_authority_bundle"] = _build_execution_authority_bundle(
        job, lifecycle
    )
    validate_execution_authority_bundle(job)
    job["executable_authority_bundle_digest"] = str(
        job["execution_authority_bundle"]["bundle_sha256"]
    )
    job["ai_office_context_digest"] = _digest(
        {
            "schema_version": "orchestration.full-plan-recovery-context.v1",
            "project_id": job["project_id"],
            "run_id": job["run_id"],
            "approval_ref": job["approval_ref"],
            "activation_binding_digest": job["activation_binding_digest"],
            "executable_authority_bundle_digest": job[
                "executable_authority_bundle_digest"
            ],
            "predecessor_run_id": binding["predecessor_run_id"],
            "recovery_id": binding["recovery_id"],
        }
    )
    return seal_authority_core(job)


def prepare_recovery_successor(
    predecessor_job_path: str | Path,
    *,
    target_runtime_release: str | Path,
    target_runtime_source_head: str,
    successor_run_id: str,
    approval_ref: str,
    approval_proof_path: str | Path,
    fresh_gate_approval_evidence: str | Path | None = None,
) -> dict[str, Any]:
    predecessor_path = Path(predecessor_job_path).resolve()
    try:
        predecessor_job = load_registered_job(predecessor_path)
        if canonical_job_path(predecessor_job).resolve() != predecessor_path:
            raise FullPlanRecoverySuccessorError(
                "predecessor job is not the canonical registered job"
            )
        if resolve_execution_owner(predecessor_job) != AUTO_RECONCILE_OWNER:
            raise FullPlanRecoverySuccessorError(
                "recovery successor requires AUTO_RECONCILE predecessor"
            )
        predecessor_authority = validate_authority_core(predecessor_job)
        predecessor_supervisor = _predecessor_supervisor(predecessor_job)
        predecessor_state, _ = predecessor_supervisor.load()
    except (
        FullPlanJobError,
        ProductionFullPlanError,
        KeyError,
        OSError,
        ValueError,
    ) as exc:
        if isinstance(exc, FullPlanRecoverySuccessorError):
            raise
        raise FullPlanRecoverySuccessorError(
            f"predecessor validation failed: {exc}"
        ) from exc

    blocked_item = _blocked_queue_item(predecessor_state)
    if (
        predecessor_state.get("state") != "BLOCKED"
        or predecessor_state.get("terminal_reason") != "PREFLIGHT_BLOCKED"
        or predecessor_state.get("last_error") != "SOURCE_HEAD_MISMATCH"
        or predecessor_state.get("lease") is not None
        or predecessor_authority != predecessor_job.get("authority_core_sha256")
    ):
        raise FullPlanRecoverySuccessorError(
            "predecessor is not an eligible blocked pre-result partial run"
        )

    state_root = Path(
        str(predecessor_job.get("harness_state_root") or predecessor_job["harness_root"])
    ).resolve()
    proof_relative, proof_sha256 = _approval_proof_reference(
        state_root, approval_proof_path, approval_ref=approval_ref,
    )
    gate_evidence_override = None
    if fresh_gate_approval_evidence is not None:
        gate_evidence_override = _validated_gate_evidence_override(
            predecessor_job, blocked_item, fresh_gate_approval_evidence
        )
    project = Path(str(predecessor_job["project_root"])).resolve()
    current_head = _git(project, "rev-parse", "HEAD")
    prepared = _seal_exact_pre_result_recovery(
        predecessor_job, predecessor_state, current_head
    )

    runtime_root = Path(target_runtime_release).expanduser().absolute()
    try:
        release = verify_runtime_release(runtime_root, target_runtime_source_head)
    except (RuntimeReleaseError, OSError, ValueError) as exc:
        raise FullPlanRecoverySuccessorError(
            f"target runtime verification failed: {exc}"
        ) from exc

    binding = _build_binding(
        predecessor_job=predecessor_job,
        predecessor_state=predecessor_state,
        blocked_item=blocked_item,
        prepared=prepared,
        successor_run_id=successor_run_id,
        approval_ref=approval_ref,
        approval_proof_path=proof_relative,
        approval_proof_sha256=proof_sha256,
        target_release_digest=release.manifest_sha256,
        target_release_source_head=release.source_head,
    )
    successor_job = _build_successor_job(
        predecessor_job,
        binding=binding,
        runtime_code_root=runtime_root,
        gate_evidence_override=gate_evidence_override,
    )
    gates = [str(item["gate_id"]) for item in successor_job["gates"]]
    successor_supervisor = DurableFullPlanSupervisor(
        str(successor_job.get("harness_state_root") or successor_job["harness_root"]),
        project_id=str(successor_job["project_id"]),
        run_id=str(successor_job["run_id"]),
        gates=gates,
        authority_core_sha256=str(successor_job["authority_core_sha256"]),
        **dict(successor_job.get("policy") or {}),
    )
    preview_state = successor_supervisor.build_recovery_successor_state(
        predecessor_state=predecessor_state,
        recovery_binding=binding,
    )
    active = [
        item
        for item in preview_state["queue"]
        if item.get("status") == "READY"
    ]
    if len(active) != 1:
        raise FullPlanRecoverySuccessorError(
            "recovery successor preview queue is invalid"
        )
    verdict = preflight_job(
        successor_job,
        resume_context={"state": preview_state, "queue_item": active[0]},
    )
    if verdict.get("status") != "PASS":
        raise FullPlanRecoverySuccessorError(
            "recovery successor preflight blocked: "
            + str(verdict.get("reason") or "UNKNOWN")
        )
    return {
        "predecessor_job": predecessor_job,
        "predecessor_state": predecessor_state,
        "successor_job": successor_job,
        "successor_preview_state": preview_state,
        "recovery_binding": binding,
        "sealed_recovery": prepared,
        "preflight": verdict,
    }


def register_recovery_successor(
    predecessor_job_path: str | Path,
    *,
    target_runtime_release: str | Path,
    target_runtime_source_head: str,
    successor_run_id: str,
    approval_ref: str,
    approval_proof_path: str | Path,
    fresh_gate_approval_evidence: str | Path | None = None,
) -> dict[str, Any]:
    prepared = prepare_recovery_successor(
        predecessor_job_path,
        target_runtime_release=target_runtime_release,
        target_runtime_source_head=target_runtime_source_head,
        successor_run_id=successor_run_id,
        approval_ref=approval_ref,
        approval_proof_path=approval_proof_path,
        fresh_gate_approval_evidence=fresh_gate_approval_evidence,
    )
    job = prepared["successor_job"]
    predecessor_state = prepared["predecessor_state"]
    binding = prepared["recovery_binding"]
    canonical = canonical_job_path(job)
    existed = canonical.exists()
    supervisor = DurableFullPlanSupervisor(
        str(job.get("harness_state_root") or job["harness_root"]),
        project_id=str(job["project_id"]),
        run_id=str(job["run_id"]),
        gates=[str(item["gate_id"]) for item in job["gates"]],
        authority_core_sha256=str(job["authority_core_sha256"]),
        **dict(job.get("policy") or {}),
    )
    seeded = supervisor.seed_recovery_successor(
        predecessor_state=predecessor_state,
        recovery_binding=binding,
    )
    try:
        registered_path = register_job(job)
        registered = load_registered_job(registered_path)
    except (FullPlanJobError, ProductionFullPlanError, OSError, ValueError) as exc:
        raise FullPlanRecoverySuccessorError(
            f"recovery successor registration failed: {exc}"
        ) from exc
    if (
        registered.get("authority_core_sha256") != job["authority_core_sha256"]
        or registered.get("recovery_successor") != binding
        or seeded.get("recovery_successor") != binding
    ):
        raise FullPlanRecoverySuccessorError(
            "registered recovery successor binding mismatch"
        )
    return {
        "status": "ALREADY_REGISTERED" if existed else "REGISTERED",
        "project_id": str(job["project_id"]),
        "predecessor_run_id": binding["predecessor_run_id"],
        "successor_run_id": str(job["run_id"]),
        "canonical_job_path": str(registered_path),
        "authority_core_sha256": str(job["authority_core_sha256"]),
        "state_sha256": str(seeded["state_sha256"]),
        "recovery_binding_sha256": str(binding["binding_sha256"]),
        "recovery_id": str(binding["recovery_id"]),
        "preflight_status": str(prepared["preflight"]["status"]),
    }
