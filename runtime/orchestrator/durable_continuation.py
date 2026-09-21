"""Pure DCC eligibility; mutation remains owned by Full Plan."""
from __future__ import annotations
from dataclasses import dataclass
import threading
from typing import Any, Mapping

AUTO = "AUTO_WITHIN_APPROVED_CONTRACT"


class ContinuationLockOrderError(RuntimeError):
    pass


_lock_order = threading.local()


def _lock_stack() -> list[str]:
    stack = getattr(_lock_order, "stack", None)
    if stack is None:
        stack = []
        _lock_order.stack = stack
    return stack


def enter_full_plan_run_lock() -> None:
    stack = _lock_stack()
    if stack:
        raise ContinuationLockOrderError("lock order violation: Full Plan run lock must be outermost")
    stack.append("run")


def exit_full_plan_run_lock() -> None:
    stack = _lock_stack()
    if stack != ["run"]:
        raise ContinuationLockOrderError("lock order violation while releasing Full Plan run lock")
    stack.pop()


def enter_continuation_transaction_lock() -> None:
    stack = _lock_stack()
    if stack != ["run"]:
        raise ContinuationLockOrderError("Full Plan run lock must be outer before continuation transaction lock")
    stack.append("transaction")


def exit_continuation_transaction_lock() -> None:
    stack = _lock_stack()
    if stack != ["run", "transaction"]:
        raise ContinuationLockOrderError("lock order violation while releasing continuation transaction lock")
    stack.pop()


def full_plan_run_lock_held() -> bool:
    return bool(_lock_stack()) and _lock_stack()[0] == "run"

_RECEIPT_REASONS = {"OPERATOR_TASK_RECEIPT_PENDING", "CONTINUATION_RECOVERY_PENDING"}

@dataclass(frozen=True, slots=True)
class ContinuationEligibility:
    eligible: bool
    reason: str


def evaluate_continuation_eligibility(state: Mapping[str, Any], context: Mapping[str, Any]) -> ContinuationEligibility:
    if str(context.get("continuation_policy") or "") != AUTO:
        return ContinuationEligibility(False, "MANUAL_OR_UNAPPROVED_CONTINUATION")
    if not bool(context.get("contract_valid")):
        return ContinuationEligibility(False, "CONTRACT_INVALID")
    if not bool(context.get("attestation_valid")):
        return ContinuationEligibility(False, "ATTESTATION_INVALID")
    if not bool(context.get("owner_epoch_current")):
        return ContinuationEligibility(False, "STALE_OWNER_EPOCH")
    if str(context.get("transaction_phase") or "") != "RECEIPT_SEALED":
        return ContinuationEligibility(False, "TRANSACTION_NOT_RECEIPT_SEALED")
    if str(state.get("state") or "") != "WAITING_RESOURCE":
        return ContinuationEligibility(False, "WAIT_STATE_NOT_DCC_OWNED")
    reason = str(state.get("last_error") or state.get("wait_reason") or "")
    if reason not in _RECEIPT_REASONS:
        return ContinuationEligibility(False, "WAIT_REASON_NOT_DCC_OWNED")
    return ContinuationEligibility(True, "AUTO_CONTINUATION_ELIGIBLE")
