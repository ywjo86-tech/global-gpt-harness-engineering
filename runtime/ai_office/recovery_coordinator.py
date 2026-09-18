from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from .contracts import canonical_digest
from .state_store import AIOfficeStateStore

RECOVERY_COORDINATION_SCHEMA_V1 = "ai-office.recovery-coordination.v1"
RECOVERY_STAGES = (
    "FAILURE_RECORDED",
    "DIAGNOSED",
    "REMEDIATED",
    "FOCUSED_VALIDATED",
    "REGRESSION_VALIDATED",
    "INDEPENDENT_REVIEWED",
    "SAME_GATE_REEVALUATION_READY",
)


class RecoveryCoordinationError(ValueError):
    pass


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RecoveryCoordinationError(f"invalid {label}")
    item = value.strip()
    if (not item and not allow_empty) or len(item) > 512:
        raise RecoveryCoordinationError(f"invalid {label}")
    return item
@dataclass(frozen=True, slots=True)
class RecoveryCoordinationV1:
    schema_version: str
    recovery_id: str
    failure_source_ref: str
    workflow_ref: str
    approval_ref: str
    manual_action_ref: str
    same_gate_ref: str
    stage: str
    stage_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RECOVERY_COORDINATION_SCHEMA_V1:
            raise RecoveryCoordinationError("unsupported recovery schema")
        for field in ("recovery_id", "failure_source_ref", "workflow_ref", "same_gate_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("approval_ref", "manual_action_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field, allow_empty=True))
        if self.stage not in RECOVERY_STAGES:
            raise RecoveryCoordinationError("invalid recovery stage")
        refs = tuple(_text(ref, "stage_evidence_ref") for ref in self.stage_evidence_refs)
        if len(refs) != len(set(refs)):
            raise RecoveryCoordinationError("duplicate recovery evidence ref")
        object.__setattr__(self, "stage_evidence_refs", refs)

    @property
    def recovery_digest(self) -> str:
        return canonical_digest(asdict(self))
def begin_recovery(
    *, recovery_id: str, failure_source_ref: str, workflow_ref: str,
    same_gate_ref: str, approval_ref: str = "", manual_action_ref: str = "",
) -> RecoveryCoordinationV1:
    return RecoveryCoordinationV1(
        RECOVERY_COORDINATION_SCHEMA_V1,
        recovery_id,
        failure_source_ref,
        workflow_ref,
        approval_ref,
        manual_action_ref,
        same_gate_ref,
        "FAILURE_RECORDED",
        (failure_source_ref,),
    )


def advance_recovery(
    recovery: RecoveryCoordinationV1, *, next_stage: str, evidence_ref: str,
) -> RecoveryCoordinationV1:
    current_index = RECOVERY_STAGES.index(recovery.stage)
    if current_index + 1 >= len(RECOVERY_STAGES) or RECOVERY_STAGES[current_index + 1] != next_stage:
        raise RecoveryCoordinationError("recovery stages cannot be skipped or replayed")
    ref = _text(evidence_ref, "evidence_ref")
    if ref in recovery.stage_evidence_refs:
        raise RecoveryCoordinationError("recovery evidence replay detected")
    return replace(
        recovery,
        stage=next_stage,
        stage_evidence_refs=(*recovery.stage_evidence_refs, ref),
    )
def rehydrate_pending_state(store: AIOfficeStateStore) -> dict[str, Any]:
    snapshot = store.load()
    manual_refs = [ref for ref in snapshot.workflow_refs if ref.startswith("manual-action:")]
    if snapshot.pending_manual_action_ref:
        manual_refs.append(snapshot.pending_manual_action_ref)
    normalized = tuple(dict.fromkeys(manual_refs))
    if len(normalized) != len(manual_refs):
        raise RecoveryCoordinationError("duplicated pending manual action reference")
    return {
        "project_id": snapshot.project_id,
        "run_id": snapshot.run_id,
        "revision": snapshot.revision,
        "workflow_state": snapshot.workflow_state,
        "pending_approval_ref": snapshot.pending_approval_ref,
        "pending_manual_action_ref": snapshot.pending_manual_action_ref,
        "manual_action_refs": normalized,
        "snapshot_digest": snapshot.snapshot_digest,
    }


def recovery_projection(recovery: RecoveryCoordinationV1) -> dict[str, Any]:
    body = asdict(recovery)
    forbidden = {"provider", "provider_ref", "model", "model_ref", "action_replay", "gate_decision"}
    if forbidden.intersection(body):
        raise RecoveryCoordinationError("recovery projection contains forbidden authority material")
    return {**body, "recovery_digest": recovery.recovery_digest}
