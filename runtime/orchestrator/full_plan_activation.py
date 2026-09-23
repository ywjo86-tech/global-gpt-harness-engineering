"""Register validated executable approved work as generic AUTO_RECONCILE Full Plan jobs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from runtime.ai_office.full_plan_activation import AIFullPlanActivationContextV1

from .approved_full_plan_binding import ExecutableAuthorityBundleV1
from .durable_io import DurableIOError, canonical_json_bytes, durable_json_load, durable_json_save, sha256_bytes
from .production_full_plan_entry import FullPlanJobError, canonical_job_path, load_job, preflight_job, register_job
from .production_run_authority import AUTO_RECONCILE_OWNER, executor_runtime_identity

FULL_PLAN_ACTIVATION_RESULT_SCHEMA_V1 = "orchestration.full-plan-activation-result.v1"
FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1 = "orchestration.full-plan-activation-receipt.v1"


class FullPlanActivationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FullPlanActivationResultV1:
    schema_version: str
    activation_request_id: str
    project_id: str
    run_id: str
    status: str
    canonical_job_path: str
    authority_digest: str
    executable_authority_bundle_digest: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class FullPlanActivationReceiptV1:
    schema_version: str
    activation_request_id: str
    bundle_digest: str
    result_status: str
    canonical_job_path: str
    run_id: str
    authority_digest: str
    executable_authority_bundle_digest: str
    activation_digest: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "FullPlanActivationReceiptV1":
        expected = {
            "schema_version", "activation_request_id", "bundle_digest", "result_status",
            "canonical_job_path", "run_id", "authority_digest",
            "executable_authority_bundle_digest", "activation_digest",
        }
        if set(value) != expected or value.get("schema_version") != FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1:
            raise FullPlanActivationError("ACTIVATION_RECEIPT_INVALID")
        unsigned = {key: value[key] for key in value if key != "activation_digest"}
        if sha256_bytes(canonical_json_bytes(unsigned)) != str(value.get("activation_digest") or ""):
            raise FullPlanActivationError("ACTIVATION_RECEIPT_INVALID")
        return cls(**{key: str(value[key]) for key in expected})

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class FullPlanActivationStore:
    def __init__(self, state_root: str | Path) -> None:
        root = Path(state_root).resolve()
        if root.is_symlink() or not root.is_dir():
            raise FullPlanActivationError("ACTIVATION_STATE_ROOT_INVALID")
        self.root = root / "_workspace" / "full-plan-activation-receipts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".lock"

    def _path(self, request_id: str) -> Path:
        if not request_id or "/" in request_id or "\\" in request_id or ".." in request_id:
            raise FullPlanActivationError("ACTIVATION_REQUEST_ID_INVALID")
        return self.root / f"{request_id}.json"

    def _load(self, path: Path) -> FullPlanActivationReceiptV1 | None:
        if not path.exists() and not path.with_suffix(path.suffix + ".prev").exists(): return None
        try: value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc: raise FullPlanActivationError("ACTIVATION_RECEIPT_INVALID") from exc
        return FullPlanActivationReceiptV1.from_mapping(value)

    def record_or_load(self, *, request_id: str, bundle: ExecutableAuthorityBundleV1,
                       registrar: Callable[[], FullPlanActivationResultV1]) -> FullPlanActivationReceiptV1:
        if request_id != bundle.activation_request_id:
            raise FullPlanActivationError("ACTIVATION_REQUEST_BINDING_MISMATCH")
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            path = self._path(request_id); existing = self._load(path)
            if existing is not None:
                if existing.bundle_digest != bundle.bundle_digest:
                    raise FullPlanActivationError("ACTIVATION_REPLAY_CONFLICT")
                return existing
            result = registrar()
            if (not isinstance(result, FullPlanActivationResultV1)
                    or result.activation_request_id != request_id or result.run_id != request_id
                    or result.executable_authority_bundle_digest != bundle.bundle_digest):
                raise FullPlanActivationError("ACTIVATION_REGISTRAR_RESULT_INVALID")
            unsigned = {
                "schema_version": FULL_PLAN_ACTIVATION_RECEIPT_SCHEMA_V1,
                "activation_request_id": request_id, "bundle_digest": bundle.bundle_digest,
                "result_status": result.status, "canonical_job_path": result.canonical_job_path,
                "run_id": result.run_id, "authority_digest": result.authority_digest,
                "executable_authority_bundle_digest": result.executable_authority_bundle_digest,
            }
            receipt = FullPlanActivationReceiptV1(**unsigned, activation_digest=sha256_bytes(canonical_json_bytes(unsigned)))
            try: durable_json_save(path, receipt.to_dict())
            except (DurableIOError, OSError, ValueError) as exc: raise FullPlanActivationError("ACTIVATION_RECEIPT_WRITE_FAILED") from exc
            return receipt


def _git_common_dir(root: Path) -> str:
    completed = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"],
                               capture_output=True, text=True, check=False, timeout=10)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise FullPlanActivationError("ACTIVATION_SOURCE_DRIFT")
    common = Path(completed.stdout.strip())
    return str((root / common).resolve() if not common.is_absolute() else common.resolve())


def _validate_context(bundle: ExecutableAuthorityBundleV1, context: AIFullPlanActivationContextV1) -> None:
    if (context.activation_request_id != bundle.activation_request_id
            or context.project_id != bundle.project_id
            or context.office_run_id != bundle.activation_request_id
            or context.approved_plan_digest != bundle.approved_plan_sha256
            or context.approved_spec_digest != bundle.approved_spec_sha256
            or context.approval_ref != bundle.approval_ref
            or context.expected_head != bundle.expected_head
            or context.executable_authority_bundle_digest != bundle.bundle_digest
            or context.gate_ids != tuple(g.gate_id for g in bundle.gates)
            or context.workflow_state != "INTAKE_READY"):
        raise FullPlanActivationError("ACTIVATION_CONTEXT_MISMATCH")


def build_executable_full_plan_job(bundle: ExecutableAuthorityBundleV1, *,
                                   ai_context: AIFullPlanActivationContextV1,
                                   harness_state_root: str | Path) -> dict[str, Any]:
    if not isinstance(bundle, ExecutableAuthorityBundleV1): raise FullPlanActivationError("EXECUTABLE_AUTHORITY_BUNDLE_REQUIRED")
    if not isinstance(ai_context, AIFullPlanActivationContextV1): raise FullPlanActivationError("AI_FULL_PLAN_CONTEXT_REQUIRED")
    _validate_context(bundle, ai_context)
    state = Path(harness_state_root).resolve()
    if state.is_symlink() or not state.is_dir(): raise FullPlanActivationError("HARNESS_STATE_ROOT_INVALID")
    project = Path(bundle.project_root).resolve()
    job = {
        "schema_version": "orchestration.production-full-plan-job.v1", "execution_owner": AUTO_RECONCILE_OWNER,
        "project_root": str(project), "harness_root": str(state), "harness_state_root": str(state),
        "runtime_code_root": bundle.runtime_code_root, "runtime_release_digest": bundle.runtime_release_digest,
        "runtime_release_source_head": bundle.runtime_release_source_head, "mapping_root": bundle.mapping_root,
        "project_id": bundle.project_id, "run_id": bundle.activation_request_id,
        "git_common_dir": _git_common_dir(project), "expected_branch": bundle.expected_branch, "expected_head": bundle.expected_head,
        "approved_plan_path": str(project / bundle.approved_plan_path), "approved_plan_sha256": bundle.approved_plan_sha256,
        "approved_spec_path": str(project / bundle.approved_spec_path), "approved_spec_sha256": bundle.approved_spec_sha256,
        "approval_ref": bundle.approval_ref, "activation_binding_digest": bundle.request_digest,
        "executable_authority_bundle_digest": bundle.bundle_digest, "ai_office_context_digest": ai_context.context_digest,
        "required_executables": ["git"], "executor_runtime_identity": executor_runtime_identity(bundle.runtime_code_root),
        "gates": [],
    }
    for gate in bundle.gates:
        item: dict[str, Any] = {
            "gate_id": gate.gate_id, "approval_evidence": gate.approval_evidence_path,
            "approval_evidence_sha256": gate.approval_evidence_sha256, "requirements_sha256": gate.requirements_sha256,
            "branch": bundle.expected_branch, "head": bundle.expected_head,
            "full_plan_opt_in": True, "project_final_validation": True,
        }
        if gate.engine_requirement_evidence_path:
            item["requirement_evidence_path"] = gate.engine_requirement_evidence_path
            item["requirement_evidence_sha256"] = gate.engine_requirement_evidence_sha256
        if gate.project_requirement_evidence_paths_by_lv:
            item["requirement_evidence_paths_by_lv"] = {lv: path for lv, path, _ in gate.project_requirement_evidence_paths_by_lv}
            item["requirement_evidence_sha256_by_lv"] = {lv: digest for lv, _, digest in gate.project_requirement_evidence_paths_by_lv}
        job["gates"].append(item)
    return job


def activate_approved_full_plan(bundle: ExecutableAuthorityBundleV1, *,
                                ai_context: AIFullPlanActivationContextV1,
                                harness_state_root: str | Path) -> FullPlanActivationResultV1:
    _validate_context(bundle, ai_context)
    job = build_executable_full_plan_job(bundle, ai_context=ai_context, harness_state_root=harness_state_root)
    preflight = preflight_job(job)
    if preflight.get("status") != "PASS":
        raise FullPlanActivationError("ACTIVATION_PREFLIGHT_BLOCKED:" + str(preflight.get("reason")))
    existed = canonical_job_path(job).is_file()
    try:
        path = register_job(job); sealed = load_job(path)
    except FullPlanJobError as exc:
        raise FullPlanActivationError(f"ACTIVATION_BLOCKED:{exc}") from exc
    authority = str(sealed.get("authority_core_sha256") or "")
    if len(authority) != 64:
        raise FullPlanActivationError("ACTIVATION_AUTHORITY_DIGEST_MISSING")
    return FullPlanActivationResultV1(
        FULL_PLAN_ACTIVATION_RESULT_SCHEMA_V1, bundle.activation_request_id, bundle.project_id,
        bundle.activation_request_id, "FULL_PLAN_ALREADY_REGISTERED" if existed else "FULL_PLAN_REGISTERED",
        str(path), authority, bundle.bundle_digest,
    )
