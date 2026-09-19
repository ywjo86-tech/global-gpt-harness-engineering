"""Pure policy evaluators for user decisions and attention delivery.

This module has no orchestration authority.  It classifies whether existing
approval lineage covers a requested continuation and whether an already
persisted incident is eligible for user-facing delivery.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


DEFERRED_INCIDENT = "DEFERRED_INCIDENT"
IMMEDIATE_DECISION = "IMMEDIATE_DECISION"
STALL_CONFIRMED = "STALL_CONFIRMED"
DELIVERY_CLASSES = frozenset({DEFERRED_INCIDENT, IMMEDIATE_DECISION, STALL_CONFIRMED})
SAFE_EFFECT_RECONCILIATION = frozenset({"NO_EFFECT", "RECONCILED"})
SUPPRESSED_TERMINAL_STATES = frozenset({"COMPLETED", "CANCELLED"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ApprovalCoverageEvidence:
    approval_ref: str
    approved_semantic_digest: str
    reviewed_semantic_digest: str
    allowed_risk_classes: tuple[str, ...]
    allowed_operations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.approval_ref, str) or not self.approval_ref.strip():
            raise ValueError("approval_ref is required")
        if not _SHA256.fullmatch(self.approved_semantic_digest):
            raise ValueError("approved_semantic_digest must be sha256")
        if not _SHA256.fullmatch(self.reviewed_semantic_digest):
            raise ValueError("reviewed_semantic_digest must be sha256")
        for field_name in ("allowed_risk_classes", "allowed_operations"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{field_name} is invalid")
            object.__setattr__(self, field_name, tuple(sorted(set(v.strip() for v in values))))

    @property
    def exact_compatible(self) -> bool:
        return self.approved_semantic_digest == self.reviewed_semantic_digest

    def covers(self, *, risk_class: str, operation: str) -> bool:
        return (
            self.exact_compatible
            and risk_class in self.allowed_risk_classes
            and operation in self.allowed_operations
        )


@dataclass(frozen=True, slots=True)
class UserDecisionAssessment:
    required: bool
    decision_type: str
    reason: str


@dataclass(frozen=True, slots=True)
class AttentionDeliveryAssessment:
    eligible: bool
    delivery_class: str
    reason: str
    elapsed_seconds: float = 0.0


def evaluate_user_decision(*, approval_coverage: ApprovalCoverageEvidence | None,
                           material_contract_change: bool, requested_risk_class: str,
                           requested_operation: str, dangerous_reexecution: bool,
                           effect_reconciliation: str = "UNKNOWN") -> UserDecisionAssessment:
    if approval_coverage is None:
        return UserDecisionAssessment(True, "INITIAL_EXECUTION_APPROVAL", "approval coverage is missing")
    if material_contract_change:
        return UserDecisionAssessment(True, "PLAN_REVISION_REQUIRED", "material contract change detected")
    if not approval_coverage.exact_compatible:
        return UserDecisionAssessment(True, "PLAN_REVISION_REQUIRED", "approval semantic digest is stale")
    if not approval_coverage.covers(risk_class=requested_risk_class, operation=requested_operation):
        return UserDecisionAssessment(True, "RISK_ESCALATION", "requested work is outside approval coverage")
    if dangerous_reexecution and effect_reconciliation not in SAFE_EFFECT_RECONCILIATION:
        return UserDecisionAssessment(
            True, "AMBIGUOUS_DANGEROUS_EFFECT",
            "dangerous reexecution lacks safe effect reconciliation",
        )
    return UserDecisionAssessment(False, "NONE", "existing approval coverage remains valid")


def infer_delivery_class(event: Mapping[str, Any]) -> str:
    explicit = event.get("delivery_class")
    if isinstance(explicit, str) and explicit in DELIVERY_CLASSES:
        return explicit
    kind = str(event.get("kind") or "")
    if kind in {"WAITING_APPROVAL", "USER_DECISION_REQUIRED"}:
        return IMMEDIATE_DECISION
    if kind in {"STALLED_SUSPECTED", "SUPERVISOR_OR_WORKER_LIVENESS_LOST"}:
        return STALL_CONFIRMED
    return DEFERRED_INCIDENT


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_attention_delivery(event: Mapping[str, Any], state: Mapping[str, Any], *,
                                now: datetime, threshold_seconds: int = 300) -> AttentionDeliveryAssessment:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if threshold_seconds <= 0:
        raise ValueError("threshold_seconds must be positive")
    now_utc = now.astimezone(timezone.utc)
    delivery_class = infer_delivery_class(event)
    state_name = str(state.get("state") or "UNKNOWN")
    if state_name in SUPPRESSED_TERMINAL_STATES:
        return AttentionDeliveryAssessment(False, delivery_class, "terminal state suppresses stale incident")
    if delivery_class == IMMEDIATE_DECISION:
        return AttentionDeliveryAssessment(True, delivery_class, "user decision is required immediately")
    if delivery_class == STALL_CONFIRMED:
        return AttentionDeliveryAssessment(True, delivery_class, "stall/liveness anomaly already met alert threshold")

    event_reason = str(event.get("reason") or "")
    current_reason = str(state.get("last_error") or state.get("terminal_reason") or "")
    if not current_reason or (event_reason and current_reason != event_reason):
        return AttentionDeliveryAssessment(False, delivery_class, "incident is no longer current")

    created = _timestamp(event.get("created_at"))
    semantic = _timestamp(state.get("last_semantic_progress_at") or state.get("last_progress_at"))
    if created is None:
        return AttentionDeliveryAssessment(False, delivery_class, "incident timestamp is invalid")
    anchor = max(created, semantic) if semantic is not None else created
    elapsed = max(0.0, (now_utc - anchor).total_seconds())
    eligible = elapsed >= float(threshold_seconds)
    reason = "notification delay satisfied" if eligible else "autonomous recovery window remains open"
    return AttentionDeliveryAssessment(eligible, delivery_class, reason, elapsed)
