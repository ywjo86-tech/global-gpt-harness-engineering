from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .contracts import OfficeStateSnapshotV1, canonical_digest
from .workflow import FullPlanCompletionRefV1

OFFICE_STATUS_SCHEMA_V1 = "ai-office.status-projection.v1"
OFFICE_KPI_SCHEMA_V1 = "ai-office.kpi-projection.v1"
OFFICE_REPORT_SCHEMA_V1 = "ai-office.report.v1"


class ReportingError(ValueError):
    pass


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ReportingError(f"invalid {label}")
    item = value.strip()
    if (not item and not allow_empty) or len(item) > 512:
        raise ReportingError(f"invalid {label}")
    return item


def _refs(values: Iterable[str], label: str) -> tuple[str, ...]:
    items = tuple(sorted({_text(value, label) for value in values}))
    return items
@dataclass(frozen=True, slots=True)
class OfficeStatusProjectionV1:
    schema_version: str
    project_id: str
    run_id: str
    workflow_state: str
    revision: int
    pending_approval_ref: str
    pending_manual_action_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_STATUS_SCHEMA_V1:
            raise ReportingError("unsupported status projection schema")
        for field in ("project_id", "run_id", "workflow_state"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ReportingError("invalid revision")
        for field in ("pending_approval_ref", "pending_manual_action_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field, allow_empty=True))

    @property
    def status_digest(self) -> str:
        return canonical_digest(asdict(self))
@dataclass(frozen=True, slots=True)
class OfficeKPIProjectionV1:
    schema_version: str
    observation_ref_count: int
    recovery_ref_count: int
    has_pending_approval: bool
    has_pending_manual_action: bool

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_KPI_SCHEMA_V1:
            raise ReportingError("unsupported KPI projection schema")
        for field in ("observation_ref_count", "recovery_ref_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReportingError(f"invalid {field}")

    @property
    def kpi_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class OfficeReportV1:
    schema_version: str
    status: OfficeStatusProjectionV1
    kpi: OfficeKPIProjectionV1
    external_assignment_ref: str
    external_fanin_ref: str
    full_plan_completion_digest: str
    observation_refs: tuple[str, ...]
    recovery_refs: tuple[str, ...]
    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_REPORT_SCHEMA_V1:
            raise ReportingError("unsupported office report schema")
        object.__setattr__(self, "external_assignment_ref", _text(self.external_assignment_ref, "external_assignment_ref", allow_empty=True))
        object.__setattr__(self, "external_fanin_ref", _text(self.external_fanin_ref, "external_fanin_ref", allow_empty=True))
        digest = _text(self.full_plan_completion_digest, "full_plan_completion_digest", allow_empty=True)
        if digest and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ReportingError("invalid full_plan_completion_digest")
        object.__setattr__(self, "full_plan_completion_digest", digest)
        if self.external_fanin_ref and not self.full_plan_completion_digest:
            raise ReportingError("FULL_PLAN_COMPLETION_BINDING_MISMATCH")
        object.__setattr__(self, "observation_refs", _refs(self.observation_refs, "observation_ref"))
        object.__setattr__(self, "recovery_refs", _refs(self.recovery_refs, "recovery_ref"))

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": asdict(self.status),
            "kpi": asdict(self.kpi),
            "external_assignment_ref": self.external_assignment_ref,
            "external_fanin_ref": self.external_fanin_ref,
            "full_plan_completion_digest": self.full_plan_completion_digest,
            "observation_refs": list(self.observation_refs),
            "recovery_refs": list(self.recovery_refs),
        }

    @property
    def report_digest(self) -> str:
        return canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "report_digest": self.report_digest}
def build_office_report(
    snapshot: OfficeStateSnapshotV1, *, external_assignment_ref: str = "",
    full_plan_completion: FullPlanCompletionRefV1 | None = None,
    observation_refs: Iterable[str] = (), recovery_refs: Iterable[str] = (),
) -> OfficeReportV1:
    observations = _refs(observation_refs, "observation_ref")
    recoveries = _refs(recovery_refs, "recovery_ref")
    if full_plan_completion is not None:
        expected_ref = f"full-plan-completion:{full_plan_completion.completion_digest}"
        if expected_ref not in snapshot.workflow_refs:
            raise ReportingError("FULL_PLAN_COMPLETION_BINDING_MISMATCH")
    if snapshot.workflow_state == "COMPLETE" and full_plan_completion is None:
        raise ReportingError("FULL_PLAN_COMPLETION_BINDING_MISMATCH")
    status = OfficeStatusProjectionV1(
        OFFICE_STATUS_SCHEMA_V1,
        snapshot.project_id,
        snapshot.run_id,
        snapshot.workflow_state,
        snapshot.revision,
        snapshot.pending_approval_ref,
        snapshot.pending_manual_action_ref,
    )
    kpi = OfficeKPIProjectionV1(
        OFFICE_KPI_SCHEMA_V1,
        len(observations),
        len(recoveries),
        bool(snapshot.pending_approval_ref),
        bool(snapshot.pending_manual_action_ref),
    )
    external_fanin_ref = "" if full_plan_completion is None else full_plan_completion.fanin_ref
    completion_digest = "" if full_plan_completion is None else full_plan_completion.completion_digest
    return OfficeReportV1(
        OFFICE_REPORT_SCHEMA_V1,
        status,
        kpi,
        external_assignment_ref,
        external_fanin_ref,
        completion_digest,
        observations,
        recoveries,
    )
