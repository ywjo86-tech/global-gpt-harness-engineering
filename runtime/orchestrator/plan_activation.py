"""Register already-approved Full Plan work without launching execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.ai_office.activation import AIActivationContextV1

from .approved_work_binding import ApprovedWorkBindingV1
from .operator_plan_execution import OperatorPlanExecutionError, build_operator_plan_job
from .production_full_plan_entry import FullPlanJobError, canonical_job_path, load_job, register_job

PLAN_ACTIVATION_RESULT_SCHEMA_V1 = "orchestration.plan-activation-result.v1"


class PlanActivationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PlanActivationResultV1:
    schema_version: str
    activation_request_id: str
    project_id: str
    run_id: str
    status: str
    canonical_job_path: str
    authority_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_context(binding: ApprovedWorkBindingV1, context: AIActivationContextV1) -> None:
    exact = (
        context.activation_request_id == binding.activation_request_id
        and context.project_id == binding.project_id
        and context.office_run_id == binding.activation_request_id
        and context.full_plan_plan_digest == binding.approved_plan_sha256
        and context.full_plan_spec_digest == binding.approved_spec_sha256
        and context.requirement_artifact_digest == binding.requirement_artifact_sha256
        and context.approval_ref == binding.approval_ref
        and context.expected_head == binding.expected_head
        and context.workflow_state == "INTAKE_READY"
        and context.workflow_revision == 1
    )
    if not exact:
        raise PlanActivationError("ACTIVATION_CONTEXT_MISMATCH")


def activate_approved_work(
    binding: ApprovedWorkBindingV1, *, ai_context: AIActivationContextV1,
    harness_state_root: str | Path, runtime_code_root: str | Path,
) -> PlanActivationResultV1:
    if not isinstance(binding, ApprovedWorkBindingV1):
        raise PlanActivationError("APPROVED_WORK_BINDING_REQUIRED")
    if not isinstance(ai_context, AIActivationContextV1):
        raise PlanActivationError("AI_ACTIVATION_CONTEXT_REQUIRED")
    _validate_context(binding, ai_context)
    runtime = Path(runtime_code_root).resolve()
    if runtime != Path(binding.runtime_code_root).resolve():
        raise PlanActivationError("RUNTIME_RELEASE_BINDING_MISMATCH")
    try:
        job = build_operator_plan_job(
            project_root=binding.project_root,
            harness_state_root=harness_state_root,
            runtime_code_root=runtime,
            project_id=binding.project_id,
            run_id=binding.activation_request_id,
            task_ids=binding.task_ids,
            approved_plan_path=binding.approved_plan_path,
            approved_spec_path=binding.approved_spec_path,
            approval_ref=binding.approval_ref,
        )
    except OperatorPlanExecutionError as exc:
        raise PlanActivationError(f"ACTIVATION_BLOCKED: {exc}") from exc

    gate_heads = {str(item.get("head") or "") for item in job.get("gates", ())}
    if job.get("expected_branch") != binding.expected_branch or gate_heads != {binding.expected_head}:
        raise PlanActivationError("ACTIVATION_SOURCE_DRIFT")
    planned_path = canonical_job_path(job)
    existed = planned_path.is_file()
    try:
        registered = register_job(job)
        sealed = load_job(registered)
    except FullPlanJobError as exc:
        raise PlanActivationError(f"ACTIVATION_BLOCKED: {exc}") from exc
    authority_digest = str(sealed.get("authority_core_sha256") or "")
    if len(authority_digest) != 64:
        raise PlanActivationError("ACTIVATION_AUTHORITY_DIGEST_MISSING")
    return PlanActivationResultV1(
        PLAN_ACTIVATION_RESULT_SCHEMA_V1, binding.activation_request_id,
        binding.project_id, binding.activation_request_id,
        "ALREADY_REGISTERED" if existed else "REGISTERED",
        str(registered), authority_digest,
    )
