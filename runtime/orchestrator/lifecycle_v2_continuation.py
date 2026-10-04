"""CAS-bound Lifecycle V2 continuation bridge.

The bridge creates no approval or mutation authority. It validates that a V2
receipt is durably bound to the acknowledged dispatch, asks existing DCC
eligibility for permission to continue, and then reopens the exact Full Plan
wait generation through the supervisor's existing CAS resume path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .harness_state_root import job_state_root
from .operator_dispatch_v2 import (
    DispatchReceiptBindingStore,
    OperatorDispatchStore,
    evaluate_v2_auto_continuation,
)
from .operator_plan_execution import OperatorPlanReceiptStore
from .production_full_plan_runner import DurableFullPlanSupervisor


class LifecycleV2ContinuationError(ValueError):
    pass


def _validate_supervisor_binding(
    job: Mapping[str, Any],
    gate_id: str,
    supervisor: DurableFullPlanSupervisor,
) -> None:
    if str(job.get("project_id") or "") != supervisor.project_id:
        raise LifecycleV2ContinuationError("V2 continuation project binding mismatch")
    if str(job.get("run_id") or "") != supervisor.run_id:
        raise LifecycleV2ContinuationError("V2 continuation run binding mismatch")
    if Path(job_state_root(job)).resolve() != supervisor.root:
        raise LifecycleV2ContinuationError("V2 continuation state-root binding mismatch")
    known = tuple(str(item.get("gate_id") or "") for item in job.get("gates", []) if isinstance(item, Mapping))
    if tuple(supervisor.gates) != known or gate_id not in known:
        raise LifecycleV2ContinuationError("V2 continuation Gate binding mismatch")


def resume_v2_after_bound_receipt(
    job: Mapping[str, Any],
    gate_id: str,
    supervisor: DurableFullPlanSupervisor,
    *,
    continuation_policy: str,
    contract_valid: bool,
    attestation_valid: bool,
    owner_epoch_current: bool,
    dispatch_store: OperatorDispatchStore | None = None,
    receipt_store: OperatorPlanReceiptStore | None = None,
    binding_store: DispatchReceiptBindingStore | None = None,
) -> dict[str, Any]:
    """Resume one exact V2 receipt wait only after existing DCC checks pass."""
    _validate_supervisor_binding(job, gate_id, supervisor)
    state, _ = supervisor.load()
    if state.get("state") != "WAITING_RESOURCE" or state.get("current_gate") != gate_id:
        raise LifecycleV2ContinuationError("V2 continuation is not waiting on the requested Gate")

    eligibility = evaluate_v2_auto_continuation(
        job,
        gate_id,
        state,
        continuation_policy=continuation_policy,
        contract_valid=contract_valid,
        attestation_valid=attestation_valid,
        owner_epoch_current=owner_epoch_current,
        dispatch_store=dispatch_store,
        receipt_store=receipt_store,
        binding_store=binding_store,
    )
    if not eligibility.eligible:
        raise LifecycleV2ContinuationError(f"V2 continuation rejected: {eligibility.reason}")

    return supervisor.resume_wait_cas(
        "WAITING_RESOURCE",
        expected_state_sha256=str(state.get("state_sha256") or ""),
        expected_epoch=int(state.get("epoch", 0)),
    )
