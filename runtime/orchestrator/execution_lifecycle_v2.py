"""Activation-bound Harness Lifecycle V2 compatibility contracts.

Lifecycle V2 is an orchestration envelope over existing authority.  It does not
create approval, provider/model selection, completion, or effect authority.
Legacy jobs remain legacy when this module is present.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .operator_plan_execution import build_operator_plan_job
from .task_contract_compat import TaskContractProjectionError, resolve_task_lv_projection

LIFECYCLE_BINDING_SCHEMA = "orchestration.lifecycle-binding.v1"
EXECUTION_AUTHORITY_BUNDLE_SCHEMA = "orchestration.execution-authority-bundle.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN_AUTHORITY_FIELDS = frozenset({
    "final_assignee",
    "provider_ref",
    "model_ref",
    "completion_authority",
    "effect_authority",
})


class ExecutionLifecycleV2Error(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    normalized = str(value or "")
    if not _SHA256.fullmatch(normalized):
        raise ExecutionLifecycleV2Error(f"{label} must be a sha256 digest")
    return normalized


def _reject_forbidden_fields(value: object, *, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_AUTHORITY_FIELDS.intersection(str(key) for key in value)
        if forbidden:
            raise ExecutionLifecycleV2Error(
                f"{path} contains forbidden authority field: {sorted(forbidden)[0]}"
            )
        for key, child in value.items():
            _reject_forbidden_fields(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, path=f"{path}[{index}]")


def resolve_lifecycle_binding(job: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve lifecycle mode without mutating or upgrading an existing job.

    Absence is deliberately interpreted as LEGACY for backward compatibility.
    """
    raw = job.get("lifecycle_binding")
    if raw is None:
        return {
            "schema_version": LIFECYCLE_BINDING_SCHEMA,
            "lifecycle_mode": "LEGACY",
            "bound_at_activation": False,
            "migration_allowed": False,
            "runtime_release_digest": "",
        }
    if not isinstance(raw, Mapping):
        raise ExecutionLifecycleV2Error("lifecycle binding is malformed")
    required = {
        "schema_version",
        "lifecycle_mode",
        "bound_at_activation",
        "migration_allowed",
        "runtime_release_digest",
    }
    if set(raw) != required:
        raise ExecutionLifecycleV2Error("lifecycle binding fields mismatch")
    if raw.get("schema_version") != LIFECYCLE_BINDING_SCHEMA:
        raise ExecutionLifecycleV2Error("lifecycle binding schema mismatch")
    mode = str(raw.get("lifecycle_mode") or "")
    if mode not in {"LEGACY", "V2"}:
        raise ExecutionLifecycleV2Error("lifecycle mode is unsupported")
    if raw.get("bound_at_activation") is not True:
        raise ExecutionLifecycleV2Error("explicit lifecycle binding must be activation-bound")
    if raw.get("migration_allowed") is not False:
        raise ExecutionLifecycleV2Error("ordinary lifecycle migration must remain disabled")
    release = _require_sha256(raw.get("runtime_release_digest"), "runtime release digest")
    return {
        "schema_version": LIFECYCLE_BINDING_SCHEMA,
        "lifecycle_mode": mode,
        "bound_at_activation": True,
        "migration_allowed": False,
        "runtime_release_digest": release,
    }


def adapt_legacy_task_lv_authority(
    *,
    canonical_plan_text: str,
    canonical_plan_sha256: str,
    projection_text: str,
    projection_sha256: str,
    project_id: str,
    gate_id: str,
    authority_ref: str,
) -> dict[str, str]:
    """Validate a legacy TASK/LV projection and expose only its authority reference.

    This adapter is deliberately read-only.  It parses and validates supplied
    evidence in memory; it never rewrites the legacy projection, canonical plan,
    mapping, run, or checkpoint.
    """
    plan_sha = _require_sha256(canonical_plan_sha256, "canonical plan digest")
    expected_projection_sha = _require_sha256(projection_sha256, "legacy projection digest")
    actual_projection_sha = hashlib.sha256(projection_text.encode("utf-8")).hexdigest()
    if actual_projection_sha != expected_projection_sha:
        raise ExecutionLifecycleV2Error("legacy task/LV projection digest mismatch")
    if hashlib.sha256(canonical_plan_text.encode("utf-8")).hexdigest() != plan_sha:
        raise ExecutionLifecycleV2Error("legacy canonical plan digest mismatch")
    project = str(project_id or "").strip()
    gate = str(gate_id or "").strip()
    reference = str(authority_ref or "").strip()
    if not project or not gate or not reference:
        raise ExecutionLifecycleV2Error("legacy authority identity is incomplete")
    try:
        projection = json.loads(projection_text)
    except json.JSONDecodeError as exc:
        raise ExecutionLifecycleV2Error("legacy task/LV projection is invalid JSON") from exc
    if not isinstance(projection, Mapping):
        raise ExecutionLifecycleV2Error("legacy task/LV projection is malformed")
    try:
        resolved = resolve_task_lv_projection(
            canonical_plan_text,
            projection,
            project_id=project,
            canonical_plan_sha256=plan_sha,
            gate_id=gate,
        )
    except TaskContractProjectionError as exc:
        raise ExecutionLifecycleV2Error(str(exc)) from exc
    if not resolved:
        raise ExecutionLifecycleV2Error("legacy task/LV projection resolves no executable authority")
    authority = {
        "gate_id": gate,
        "authority_kind": "TASK_LV_PROJECTION",
        "authority_ref": reference,
        "authority_sha256": expected_projection_sha,
    }
    _reject_forbidden_fields(authority, path="legacy_authority")
    return authority


def _full_plan_gate_authority(gate: Mapping[str, Any]) -> dict[str, str]:
    gate_id = str(gate.get("gate_id") or "")
    authority_ref = str(gate.get("approval_evidence") or "")
    requirements_sha256 = _require_sha256(gate.get("requirements_sha256"), "gate requirements digest")
    branch = str(gate.get("branch") or "")
    head = str(gate.get("head") or "")
    if not gate_id or not authority_ref or not branch or not head:
        raise ExecutionLifecycleV2Error("Full Plan gate authority is incomplete")
    source: dict[str, Any] = {
        "gate_id": gate_id,
        "approval_evidence": authority_ref,
        "requirements_sha256": requirements_sha256,
        "branch": branch,
        "head": head,
        "full_plan_opt_in": gate.get("full_plan_opt_in") is True,
        "project_final_validation": gate.get("project_final_validation") is True,
    }
    if gate.get("continuation_contract") is not None:
        source["continuation_contract"] = gate["continuation_contract"]
    return {
        "gate_id": gate_id,
        "authority_kind": "FULL_PLAN_GATE",
        "authority_ref": authority_ref,
        "authority_sha256": _digest(source),
    }


def _build_execution_authority_bundle(
    job: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    if binding.get("lifecycle_mode") != "V2" or binding.get("bound_at_activation") is not True:
        raise ExecutionLifecycleV2Error("V2 authority bundle requires an activation-bound V2 lifecycle")
    gates = job.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ExecutionLifecycleV2Error("V2 authority bundle requires approved gates")
    expected_branch = str(job.get("expected_branch") or "")
    heads: set[str] = set()
    gate_authorities: list[dict[str, str]] = []
    for raw_gate in gates:
        if not isinstance(raw_gate, Mapping):
            raise ExecutionLifecycleV2Error("V2 gate authority is malformed")
        if str(raw_gate.get("branch") or "") != expected_branch:
            raise ExecutionLifecycleV2Error("V2 gate branch binding mismatch")
        head = str(raw_gate.get("head") or "")
        if not head:
            raise ExecutionLifecycleV2Error("V2 gate source head is missing")
        heads.add(head)
        gate_authorities.append(_full_plan_gate_authority(raw_gate))
    if len(heads) != 1:
        raise ExecutionLifecycleV2Error("V2 activation source head is ambiguous")

    bundle: dict[str, Any] = {
        "schema_version": EXECUTION_AUTHORITY_BUNDLE_SCHEMA,
        "project_id": str(job.get("project_id") or ""),
        "run_id": str(job.get("run_id") or ""),
        "approved_plan_sha256": _require_sha256(job.get("approved_plan_sha256"), "approved plan digest"),
        "approved_spec_sha256": _require_sha256(job.get("approved_spec_sha256"), "approved spec digest"),
        "approval_ref": str(job.get("approval_ref") or ""),
        "expected_branch": expected_branch,
        "activation_source_head": next(iter(heads)),
        "runtime_release_digest": _require_sha256(
            binding.get("runtime_release_digest"), "runtime release digest"
        ),
        "lifecycle_mode": "V2",
        "gate_authorities": gate_authorities,
    }
    if not bundle["project_id"] or not bundle["run_id"] or not bundle["approval_ref"] or not expected_branch:
        raise ExecutionLifecycleV2Error("V2 authority bundle identity is incomplete")
    _reject_forbidden_fields(bundle)
    bundle["bundle_sha256"] = _digest(bundle)
    return bundle


def validate_execution_authority_bundle(job: Mapping[str, Any]) -> dict[str, Any]:
    binding = resolve_lifecycle_binding(job)
    if binding["lifecycle_mode"] != "V2":
        raise ExecutionLifecycleV2Error("execution authority bundle is only valid for V2 jobs")
    raw = job.get("execution_authority_bundle")
    if not isinstance(raw, Mapping):
        raise ExecutionLifecycleV2Error("execution authority bundle is missing")
    required = {
        "schema_version",
        "project_id",
        "run_id",
        "approved_plan_sha256",
        "approved_spec_sha256",
        "approval_ref",
        "expected_branch",
        "activation_source_head",
        "runtime_release_digest",
        "lifecycle_mode",
        "gate_authorities",
        "bundle_sha256",
    }
    if set(raw) != required:
        raise ExecutionLifecycleV2Error("execution authority bundle fields mismatch")
    _reject_forbidden_fields(raw)
    if raw.get("schema_version") != EXECUTION_AUTHORITY_BUNDLE_SCHEMA:
        raise ExecutionLifecycleV2Error("execution authority bundle schema mismatch")
    expected = _build_execution_authority_bundle(job, binding)
    if dict(raw) != expected:
        raise ExecutionLifecycleV2Error("execution authority bundle binding mismatch")
    return dict(raw)


def build_v2_operator_plan_job(
    *,
    project_root: str | Path,
    runtime_code_root: str | Path,
    project_id: str,
    run_id: str,
    task_ids: Sequence[str],
    approved_plan_path: str | Path,
    approved_spec_path: str | Path,
    approval_ref: str,
    runtime_release_digest: str,
    harness_root: str | Path | None = None,
    harness_state_root: str | Path | None = None,
    continuation_contracts_by_gate: Mapping[str, Mapping[str, Any] | Any] | None = None,
) -> dict[str, Any]:
    """Build a new V2 job while leaving the legacy builder unchanged."""
    release = _require_sha256(runtime_release_digest, "runtime release digest")
    job = build_operator_plan_job(
        project_root=project_root,
        harness_root=harness_root,
        harness_state_root=harness_state_root,
        runtime_code_root=runtime_code_root,
        project_id=project_id,
        run_id=run_id,
        task_ids=task_ids,
        approved_plan_path=approved_plan_path,
        approved_spec_path=approved_spec_path,
        approval_ref=approval_ref,
        continuation_contracts_by_gate=continuation_contracts_by_gate,
    )
    binding = {
        "schema_version": LIFECYCLE_BINDING_SCHEMA,
        "lifecycle_mode": "V2",
        "bound_at_activation": True,
        "migration_allowed": False,
        "runtime_release_digest": release,
    }
    job["lifecycle_binding"] = binding
    job["execution_authority_bundle"] = _build_execution_authority_bundle(job, binding)
    validate_execution_authority_bundle(job)
    return job
