"""AI Office governance context for validated executable Full Plan activation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runtime.orchestrator.approved_full_plan_binding import ExecutableAuthorityBundleV1

from .contracts import canonical_digest
from .requirement_intake import RequirementEnvelopeV1, RequirementIntakeError, intake_requirement
from .state_store import AIOfficeStateStore, AIOfficeStateStoreError
from .workflow import WorkflowContractError, WorkflowCoordinator

AI_FULL_PLAN_ACTIVATION_CONTEXT_SCHEMA_V1 = "ai-office.full-plan-activation-context.v1"


class AIFullPlanActivationError(ValueError):
    pass


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise AIFullPlanActivationError(f"invalid {label}")
    return text


@dataclass(frozen=True, slots=True)
class AIFullPlanActivationContextV1:
    schema_version: str
    activation_request_id: str
    project_id: str
    office_run_id: str
    requirement_id: str
    requirement_envelope_digest: str
    approved_plan_digest: str
    approved_spec_digest: str
    approval_ref: str
    expected_head: str
    executable_authority_bundle_digest: str
    gate_ids: tuple[str, ...]
    workflow_state: str
    workflow_revision: int
    workflow_state_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != AI_FULL_PLAN_ACTIVATION_CONTEXT_SCHEMA_V1:
            raise AIFullPlanActivationError("unsupported AI Full Plan activation context schema")
        for value, label in (
            (self.activation_request_id, "activation request ID"), (self.project_id, "project ID"),
            (self.office_run_id, "office run ID"), (self.requirement_id, "requirement ID"),
            (self.approval_ref, "approval ref"), (self.workflow_state, "workflow state"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise AIFullPlanActivationError(f"invalid {label}")
        for value, label in (
            (self.requirement_envelope_digest, "requirement envelope digest"),
            (self.approved_plan_digest, "approved plan digest"),
            (self.approved_spec_digest, "approved spec digest"),
            (self.executable_authority_bundle_digest, "executable authority bundle digest"),
            (self.workflow_state_digest, "workflow state digest"),
        ):
            _digest(value, label)
        if not self.gate_ids or len(self.gate_ids) != len(set(self.gate_ids)):
            raise AIFullPlanActivationError("invalid Gate IDs")
        if not isinstance(self.workflow_revision, int) or isinstance(self.workflow_revision, bool) or self.workflow_revision < 0:
            raise AIFullPlanActivationError("invalid workflow revision")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["gate_ids"] = list(self.gate_ids); return value

    @property
    def context_digest(self) -> str:
        return canonical_digest(self.to_dict())


def _requirement_for_bundle(bundle: ExecutableAuthorityBundleV1) -> RequirementEnvelopeV1:
    requirement_id = f"approved-full-plan:{bundle.activation_request_id}"
    source_ref = f"approved-plan:{bundle.approved_plan_path}"
    planning_ref = "full-plan:approved-executable"
    constraints = (
        f"approved-spec-sha256:{bundle.approved_spec_sha256}",
        f"authority-bundle-sha256:{bundle.bundle_digest}",
        f"approval-ref-digest:{canonical_digest({'approval_ref': bundle.approval_ref})}",
    )
    approved = {
        "source_ref": source_ref, "source_digest": bundle.approved_plan_sha256,
        "planning_authority_ref": planning_ref, "constraints_refs": constraints,
    }
    candidate = {"requirement_id": requirement_id, **approved, "correlation_id": bundle.activation_request_id}
    try:
        return intake_requirement(candidate, approved_register={requirement_id: approved})
    except RequirementIntakeError as exc:
        raise AIFullPlanActivationError("AI_FULL_PLAN_ACTIVATION_REQUIREMENT_BLOCKED") from exc


def coordinate_approved_full_plan_activation(
    bundle: ExecutableAuthorityBundleV1, *, office_store: AIOfficeStateStore,
) -> AIFullPlanActivationContextV1:
    if not isinstance(bundle, ExecutableAuthorityBundleV1):
        raise AIFullPlanActivationError("EXECUTABLE_AUTHORITY_BUNDLE_REQUIRED")
    if not isinstance(office_store, AIOfficeStateStore):
        raise AIFullPlanActivationError("AI_OFFICE_STORE_REQUIRED")
    if office_store.project_id != bundle.project_id or office_store.run_id != bundle.activation_request_id:
        raise AIFullPlanActivationError("AI_FULL_PLAN_ACTIVATION_CONFLICT: office identity mismatch")

    requirement = _requirement_for_bundle(bundle)
    approved_plan_ref = f"plan:{bundle.approved_plan_sha256}"
    baseline_ref = f"head:{bundle.expected_head}"
    exists = office_store.snapshot_path.exists() or office_store.journal_path.exists()
    if exists:
        try:
            snapshot = office_store.load()
        except AIOfficeStateStoreError as exc:
            raise AIFullPlanActivationError("AI_FULL_PLAN_ACTIVATION_CONFLICT: existing workflow is invalid") from exc
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
            raise AIFullPlanActivationError("AI_FULL_PLAN_ACTIVATION_CONFLICT: existing workflow differs")
    else:
        try:
            office_store.initialize(approved_plan_ref=approved_plan_ref, baseline_ref=baseline_ref)
            WorkflowCoordinator(
                office_store, office_id="AI_OFFICE", department_id="HARNESS_ACTIVATION",
                schedule_ref=f"activation:{bundle.activation_request_id}",
            ).transition("REQUIREMENT_ACCEPTED", reason_ref=f"requirement:{requirement.envelope_digest}")
            snapshot = office_store.load()
        except (AIOfficeStateStoreError, WorkflowContractError) as exc:
            raise AIFullPlanActivationError("AI_FULL_PLAN_ACTIVATION_CONFLICT: workflow initialization failed") from exc

    return AIFullPlanActivationContextV1(
        schema_version=AI_FULL_PLAN_ACTIVATION_CONTEXT_SCHEMA_V1,
        activation_request_id=bundle.activation_request_id, project_id=bundle.project_id,
        office_run_id=office_store.run_id, requirement_id=requirement.requirement_id,
        requirement_envelope_digest=requirement.envelope_digest,
        approved_plan_digest=bundle.approved_plan_sha256, approved_spec_digest=bundle.approved_spec_sha256,
        approval_ref=bundle.approval_ref, expected_head=bundle.expected_head,
        executable_authority_bundle_digest=bundle.bundle_digest,
        gate_ids=tuple(g.gate_id for g in bundle.gates), workflow_state=snapshot.workflow_state,
        workflow_revision=snapshot.revision, workflow_state_digest=canonical_digest(snapshot.to_dict()),
    )
