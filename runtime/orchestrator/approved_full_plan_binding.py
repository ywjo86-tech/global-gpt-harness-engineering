"""Read-only authority validation for executable approved Full Plan activation."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .approved_full_plan_activation_contract import (
    ApprovedFullPlanActivationRequestV1, GateBindingRefV1,
)
from .approved_work_binding import ApprovedWorkBindingError, resolve_committed_project_file
from .contract_adapter import ContractMappingError, load_project_mapping, sha256_file, validate_mapping_sources
from .gate_approval import GateApprovalError, load_approval_evidence
from .gate_orchestrator import (
    GateOrchestrationError, GatePlan, load_gate_plan, load_project_requirement_contract,
    load_requirement_evidence, namespace_root, validate_global_gate_bindings,
)
from .project_onboarding import OnboardingRegistry, ProjectOnboardingError
from .runtime_release import RuntimeReleaseManifest
from .task_contract_compat import TaskContractProjectionError, resolve_task_project_requirement_contract


class ApprovedFullPlanBindingError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git(root: Path, *args: str, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=20,
    )
    if result.returncode != 0 and not allow_nonzero:
        raise ApprovedFullPlanBindingError("SOURCE_BINDING_MISMATCH: Git verification failed")
    return result


def resolve_executable_authority_roots(configured_root: str | Path) -> tuple[Path, Path, Path]:
    root = Path(configured_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: authority root unsafe")
    aliases = root / "aliases"
    mappings = root / "mappings"
    for path in (aliases, mappings):
        if path.is_symlink() or not path.is_dir() or path.resolve() != path:
            raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: authority registry incomplete")
    return root, aliases, mappings


def resolve_harness_authority_file(*, harness_state_root: str | Path, project_id: str,
                                   kind: str, raw: object, label: str) -> tuple[Path, str]:
    if kind not in {"approval", "artifact"}:
        raise ApprovedFullPlanBindingError(f"{label}: invalid authority namespace")
    text = str(raw or "")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts or "\\" in text:
        raise ApprovedFullPlanBindingError(f"{label}: unsafe namespace-relative path")
    root = Path(harness_state_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ApprovedFullPlanBindingError(f"{label}: Harness state root unsafe")
    base = namespace_root(root, project_id, kind)
    target = base.joinpath(*relative.parts)
    try:
        parts = target.relative_to(root).parts
    except ValueError as exc:
        raise ApprovedFullPlanBindingError(f"{label}: authority namespace escape") from exc
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ApprovedFullPlanBindingError(f"{label}: symlinked authority path")
    if not target.is_file() or target.is_symlink():
        raise ApprovedFullPlanBindingError(f"{label}: authority artifact missing")
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(base)
    except (OSError, ValueError) as exc:
        raise ApprovedFullPlanBindingError(f"{label}: authority namespace escape") from exc
    return resolved, relative.as_posix()


@dataclass(frozen=True, slots=True)
class ValidatedGateAuthorityV1:
    gate_id: str
    approval_evidence_path: str
    approval_evidence_sha256: str
    requirements_sha256: str
    engine_requirement_evidence_path: str
    engine_requirement_evidence_sha256: str
    project_requirement_evidence_paths_by_lv: tuple[tuple[str, str, str], ...]
    lv_order: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["project_requirement_evidence_paths_by_lv"] = [list(row) for row in self.project_requirement_evidence_paths_by_lv]
        value["lv_order"] = list(self.lv_order)
        return value


@dataclass(frozen=True, slots=True)
class ExecutableAuthorityBundleV1:
    schema_version: str
    activation_request_id: str
    request_digest: str
    project_alias: str
    project_id: str
    project_root: str
    authority_root: str
    mapping_root: str
    approved_plan_path: str
    approved_plan_sha256: str
    approved_spec_path: str
    approved_spec_sha256: str
    approval_ref: str
    expected_branch: str
    expected_head: str
    runtime_release_digest: str
    runtime_release_source_head: str
    runtime_code_root: str
    gates: tuple[ValidatedGateAuthorityV1, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["gates"] = [gate.to_dict() for gate in self.gates]
        return value

    @property
    def bundle_digest(self) -> str:
        return _sha(self.to_dict())


def _committed(root: Path, raw: object, label: str, error: str) -> tuple[Path, str]:
    try:
        return resolve_committed_project_file(root, raw, label)
    except ApprovedWorkBindingError as exc:
        raise ApprovedFullPlanBindingError(error) from exc


def _validate_gate_requirement_artifacts(*, project_root: Path, harness_state_root: Path,
                                         project_id: str, plan: GatePlan,
                                         gate_ref: GateBindingRefV1, approval_path: Path,
                                         approval_sha256: str, requirements_sha256: str,
                                         project_requirements_required: bool) -> ValidatedGateAuthorityV1:
    engine_path = ""
    engine_sha256 = ""
    engine_ref = gate_ref.engine_requirement_evidence
    if engine_ref is not None:
        resolved, _ = resolve_harness_authority_file(
            harness_state_root=harness_state_root, project_id=project_id, kind="artifact",
            raw=engine_ref.path, label="EXECUTABLE_REQUIREMENT_BINDING_MISMATCH",
        )
        engine_sha256 = sha256_file(resolved)
        if engine_sha256 != engine_ref.sha256:
            raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
        try:
            load_requirement_evidence(resolved, requirements_sha256=requirements_sha256)
        except (GateOrchestrationError, OSError, ValueError) as exc:
            raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH") from exc
        engine_path = str(resolved)

    supplied = {item.lv_id: item for item in gate_ref.project_requirement_evidence_by_lv}
    expected_lvs = [item.lv_id for item in plan.lvs]
    if project_requirements_required and set(supplied) != set(expected_lvs):
        raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
    if not project_requirements_required and supplied:
        raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")

    project_rows: list[tuple[str, str, str]] = []
    if project_requirements_required:
        plan_text = (project_root / plan.canonical_plan_path).read_text(encoding="utf-8")
        for lv in plan.lvs:
            try:
                expected = resolve_task_project_requirement_contract(
                    plan_text, project_id=plan.project_id,
                    canonical_plan_sha256=plan.canonical_plan_sha256,
                    gate_id=plan.gate_id, task_id=lv.lv_id,
                    owned_files=list(lv.owned_files),
                )
            except (TaskContractProjectionError, OSError, ValueError) as exc:
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH") from exc
            ref = supplied[lv.lv_id]
            resolved, _ = _committed(
                project_root, ref.path, f"project requirement evidence {lv.lv_id}",
                "EXECUTABLE_REQUIREMENT_BINDING_MISMATCH",
            )
            actual_sha = sha256_file(resolved)
            if actual_sha != ref.sha256:
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
            try:
                loaded = load_project_requirement_contract(
                    resolved, project_id=plan.project_id, gate_id=plan.gate_id,
                    lv_id=lv.lv_id, plan_sha256=plan.canonical_plan_sha256,
                    expected_requirement_ids=tuple(expected["requirements"]),
                )
            except (GateOrchestrationError, OSError, ValueError) as exc:
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH") from exc
            if dict(loaded) != dict(expected["requirements"]):
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
            project_rows.append((lv.lv_id, str(resolved), actual_sha))

    if not project_rows and not engine_path:
        raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
    return ValidatedGateAuthorityV1(
        gate_id=plan.gate_id,
        approval_evidence_path=str(approval_path), approval_evidence_sha256=approval_sha256,
        requirements_sha256=requirements_sha256,
        engine_requirement_evidence_path=engine_path, engine_requirement_evidence_sha256=engine_sha256,
        project_requirement_evidence_paths_by_lv=tuple(project_rows),
        lv_order=tuple(item.lv_id for item in plan.lvs),
    )


def validate_approved_full_plan_binding(
    request: ApprovedFullPlanActivationRequestV1 | Mapping[str, Any], *,
    authority_root: str | Path, runtime_release: RuntimeReleaseManifest,
    harness_state_root: str | Path,
) -> ExecutableAuthorityBundleV1:
    req = request if isinstance(request, ApprovedFullPlanActivationRequestV1) else ApprovedFullPlanActivationRequestV1.from_mapping(request)
    authority, aliases_root, mappings_root = resolve_executable_authority_roots(authority_root)
    try:
        registry = OnboardingRegistry(aliases_root)
        entry = next((item for item in registry.entries() if item.get("alias") == req.project_alias), None)
    except ProjectOnboardingError as exc:
        raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: project registry invalid") from exc
    if entry is None:
        raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: project alias")
    try:
        project_root = Path(str(entry["project_root"])).resolve(strict=True)
        mapping = load_project_mapping(project_root, mapping_root=mappings_root)
    except (KeyError, OSError, ValueError, ContractMappingError) as exc:
        raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH") from exc
    if mapping is None or validate_mapping_sources(mapping):
        raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH")

    plan_path, plan_relative = _committed(project_root, req.approved_plan.path, "approved plan", "EXECUTABLE_MAPPING_MISMATCH")
    spec_path, spec_relative = _committed(project_root, req.approved_spec.path, "approved spec", "EXECUTABLE_MAPPING_MISMATCH")
    plan_sha = sha256_file(plan_path); spec_sha = sha256_file(spec_path)
    if (
        str(entry.get("project_id")) != str(mapping.project_id)
        or Path(str(entry.get("project_root"))).resolve() != project_root
        or str(entry.get("canonical_plan")) != plan_relative
        or str(entry.get("canonical_plan_sha256")) != plan_sha
        or mapping.canonical_source.resolve() != plan_path.resolve()
        or mapping.canonical_sha256 != plan_sha
        or req.approved_plan.sha256 != plan_sha
        or req.approved_spec.sha256 != spec_sha
    ):
        raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH")
    if mapping.task_lv_projection_path is not None:
        try:
            projection_relative = mapping.task_lv_projection_path.relative_to(project_root).as_posix()
        except ValueError as exc:
            raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH") from exc
        projection_path, _ = _committed(project_root, projection_relative, "TASK-to-LV authority projection", "EXECUTABLE_MAPPING_MISMATCH")
        if sha256_file(projection_path) != mapping.task_lv_projection_sha256:
            raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH")

    branch = _git(project_root, "branch", "--show-current").stdout.strip()
    head = _git(project_root, "rev-parse", "HEAD").stdout.strip()
    if (branch, head) != (req.expected_branch, req.expected_head):
        raise ApprovedFullPlanBindingError("SOURCE_BINDING_MISMATCH")

    runtime_root = Path(str(runtime_release.release_path or "")).expanduser().absolute()
    try:
        runtime_canonical = runtime_root.resolve(strict=True)
    except OSError as exc:
        raise ApprovedFullPlanBindingError("RUNTIME_RELEASE_MISMATCH") from exc
    if (
        req.runtime_release_digest != str(runtime_release.manifest_sha256 or "")
        or runtime_root.is_symlink() or not runtime_root.is_dir() or runtime_canonical != runtime_root
    ):
        raise ApprovedFullPlanBindingError("RUNTIME_RELEASE_MISMATCH")

    validated_gates: list[ValidatedGateAuthorityV1] = []
    project_requirements_required = mapping.task_lv_projection_path is not None
    for gate_ref in req.gate_bindings:
        try:
            plan = load_gate_plan(project_root, gate_ref.gate_id, mapping_root=mappings_root)
        except (GateOrchestrationError, ContractMappingError, OSError, ValueError) as exc:
            raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED") from exc
        approval_path, _ = resolve_harness_authority_file(
            harness_state_root=harness_state_root, project_id=str(mapping.project_id), kind="approval",
            raw=gate_ref.approval_evidence.path, label="EXECUTABLE_APPROVAL_REQUIRED",
        )
        approval_sha = sha256_file(approval_path)
        if approval_sha != gate_ref.approval_evidence.sha256:
            raise ApprovedFullPlanBindingError("EXECUTABLE_APPROVAL_REQUIRED")
        try:
            approval = load_approval_evidence(approval_path)
            requirements_sha256 = str(approval["payload"]["requirements_sha256"])
            validate_global_gate_bindings(
                project_root, gate_ref.gate_id, requirements_sha256=requirements_sha256,
                approval_evidence=approval_path, branch=req.expected_branch, head=req.expected_head,
                harness_root=harness_state_root, mapping_root=mappings_root,
            )
        except (GateApprovalError, GateOrchestrationError, OSError, ValueError, KeyError, TypeError) as exc:
            raise ApprovedFullPlanBindingError("EXECUTABLE_APPROVAL_REQUIRED") from exc
        validated_gates.append(_validate_gate_requirement_artifacts(
            project_root=project_root, harness_state_root=Path(harness_state_root),
            project_id=str(mapping.project_id), plan=plan, gate_ref=gate_ref,
            approval_path=approval_path, approval_sha256=approval_sha,
            requirements_sha256=requirements_sha256,
            project_requirements_required=project_requirements_required,
        ))

    return ExecutableAuthorityBundleV1(
        schema_version="orchestration.executable-authority-bundle.v1",
        activation_request_id=req.activation_request_id, request_digest=req.request_digest,
        project_alias=req.project_alias, project_id=str(mapping.project_id), project_root=str(project_root),
        authority_root=str(authority), mapping_root=str(mappings_root),
        approved_plan_path=plan_relative, approved_plan_sha256=req.approved_plan.sha256,
        approved_spec_path=spec_relative, approved_spec_sha256=req.approved_spec.sha256,
        approval_ref=req.approval_ref, expected_branch=branch, expected_head=head,
        runtime_release_digest=req.runtime_release_digest,
        runtime_release_source_head=str(runtime_release.source_head),
        runtime_code_root=str(runtime_release.release_path), gates=tuple(validated_gates),
    )
