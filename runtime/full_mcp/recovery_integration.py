from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .qualification import GATE_ORDER, compute_invalidation
from .recovery import RecoveryDecision, RecoveryPolicyError, classify_recovery


class RecoveryIntegrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryIntegrationPlan:
    classification: str
    reason_code: str
    auto_retry_allowed: bool
    requires_restore_or_remediation: bool
    stale_validation_result_refs: tuple[str, ...]
    stale_evidence_refs: tuple[str, ...]
    invalidated_gate_ids: tuple[str, ...]
    earliest_reentry_gate: str
    originally_failed_gate: str
    gate_reentry_sequence: tuple[str, ...]
    required_sequence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_integrated_recovery(
    *,
    error_code: str,
    effect_state: str,
    state_changing: bool,
    changed_paths: Sequence[str],
    validation_results_by_path: Mapping[str, Mapping[str, Any]],
    evidence_by_path: Mapping[str, Mapping[str, Any]],
    gate_records: Mapping[str, Mapping[str, Any]],
    originally_failed_gate: str,
) -> RecoveryIntegrationPlan:
    if originally_failed_gate not in GATE_ORDER:
        raise RecoveryIntegrationError("originally failed gate is invalid")
    try:
        primitive: RecoveryDecision = classify_recovery(
            error_code=error_code, effect_state=effect_state, state_changing=state_changing
        )
    except RecoveryPolicyError as exc:
        raise RecoveryIntegrationError("recovery primitive rejected integration input") from exc
    impact = compute_invalidation(
        changed_paths=changed_paths,
        validation_results_by_path=validation_results_by_path,
        evidence_by_path=evidence_by_path,
        gate_records=gate_records,
    )
    failed_index = GATE_ORDER.index(originally_failed_gate)
    invalidated = tuple(impact["invalidated_gate_ids"])
    relevant = tuple(g for g in invalidated if GATE_ORDER.index(g) <= failed_index)
    earliest = relevant[0] if relevant else originally_failed_gate
    start_index = GATE_ORDER.index(earliest)
    reentry = GATE_ORDER[start_index:failed_index + 1]
    if not reentry or reentry[-1] != originally_failed_gate:
        raise RecoveryIntegrationError("same-gate re-entry sequence is invalid")
    if state_changing and primitive.auto_retry_allowed:
        raise RecoveryIntegrationError("state-changing recovery cannot auto-retry")
    required = (
        "DIAGNOSE",
        "REMEDIATE_OR_RESTORE" if primitive.requires_restore_or_remediation else "REMEDIATE_IF_REQUIRED",
        "FOCUSED_VALIDATION",
        "REGRESSION",
        "INDEPENDENT_REVIEW",
        *(f"REEVALUATE:{gate}" for gate in reentry),
    )
    return RecoveryIntegrationPlan(
        classification=primitive.classification,
        reason_code=primitive.reason_code,
        auto_retry_allowed=primitive.auto_retry_allowed,
        requires_restore_or_remediation=primitive.requires_restore_or_remediation,
        stale_validation_result_refs=tuple(impact["stale_validation_result_refs"]),
        stale_evidence_refs=tuple(impact["stale_evidence_refs"]),
        invalidated_gate_ids=invalidated,
        earliest_reentry_gate=earliest,
        originally_failed_gate=originally_failed_gate,
        gate_reentry_sequence=tuple(reentry),
        required_sequence=tuple(required),
    )
