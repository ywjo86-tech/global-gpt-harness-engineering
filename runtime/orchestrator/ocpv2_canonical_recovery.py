"""Recover OCP result bookkeeping from exact registered Full Plan evidence.

Recovery has no execution callback.  It may inspect already-registered canonical state,
enqueue a downstream result projection, and retry transport publication.  Missing or
mismatched evidence remains unresolved and can never cause canonical re-execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .harness_state_root import job_state_root
from .production_full_plan_entry import canonical_job_path, load_registered_job
from .production_full_plan_runner import DurableFullPlanSupervisor
from .remote_operator_ingress import CanonicalCompletionEvidence
from .remote_operator_outbox import RemoteResultOutbox, RemoteResultProjectionV1
from .remote_operator_receipt import RemoteOperatorReceiptStore
from .remote_operator_recovery_binding import (
    RemoteExecutionBindingStore,
    RemoteExecutionBindingV1,
)


def _evidence_matches(binding: RemoteExecutionBindingV1, evidence: CanonicalCompletionEvidence) -> bool:
    return (
        evidence.message_id == binding.message_id
        and evidence.directive_digest == binding.directive_digest
        and evidence.project_id == binding.project_id
        and evidence.run_id == binding.run_id
        and evidence.gate_id == binding.gate_id
        and evidence.task_id == binding.task_id
        and bool(evidence.canonical_state_ref)
        and len(evidence.canonical_state_sha256) == 64
        and all(ch in "0123456789abcdef" for ch in evidence.canonical_state_sha256)
    )


def projection_from_evidence(
    binding: RemoteExecutionBindingV1,
    evidence: CanonicalCompletionEvidence,
) -> RemoteResultProjectionV1 | None:
    if not _evidence_matches(binding, evidence):
        return None
    return RemoteResultProjectionV1(
        projection_id=f"REC-{binding.envelope_sha256[:24]}",
        message_id=binding.message_id,
        directive_digest=binding.directive_digest,
        project_id=binding.project_id,
        run_id=binding.run_id,
        gate_id=binding.gate_id,
        task_id=binding.task_id,
        canonical_state_ref=evidence.canonical_state_ref,
        canonical_state_sha256=evidence.canonical_state_sha256,
        effect_evidence_refs=tuple(evidence.effect_evidence_refs),
        checkpoint_ref=evidence.checkpoint_ref,
        checkpoint_sha256=evidence.checkpoint_sha256,
        migration_transaction_sha256=evidence.migration_transaction_sha256,
        result_class="CANONICAL_ACTION_COMPLETED",
        result_summary=evidence.result_summary,
        projected_at=evidence.completed_at,
    )


def recover_pending_canonical_results(
    *,
    binding_store: RemoteExecutionBindingStore,
    receipt_store: RemoteOperatorReceiptStore,
    outbox: RemoteResultOutbox,
    evidence_resolver: Callable[[RemoteExecutionBindingV1], CanonicalCompletionEvidence | None],
    publisher: Callable[[RemoteResultProjectionV1], object],
    durable_acknowledged: Callable[[str], bool],
) -> dict[str, object]:
    """Reconstruct and publish proven canonical results without exposing mutation callbacks."""
    recovered = 0
    published = 0
    acknowledged = 0
    unresolved: list[str] = []

    for binding in binding_store.pending():
        if durable_acknowledged(binding.message_id):
            if binding.status == "OUTBOXED" and binding.projection_id:
                pending = {
                    item.projection_id: item
                    for item in outbox.pending()
                    if isinstance(item, RemoteResultProjectionV1)
                }
                projection = pending.get(binding.projection_id)
                if projection is not None:
                    outbox.mark_published(projection.projection_id, projection.projection_sha256)
            binding_store.mark_projected(binding.message_id, binding.projection_id or None)
            acknowledged += 1
            continue

        if binding.status == "OUTBOXED":
            continue

        evidence = evidence_resolver(binding)
        if evidence is None:
            unresolved.append(binding.message_id)
            continue
        projection = projection_from_evidence(binding, evidence)
        if projection is None:
            unresolved.append(binding.message_id)
            continue

        outbox.enqueue_projection(projection)
        canonical_refs = []
        if projection.canonical_state_ref:
            canonical_refs.append(projection.canonical_state_ref)
        canonical_refs.extend(projection.effect_evidence_refs)
        if projection.checkpoint_ref:
            canonical_refs.append(projection.checkpoint_ref)
        receipt_store.record_terminal_projection(
            message_id=binding.message_id,
            projection_digest=projection.projection_sha256,
            canonical_receipt_refs=tuple(canonical_refs),
        )
        binding_store.mark_outboxed(binding.message_id, projection.projection_id)
        recovered += 1

    # Publishing is deliberately after all durable enqueue/receipt transitions. If the
    # publisher raises, the canonical outbox item and OUTBOXED binding survive for the
    # next run. Noncanonical control projections share the durable outbox but are owned
    # by the runtime service's separate recovery path and must never enter this binding-
    # guarded loop.
    for projection in tuple(outbox.pending()):
        if not isinstance(projection, RemoteResultProjectionV1):
            continue
        publisher(projection)
        outbox.mark_published(projection.projection_id, projection.projection_sha256)
        for binding in binding_store.pending():
            if binding.projection_id == projection.projection_id:
                binding_store.mark_projected(binding.message_id, projection.projection_id)
        published += 1

    return {
        "recovered": recovered,
        "published": published,
        "acknowledged": acknowledged,
        "unresolved": tuple(unresolved),
    }


def resolve_registered_full_plan_completion(
    binding: RemoteExecutionBindingV1,
    *,
    harness_state_root: str | Path,
) -> CanonicalCompletionEvidence | None:
    """Return evidence only for the exact OCP-bound Gate that is already complete."""
    root = Path(harness_state_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        return None
    job_path = (
        root
        / "_workspace"
        / "production-full-plan-jobs"
        / binding.project_id
        / f"{binding.run_id}.job.json"
    )
    if job_path.is_symlink() or not job_path.is_file():
        return None
    try:
        job = load_registered_job(job_path)
        if (
            str(job.get("project_id") or "") != binding.project_id
            or str(job.get("run_id") or "") != binding.run_id
            or job_state_root(job) != root.resolve()
            or canonical_job_path(job).resolve() != job_path.resolve()
        ):
            return None
        gate_ids = [
            str(item.get("gate_id") or "")
            for item in job.get("gates", [])
            if isinstance(item, dict)
        ]
        if binding.gate_id not in gate_ids:
            return None
        supervisor = DurableFullPlanSupervisor(
            root,
            project_id=binding.project_id,
            run_id=binding.run_id,
            gates=gate_ids,
            authority_core_sha256=str(job.get("authority_core_sha256") or ""),
            **dict(job.get("policy") or {}),
        )
        state, _ = supervisor.load()
    except (OSError, ValueError, TypeError):
        return None

    if binding.gate_id not in state.get("completed_gates", []):
        return None
    queue_matches = [
        item
        for item in state.get("queue", [])
        if isinstance(item, dict)
        and item.get("gate_id") == binding.gate_id
        and item.get("gate_run_id") == binding.task_execution_id
        and item.get("status") == "COMPLETED"
    ]
    if len(queue_matches) != 1:
        return None

    owner = state.get("continuation_owner")
    if not isinstance(owner, dict):
        return None
    if (
        owner.get("source") != "OCPV2"
        or owner.get("gate_id") != binding.gate_id
        or int(owner.get("epoch", 0)) != binding.expected_owner_epoch
        or owner.get("message_id") != binding.message_id
        or owner.get("directive_digest") != binding.directive_digest
        or owner.get("task_execution_id") != binding.task_execution_id
    ):
        return None

    state_sha = str(state.get("state_sha256") or "")
    if len(state_sha) != 64 or any(ch not in "0123456789abcdef" for ch in state_sha):
        return None
    completed_at = str(
        state.get("last_semantic_progress_at")
        or state.get("last_progress_at")
        or owner.get("claimed_at")
        or ""
    )
    if not completed_at:
        return None

    return CanonicalCompletionEvidence(
        message_id=binding.message_id,
        directive_digest=binding.directive_digest,
        project_id=binding.project_id,
        run_id=binding.run_id,
        gate_id=binding.gate_id,
        task_id=binding.task_id,
        canonical_state_ref=f"full-plan-state:{binding.project_id}/{binding.run_id}",
        canonical_state_sha256=state_sha,
        effect_evidence_refs=(f"full-plan-gate:{binding.task_execution_id}:COMPLETED",),
        checkpoint_ref="",
        checkpoint_sha256="",
        migration_transaction_sha256="",
        result_summary=f"canonical Gate {binding.gate_id} completed under exact OCP binding",
        completed_at=completed_at,
    )
