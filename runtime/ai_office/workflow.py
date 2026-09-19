from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contracts import canonical_digest
from .state_store import AIOfficeStateStore

OFFICE_REGISTRY_SCHEMA_V1 = "ai-office.office-registry.v1"
OFFICE_RUN_SCHEMA_V1 = "ai-office.office-run.v1"
WORKFLOW_ITEM_SCHEMA_V1 = "ai-office.workflow-item.v1"

TRANSITIONS: Mapping[str, Mapping[str, str]] = {
    "NEW": {"REQUIREMENT_ACCEPTED": "INTAKE_READY"},
    "INTAKE_READY": {"CONTEXT_ASSEMBLED": "CONTEXT_READY"},
    "CONTEXT_READY": {"FULL_PLAN_HANDOFF_REFERENCED": "PLAN_COORDINATED"},
    "PLAN_COORDINATED": {"GOVERNANCE_READY": "EXECUTION_PENDING", "APPROVAL_REQUIRED": "WAITING_APPROVAL"},
    "EXECUTION_PENDING": {"STATE_CHANGE_UNAVAILABLE": "WAITING_STATE_CHANGE_AUTHORITY", "EXECUTION_ACCEPTED": "EXECUTION_IN_PROGRESS"},
    "WAITING_STATE_CHANGE_AUTHORITY": {"STATE_CHANGE_AUTHORITY_READY": "EXECUTION_PENDING"},
    "EXECUTION_IN_PROGRESS": {"RESULT_REFS_COMPLETE": "REVIEW_PENDING", "RECOVERY_REQUIRED": "RECOVERY_COORDINATION"},
    "RECOVERY_COORDINATION": {"RECOVERY_REVIEWED": "REVIEW_PENDING"},
    "REVIEW_PENDING": {"GATE_GO_REFERENCED": "COMPLETE"},
}


class WorkflowContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FullPlanCompletionRefV1:
    full_plan_run_id: str
    gate_id: str
    gate_ref: str
    gate_digest: str
    fanin_ref: str
    fanin_digest: str

    def __post_init__(self) -> None:
        for field in ("full_plan_run_id", "gate_id", "gate_ref", "fanin_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("gate_digest", "fanin_digest"):
            value = _text(getattr(self, field), field)
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise WorkflowContractError(f"invalid {field}")
            object.__setattr__(self, field, value)

    @property
    def completion_digest(self) -> str:
        return canonical_digest(asdict(self))
def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise WorkflowContractError(f"invalid {label}")
    return value.strip()


@dataclass(frozen=True, slots=True)
class OfficeRegistryV1:
    schema_version: str
    office_id: str
    department_ids: tuple[str, ...]
    registry_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_REGISTRY_SCHEMA_V1:
            raise WorkflowContractError("unsupported office registry schema")
        object.__setattr__(self, "office_id", _text(self.office_id, "office_id"))
        departments = tuple(_text(item, "department_id") for item in self.department_ids)
        if not departments or len(departments) != len(set(departments)):
            raise WorkflowContractError("invalid department registry")
        object.__setattr__(self, "department_ids", departments)
        object.__setattr__(self, "registry_ref", _text(self.registry_ref, "registry_ref"))

    @property
    def registry_digest(self) -> str:
        return canonical_digest(asdict(self))
@dataclass(frozen=True, slots=True)
class OfficeRunV1:
    schema_version: str
    office_id: str
    department_id: str
    run_id: str
    schedule_ref: str
    workflow_state: str
    revision: int
    external_full_plan_assignment_ref: str = ""
    external_fanin_ref: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != OFFICE_RUN_SCHEMA_V1:
            raise WorkflowContractError("unsupported office run schema")
        for field in ("office_id", "department_id", "run_id", "schedule_ref", "workflow_state"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise WorkflowContractError("invalid run revision")
        if self.external_full_plan_assignment_ref:
            object.__setattr__(self, "external_full_plan_assignment_ref", _text(self.external_full_plan_assignment_ref, "external_full_plan_assignment_ref"))
        if self.external_fanin_ref:
            object.__setattr__(self, "external_fanin_ref", _text(self.external_fanin_ref, "external_fanin_ref"))

    @property
    def run_digest(self) -> str:
        return canonical_digest(asdict(self))
@dataclass(frozen=True, slots=True)
class WorkflowItemV1:
    schema_version: str
    workflow_item_id: str
    requirement_digest: str
    context_digest: str
    workflow_state: str
    revision: int
    external_assignment_ref: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != WORKFLOW_ITEM_SCHEMA_V1:
            raise WorkflowContractError("unsupported workflow item schema")
        for field in ("workflow_item_id", "requirement_digest", "context_digest", "workflow_state"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise WorkflowContractError("invalid workflow revision")
        if self.external_assignment_ref:
            object.__setattr__(self, "external_assignment_ref", _text(self.external_assignment_ref, "external_assignment_ref"))

    @property
    def workflow_digest(self) -> str:
        return canonical_digest(asdict(self))


def next_state(current_state: str, event: str) -> str:
    target = TRANSITIONS.get(current_state, {}).get(event)
    if not target:
        raise WorkflowContractError("undeclared workflow transition")
    return target
class WorkflowCoordinator:
    def __init__(self, store: AIOfficeStateStore, *, office_id: str, department_id: str, schedule_ref: str):
        self.store = store
        self.office_id = _text(office_id, "office_id")
        self.department_id = _text(department_id, "department_id")
        self.schedule_ref = _text(schedule_ref, "schedule_ref")

    def transition(
        self, event: str, *, reason_ref: str, external_assignment_ref: str = "",
        full_plan_completion: FullPlanCompletionRefV1 | None = None,
    ) -> OfficeRunV1:
        current = self.store.load()
        target = next_state(current.workflow_state, event)
        refs = current.workflow_refs
        if external_assignment_ref:
            if event != "FULL_PLAN_HANDOFF_REFERENCED":
                raise WorkflowContractError("assignment ref is accepted only at Full Plan handoff")
            ref = _text(external_assignment_ref, "external_assignment_ref")
            refs = tuple(dict.fromkeys((*refs, f"full-plan-assignment:{ref}")))
        if event == "GATE_GO_REFERENCED":
            if not isinstance(full_plan_completion, FullPlanCompletionRefV1):
                raise WorkflowContractError("FULL_PLAN_COMPLETION_BINDING_MISMATCH")
            refs = tuple(dict.fromkeys((
                *refs,
                f"full-plan-gate:{full_plan_completion.gate_ref}",
                f"full-plan-fanin:{full_plan_completion.fanin_ref}",
                f"full-plan-completion:{full_plan_completion.completion_digest}",
            )))
        elif full_plan_completion is not None:
            raise WorkflowContractError("Full Plan completion ref is accepted only at Gate GO")
        updated = self.store.transition(to_state=target, reason_ref=reason_ref, workflow_refs=refs)
        assignment_refs = [ref.split(":", 1)[1] for ref in updated.workflow_refs if ref.startswith("full-plan-assignment:")]
        fanin_refs = [ref.split(":", 1)[1] for ref in updated.workflow_refs if ref.startswith("full-plan-fanin:")]
        return OfficeRunV1(
            OFFICE_RUN_SCHEMA_V1, self.office_id, self.department_id, updated.run_id,
            self.schedule_ref, updated.workflow_state, updated.revision,
            assignment_refs[-1] if assignment_refs else "", fanin_refs[-1] if fanin_refs else "",
        )
