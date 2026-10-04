"""Request-local AI Office coordination for already-approved Full Plan work."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runtime.orchestrator.approved_work_binding import ApprovedWorkBindingV1

from .contracts import canonical_digest
from .requirement_intake import RequirementEnvelopeV1, RequirementIntakeError, intake_requirement
from .state_store import AIOfficeStateStore, AIOfficeStateStoreError
from .workflow import WorkflowContractError, WorkflowCoordinator

AI_ACTIVATION_CONTEXT_SCHEMA_V1 = "ai-office.activation-context.v1"


class AIActivationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AIActivationContextV1:
    schema_version: str
    activation_request_id: str
    project_id: str
    office_run_id: str
    requirement_id: str
    requirement_envelope_digest: str
    full_plan_plan_digest: str
    full_plan_spec_digest: str
    requirement_artifact_digest: str
    approval_ref: str
    expected_head: str
    workflow_state: str
    workflow_revision: int
    workflow_state_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != AI_ACTIVATION_CONTEXT_SCHEMA_V1:
            raise AIActivationError("unsupported AI activation context schema")
        for value, label in (
            (self.activation_request_id, "activation request ID"),
            (self.project_id, "project ID"), (self.office_run_id, "office run ID"),
            (self.requirement_id, "requirement ID"), (self.approval_ref, "approval ref"),
            (self.workflow_state, "workflow state"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise AIActivationError(f"invalid {label}")
        for value, label in (
            (self.requirement_envelope_digest, "requirement envelope digest"),
            (self.full_plan_plan_digest, "Full Plan plan digest"),
            (self.full_plan_spec_digest, "Full Plan spec digest"),
            (self.requirement_artifact_digest, "requirement artifact digest"),
            (self.workflow_state_digest, "workflow state digest"),
        ):
            if len(str(value)) != 64 or any(ch not in "0123456789abcdef" for ch in str(value)):
                raise AIActivationError(f"invalid {label}")
        if not isinstance(self.workflow_revision, int) or isinstance(self.workflow_revision, bool) or self.workflow_revision < 0:
            raise AIActivationError("invalid workflow revision")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def context_digest(self) -> str:
        return canonical_digest(self.to_dict())


def _requirement_for_binding(binding: ApprovedWorkBindingV1) -> RequirementEnvelopeV1:
    requirement_id = f"approved-work:{binding.activation_request_id}"
    source_ref = f"approved-plan:{binding.approved_plan_path}"
    planning_ref = "full-plan:approved"
    constraints = (
        f"approved-spec-sha256:{binding.approved_spec_sha256}",
        f"requirement-artifact-sha256:{binding.requirement_artifact_sha256}",
        f"approval-ref-digest:{canonical_digest({'approval_ref': binding.approval_ref})}",
    )
    approved = {
        "source_ref": source_ref,
        "source_digest": binding.approved_plan_sha256,
        "planning_authority_ref": planning_ref,
        "constraints_refs": constraints,
    }
    candidate = {
        "requirement_id": requirement_id,
        **approved,
        "correlation_id": binding.activation_request_id,
    }
    try:
        return intake_requirement(candidate, approved_register={requirement_id: approved})
    except RequirementIntakeError as exc:
        raise AIActivationError("AI_ACTIVATION_REQUIREMENT_BLOCKED") from exc


def _expected_refs(binding: ApprovedWorkBindingV1) -> tuple[str, str]:
    return f"plan:{binding.approved_plan_sha256}", f"head:{binding.expected_head}"


def coordinate_approved_activation(
    binding: ApprovedWorkBindingV1, *, office_store: AIOfficeStateStore,
) -> AIActivationContextV1:
    if not isinstance(binding, ApprovedWorkBindingV1):
        raise AIActivationError("APPROVED_WORK_BINDING_REQUIRED")
    if not isinstance(office_store, AIOfficeStateStore):
        raise AIActivationError("AI_OFFICE_STORE_REQUIRED")
    if office_store.project_id != binding.project_id or office_store.run_id != binding.activation_request_id:
        raise AIActivationError("AI_ACTIVATION_CONFLICT: office identity mismatch")

    requirement = _requirement_for_binding(binding)
    approved_plan_ref, baseline_ref = _expected_refs(binding)
    exists = office_store.snapshot_path.exists() or office_store.journal_path.exists()
    if exists:
        try:
            snapshot = office_store.load()
        except AIOfficeStateStoreError as exc:
            raise AIActivationError("AI_ACTIVATION_CONFLICT: existing workflow is invalid") from exc
        exact = (
            snapshot.approved_plan_ref == approved_plan_ref
            and snapshot.baseline_ref == baseline_ref
            and snapshot.workflow_state == "INTAKE_READY"
            and snapshot.revision == 1
            and not snapshot.workflow_refs
            and not snapshot.pending_approval_ref
            and not snapshot.pending_manual_action_ref
        )
        if not exact:
            raise AIActivationError("AI_ACTIVATION_CONFLICT: existing workflow differs")
    else:
        try:
            office_store.initialize(approved_plan_ref=approved_plan_ref, baseline_ref=baseline_ref)
            coordinator = WorkflowCoordinator(
                office_store, office_id="AI_OFFICE", department_id="HARNESS_ACTIVATION",
                schedule_ref=f"activation:{binding.activation_request_id}",
            )
            coordinator.transition("REQUIREMENT_ACCEPTED", reason_ref=f"requirement:{requirement.envelope_digest}")
            snapshot = office_store.load()
        except (AIOfficeStateStoreError, WorkflowContractError) as exc:
            raise AIActivationError("AI_ACTIVATION_CONFLICT: workflow initialization failed") from exc

    return AIActivationContextV1(
        schema_version=AI_ACTIVATION_CONTEXT_SCHEMA_V1,
        activation_request_id=binding.activation_request_id,
        project_id=binding.project_id,
        office_run_id=office_store.run_id,
        requirement_id=requirement.requirement_id,
        requirement_envelope_digest=requirement.envelope_digest,
        full_plan_plan_digest=binding.approved_plan_sha256,
        full_plan_spec_digest=binding.approved_spec_sha256,
        requirement_artifact_digest=binding.requirement_artifact_sha256,
        approval_ref=binding.approval_ref,
        expected_head=binding.expected_head,
        workflow_state=snapshot.workflow_state,
        workflow_revision=snapshot.revision,
        workflow_state_digest=canonical_digest(snapshot.to_dict()),
    )
