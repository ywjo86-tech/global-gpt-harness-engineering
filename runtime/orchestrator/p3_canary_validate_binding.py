"""Fail-closed binding for the single P3 validation candidate."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .approved_work_binding import ApprovedWorkBindingError, resolve_committed_project_file
from .p3_canary_validate_evidence import (
    P3CanaryValidateEvidence,
    P3CanaryValidateEvidenceError,
)


_SCHEMA = "orchestration.lifecycle-v2-p3-canary-validate-binding.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class P3CanaryValidateBindingError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise P3CanaryValidateBindingError(f"invalid {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise P3CanaryValidateBindingError(f"invalid {label}")
    return text


def _branch(value: object) -> str:
    text = str(value or "")
    if not _BRANCH.fullmatch(text) or ".." in text or "//" in text or text.endswith("/"):
        raise P3CanaryValidateBindingError("invalid expected branch")
    return text


@dataclass(frozen=True, slots=True)
class P3CanaryValidateBinding:
    schema_version: str
    project_alias: str
    candidate_run_id: str
    admission_request_id: str
    admission_request_digest: str
    admission_evidence_digest: str
    admission_digest: str
    expected_branch: str
    expected_head: str
    approved_plan_path: str
    approved_plan_sha256: str
    approved_spec_path: str
    approved_spec_sha256: str
    approval_ref: str
    p3_canary_validate_evidence_digest: str
    binding_digest: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "P3CanaryValidateBinding":
        if not isinstance(raw, Mapping) or set(raw) != set(cls.__dataclass_fields__):
            raise P3CanaryValidateBindingError("binding fields mismatch")
        unsigned = {key: raw[key] for key in cls.__dataclass_fields__ if key != "binding_digest"}
        binding = cls(
            schema_version=str(unsigned["schema_version"]),
            project_alias=_safe_id(unsigned["project_alias"], "project alias"),
            candidate_run_id=_safe_id(unsigned["candidate_run_id"], "candidate run ID"),
            admission_request_id=_safe_id(unsigned["admission_request_id"], "admission request ID"),
            admission_request_digest=_digest(unsigned["admission_request_digest"], "admission request digest"),
            admission_evidence_digest=_digest(unsigned["admission_evidence_digest"], "admission evidence digest"),
            admission_digest=_digest(unsigned["admission_digest"], "admission digest"),
            expected_branch=_branch(unsigned["expected_branch"]),
            expected_head=str(unsigned["expected_head"]),
            approved_plan_path=str(unsigned["approved_plan_path"]),
            approved_plan_sha256=_digest(unsigned["approved_plan_sha256"], "approved plan digest"),
            approved_spec_path=str(unsigned["approved_spec_path"]),
            approved_spec_sha256=_digest(unsigned["approved_spec_sha256"], "approved spec digest"),
            approval_ref=_safe_id(unsigned["approval_ref"], "approval reference"),
            p3_canary_validate_evidence_digest=_digest(unsigned["p3_canary_validate_evidence_digest"], "P3 validation evidence digest"),
            binding_digest=_digest(raw["binding_digest"], "binding digest"),
        )
        if binding.schema_version != _SCHEMA or not _SHA1.fullmatch(binding.expected_head):
            raise P3CanaryValidateBindingError("unsupported binding")
        material = asdict(binding)
        material.pop("binding_digest")
        if binding.binding_digest != hashlib.sha256(_canonical(material)).hexdigest():
            raise P3CanaryValidateBindingError("binding digest mismatch")
        return binding

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def create_p3_canary_validate_binding(*, project_alias: str, candidate_run_id: str,
                                      admission_request_id: str, admission_request_digest: str,
                                      admission_evidence_digest: str, admission_digest: str,
                                      expected_branch: str, expected_head: str,
                                      approved_plan_path: str, approved_plan_sha256: str,
                                      approved_spec_path: str, approved_spec_sha256: str,
                                      approval_ref: str, p3_canary_validate_evidence_digest: str) -> P3CanaryValidateBinding:
    unsigned = {
        "schema_version": _SCHEMA, "project_alias": project_alias, "candidate_run_id": candidate_run_id,
        "admission_request_id": admission_request_id, "admission_request_digest": admission_request_digest,
        "admission_evidence_digest": admission_evidence_digest, "admission_digest": admission_digest,
        "expected_branch": expected_branch, "expected_head": expected_head,
        "approved_plan_path": approved_plan_path, "approved_plan_sha256": approved_plan_sha256,
        "approved_spec_path": approved_spec_path, "approved_spec_sha256": approved_spec_sha256,
        "approval_ref": approval_ref, "p3_canary_validate_evidence_digest": p3_canary_validate_evidence_digest,
    }
    parsed = P3CanaryValidateBinding.from_mapping({
        **unsigned,
        "binding_digest": hashlib.sha256(_canonical(unsigned)).hexdigest(),
    })
    return parsed


def validate_p3_canary_validate_binding(*, binding: P3CanaryValidateBinding | Mapping[str, Any],
                                        project_root: str | Path, evidence: Mapping[str, Any]) -> P3CanaryValidateBinding:
    sealed = binding if isinstance(binding, P3CanaryValidateBinding) else P3CanaryValidateBinding.from_mapping(binding)
    root = Path(project_root).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise P3CanaryValidateBindingError("unsafe project root")
    try:
        plan, _ = resolve_committed_project_file(root, sealed.approved_plan_path, "approved plan")
        spec, _ = resolve_committed_project_file(root, sealed.approved_spec_path, "approved spec")
    except ApprovedWorkBindingError as exc:
        raise P3CanaryValidateBindingError("committed P3 plan or spec required") from exc
    if hashlib.sha256(plan.read_bytes()).hexdigest() != sealed.approved_plan_sha256 or hashlib.sha256(spec.read_bytes()).hexdigest() != sealed.approved_spec_sha256:
        raise P3CanaryValidateBindingError("P3 plan or spec digest mismatch")
    result = subprocess.run(["git", "-C", str(root), "branch", "--show-current"], capture_output=True, text=True, check=False, timeout=10)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=10)
    if result.returncode or head.returncode or (result.stdout.strip(), head.stdout.strip()) != (sealed.expected_branch, sealed.expected_head):
        raise P3CanaryValidateBindingError("P3 source binding mismatch")
    try:
        sealed_evidence = P3CanaryValidateEvidence.from_mapping(dict(evidence))
    except (P3CanaryValidateEvidenceError, TypeError, ValueError) as exc:
        raise P3CanaryValidateBindingError("P3 evidence lineage mismatch") from exc
    if (
        sealed_evidence.evidence_digest != sealed.p3_canary_validate_evidence_digest
        or sealed_evidence.project_alias != sealed.project_alias
        or sealed_evidence.candidate_run_id != sealed.candidate_run_id
        or sealed_evidence.admission_request_id != sealed.admission_request_id
        or sealed_evidence.admission_request_digest != sealed.admission_request_digest
        or sealed_evidence.admission_evidence_digest != sealed.admission_evidence_digest
        or sealed_evidence.admission_digest != sealed.admission_digest
        or sealed_evidence.approval_ref != sealed.approval_ref
    ):
        raise P3CanaryValidateBindingError("P3 evidence lineage mismatch")
    return sealed
