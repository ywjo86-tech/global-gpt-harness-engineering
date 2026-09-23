"""Register already-approved Full Plan work without launching execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import os
from pathlib import Path
from typing import Any, Callable

from runtime.ai_office.activation import AIActivationContextV1

from .approved_work_binding import ApprovedWorkBindingV1
from .durable_io import DurableIOError, canonical_json_bytes, durable_json_load, durable_json_save, sha256_bytes
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


PLAN_ACTIVATION_RECEIPT_SCHEMA_V1 = "orchestration.plan-activation-receipt.v1"


@dataclass(frozen=True, slots=True)
class PlanActivationReceiptV1:
    schema_version: str
    activation_request_id: str
    binding_digest: str
    result_status: str
    canonical_job_path: str
    run_id: str
    authority_digest: str
    activation_digest: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "PlanActivationReceiptV1":
        expected = {
            "schema_version", "activation_request_id", "binding_digest", "result_status",
            "canonical_job_path", "run_id", "authority_digest", "activation_digest",
        }
        if set(value) != expected or value.get("schema_version") != PLAN_ACTIVATION_RECEIPT_SCHEMA_V1:
            raise PlanActivationError("ACTIVATION_RECEIPT_INVALID")
        unsigned = {key: value[key] for key in value if key != "activation_digest"}
        if sha256_bytes(canonical_json_bytes(unsigned)) != str(value.get("activation_digest") or ""):
            raise PlanActivationError("ACTIVATION_RECEIPT_INVALID")
        return cls(**{key: str(value[key]) for key in expected})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanActivationStore:
    def __init__(self, state_root: str | Path) -> None:
        root = Path(state_root).resolve()
        if root.is_symlink() or not root.is_dir():
            raise PlanActivationError("ACTIVATION_STATE_ROOT_INVALID")
        self.root = root / "_workspace" / "plan-activation-receipts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".lock"

    def _path(self, request_id: str) -> Path:
        if not request_id or "/" in request_id or "\\" in request_id or ".." in request_id:
            raise PlanActivationError("ACTIVATION_REQUEST_ID_INVALID")
        return self.root / f"{request_id}.json"

    def _load(self, path: Path) -> PlanActivationReceiptV1 | None:
        if not path.exists() and not path.with_suffix(path.suffix + ".prev").exists():
            return None
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise PlanActivationError("ACTIVATION_RECEIPT_INVALID") from exc
        return PlanActivationReceiptV1.from_mapping(value)

    def record_or_load(
        self, *, request_id: str, binding: ApprovedWorkBindingV1,
        registrar: Callable[[], PlanActivationResultV1],
    ) -> PlanActivationReceiptV1:
        if request_id != binding.activation_request_id:
            raise PlanActivationError("ACTIVATION_REQUEST_BINDING_MISMATCH")
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            path = self._path(request_id)
            existing = self._load(path)
            if existing is not None:
                if existing.binding_digest != binding.binding_digest:
                    raise PlanActivationError("ACTIVATION_REPLAY_CONFLICT")
                return existing
            result = registrar()
            if not isinstance(result, PlanActivationResultV1):
                raise PlanActivationError("ACTIVATION_REGISTRAR_RESULT_INVALID")
            if result.activation_request_id != request_id or result.run_id != request_id:
                raise PlanActivationError("ACTIVATION_REGISTRAR_RESULT_INVALID")
            unsigned = {
                "schema_version": PLAN_ACTIVATION_RECEIPT_SCHEMA_V1,
                "activation_request_id": request_id,
                "binding_digest": binding.binding_digest,
                "result_status": result.status,
                "canonical_job_path": result.canonical_job_path,
                "run_id": result.run_id,
                "authority_digest": result.authority_digest,
            }
            receipt = PlanActivationReceiptV1(
                **unsigned, activation_digest=sha256_bytes(canonical_json_bytes(unsigned))
            )
            try:
                durable_json_save(path, receipt.to_dict())
            except (DurableIOError, OSError, ValueError) as exc:
                raise PlanActivationError("ACTIVATION_RECEIPT_WRITE_FAILED") from exc
            return receipt


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
