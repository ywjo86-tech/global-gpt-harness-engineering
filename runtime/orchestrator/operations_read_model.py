"""Closed, non-authoritative operations read model for AI Office surfaces."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

from runtime.ai_office.reporting import OfficeReportV1
from .operations_diagnostic_projection import DiagnosticHealthProjectionV1
from .operator_console_projection import OperatorConsoleProjectionV1


OPERATIONS_READ_MODEL_SCHEMA_V1 = "orchestration.operations-read-model.v1"


class OperationsReadModelError(ValueError):
    pass


_STATE_ALIASES = {
    "NEW": "QUEUED",
    "INTAKE_READY": "PLANNING",
    "INTAKE_BLOCKED": "STALLED",
    "CONTEXT_READY": "PLANNING",
    "SOURCE_BINDING_BLOCKED": "STALLED",
    "PLAN_COORDINATED": "PLANNING",
    "PLAN_HANDOFF_BLOCKED": "STALLED",
    "EXECUTION_PENDING": "QUEUED",
    "WAITING_STATE_CHANGE_AUTHORITY": "WAITING_DEPENDENCY",
    "EXECUTION_IN_PROGRESS": "RUNNING",
    "REVIEW_PENDING": "RUNNING",
    "RECOVERY_COORDINATION": "RECOVERING",
    "COMPLETE": "COMPLETED",
    "BLOCKED": "STALLED",
}

_STATE_MAP = {
    "QUEUED": ("QUEUED", "대기"),
    "PLANNING": ("PLANNING", "계획 작성 중"),
    "RUNNING": ("RUNNING", "작업 중"),
    "WAITING_DEPENDENCY": ("WAITING_DEPENDENCY", "다른 업무 결과 대기"),
    "WAITING_APPROVAL": ("WAITING_APPROVAL", "사용자 승인 대기"),
    "PAUSED": ("PAUSED", "일시 중지"),
    "STALLED": ("STALLED", "진행 정지"),
    "RECOVERING": ("RECOVERING", "자동 복구 중"),
    "FAILED": ("FAILED", "문제 발생"),
    "COMPLETED": ("COMPLETED", "완료"),
}


def normalize_operations_state(raw_state: str) -> tuple[str, str]:
    state = str(raw_state or "").strip().upper()
    state = _STATE_ALIASES.get(state, state)
    return _STATE_MAP.get(state, ("UNKNOWN", "상태 확인 필요"))


def normalize_progress(value: int | None, source: str) -> tuple[int | None, str]:
    if value is None:
        return None, ""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise OperationsReadModelError("progress requires a bounded integer value")
    source_text = str(source or "").strip()
    if not source_text:
        raise OperationsReadModelError("progress requires an evidence source")
    return value, source_text


def resolve_freshness(
    sources: tuple["SourceIdentityV1", ...],
    now: datetime,
    stale_after_seconds: int = 300,
) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or stale_after_seconds <= 0:
        raise OperationsReadModelError("freshness requires timezone-aware now and positive threshold")
    if not sources:
        return "UNKNOWN"
    parsed = []
    for source in sources:
        if not isinstance(source, SourceIdentityV1):
            return "UNKNOWN"
        try:
            timestamp = datetime.fromisoformat(source.source_timestamp)
        except (TypeError, ValueError):
            return "UNKNOWN"
        if timestamp.tzinfo is None or timestamp > now:
            return "UNKNOWN"
        parsed.append(timestamp)
    if any((now - timestamp).total_seconds() > stale_after_seconds for timestamp in parsed):
        return "STALE"
    return "FRESH"


@dataclass(frozen=True, slots=True)
class SourceIdentityV1:
    source_component: str
    source_version: str
    source_head: str
    source_timestamp: str


@dataclass(frozen=True, slots=True)
class OperationsReadModelV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    gate_id: str
    raw_state: str
    normalized_state: str
    human_state: str
    progress: int | None
    progress_source: str
    current_work: str
    outcome: str
    impact: str
    next_step: str
    approval_required: bool
    approval_refs: tuple[str, ...]
    checkpoint_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    sources: tuple[SourceIdentityV1, ...]
    freshness: str
    diagnostic_health: DiagnosticHealthProjectionV1 | None = None

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["approval_refs"] = list(self.approval_refs)
        value["checkpoint_refs"] = list(self.checkpoint_refs)
        value["evidence_refs"] = list(self.evidence_refs)
        value["sources"] = [asdict(item) for item in self.sources]
        return value


def _validate_inputs(
    console: OperatorConsoleProjectionV1,
    office_report: OfficeReportV1,
    source_identities: tuple[SourceIdentityV1, ...],
) -> None:
    if not isinstance(console, OperatorConsoleProjectionV1):
        raise OperationsReadModelError("OperatorConsoleProjectionV1 is required")
    if not isinstance(office_report, OfficeReportV1):
        raise OperationsReadModelError("OfficeReportV1 is required")
    if (console.project_id, console.run_id) != (
        office_report.status.project_id,
        office_report.status.run_id,
    ):
        raise OperationsReadModelError("console/office report identity mismatch")
    if any(not isinstance(item, SourceIdentityV1) for item in source_identities):
        raise OperationsReadModelError("SourceIdentityV1 entries are required")


def build_operations_read_model(
    console: OperatorConsoleProjectionV1,
    office_report: OfficeReportV1,
    *,
    source_identities: tuple[SourceIdentityV1, ...],
    now: datetime,
    diagnostic_health: DiagnosticHealthProjectionV1 | None = None,
) -> OperationsReadModelV1:
    """Build a closed read model from bounded projections only.

    Task 2 replaces the provisional state/freshness values with deterministic
    normalization. No percentage is inferred here.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise OperationsReadModelError("timezone-aware now is required")
    _validate_inputs(console, office_report, source_identities)
    raw_state = office_report.status.workflow_state or console.stage
    normalized_state, human_state = normalize_operations_state(raw_state)
    approval_ref = office_report.status.pending_approval_ref
    evidence_refs = tuple(
        dict.fromkeys(
            (*console.evidence_refs, *office_report.observation_refs, *office_report.recovery_refs)
        )
    )
    return OperationsReadModelV1(
        schema_version=OPERATIONS_READ_MODEL_SCHEMA_V1,
        project_id=console.project_id,
        run_id=console.run_id,
        task_id=console.task_id,
        gate_id=console.gate_id,
        raw_state=raw_state,
        normalized_state=normalized_state,
        human_state=human_state,
        progress=None,
        progress_source="",
        current_work="",
        outcome="",
        impact="",
        next_step="",
        approval_required=bool(approval_ref or office_report.kpi.has_pending_approval),
        approval_refs=(approval_ref,) if approval_ref else (),
        checkpoint_refs=console.checkpoint_refs,
        evidence_refs=evidence_refs,
        sources=tuple(source_identities),
        freshness=resolve_freshness(tuple(source_identities), now),
        diagnostic_health=diagnostic_health,
    )


def build_operations_read_model_from_console_snapshot(
    console: OperatorConsoleProjectionV1,
    snapshot: Mapping[str, Any],
    *,
    source_identities: tuple[SourceIdentityV1, ...] = (),
    diagnostic_health: DiagnosticHealthProjectionV1 | None = None,
) -> OperationsReadModelV1:
    """Bounded adapter for the legacy Jarvis bridge snapshot shape."""
    if not isinstance(console, OperatorConsoleProjectionV1) or not isinstance(snapshot, Mapping):
        raise OperationsReadModelError("console projection and snapshot mapping are required")
    sources = source_identities or (
        SourceIdentityV1(
            "PROJECT_ORCHESTRATOR",
            "UNKNOWN",
            "UNKNOWN",
            str(snapshot.get("last_updated") or "UNKNOWN"),
        ),
    )
    raw_state = str(console.stage or "")
    normalized_state, human_state = normalize_operations_state(raw_state)
    next_step = str(snapshot.get("next_step") or "")
    return OperationsReadModelV1(
        schema_version=OPERATIONS_READ_MODEL_SCHEMA_V1,
        project_id=console.project_id,
        run_id=console.run_id,
        task_id=console.task_id,
        gate_id=console.gate_id,
        raw_state=raw_state,
        normalized_state=normalized_state,
        human_state=human_state,
        progress=None,
        progress_source="",
        current_work=next_step,
        outcome="",
        impact="",
        next_step=next_step,
        approval_required=bool(snapshot.get("approval_required")),
        approval_refs=(),
        checkpoint_refs=console.checkpoint_refs,
        evidence_refs=console.evidence_refs,
        sources=tuple(sources),
        freshness="UNKNOWN",
        diagnostic_health=diagnostic_health,
    )
