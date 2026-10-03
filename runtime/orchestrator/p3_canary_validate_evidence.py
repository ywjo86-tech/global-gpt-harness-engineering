"""Create-once authority evidence for the bounded P3 validation canary."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = "orchestration.lifecycle-v2-p3-canary-validate-evidence.v1"


class P3CanaryValidateEvidenceError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value) or ".." in value:
        raise P3CanaryValidateEvidenceError(f"invalid {label}")
    return value


def _digest(value: str, label: str) -> str:
    if not _SHA256.fullmatch(value):
        raise P3CanaryValidateEvidenceError(f"invalid {label}")
    return value


@dataclass(frozen=True, slots=True)
class P3CanaryValidateEvidence:
    schema_version: str
    project_alias: str
    candidate_run_id: str
    admission_request_id: str
    admission_request_digest: str
    admission_evidence_digest: str
    admission_digest: str
    approval_ref: str
    scope: str
    evidence_digest: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: object) -> "P3CanaryValidateEvidence":
        if not isinstance(raw, dict) or set(raw) != set(cls.__dataclass_fields__):
            raise P3CanaryValidateEvidenceError("evidence fields mismatch")
        unsigned = {
            "schema_version": str(raw.get("schema_version") or ""),
            "project_alias": _safe_id(str(raw.get("project_alias") or ""), "project alias"),
            "candidate_run_id": _safe_id(str(raw.get("candidate_run_id") or ""), "candidate run ID"),
            "admission_request_id": _safe_id(str(raw.get("admission_request_id") or ""), "admission request ID"),
            "admission_request_digest": _digest(str(raw.get("admission_request_digest") or ""), "admission request digest"),
            "admission_evidence_digest": _digest(str(raw.get("admission_evidence_digest") or ""), "admission evidence digest"),
            "admission_digest": _digest(str(raw.get("admission_digest") or ""), "admission digest"),
            "approval_ref": _safe_id(str(raw.get("approval_ref") or ""), "approval reference"),
            "scope": str(raw.get("scope") or ""),
        }
        if unsigned["schema_version"] != _SCHEMA or unsigned["scope"] != "P3_CANARY_VALIDATE":
            raise P3CanaryValidateEvidenceError("unsupported evidence")
        evidence_digest = _digest(str(raw.get("evidence_digest") or ""), "evidence digest")
        if evidence_digest != hashlib.sha256(_canonical(unsigned)).hexdigest():
            raise P3CanaryValidateEvidenceError("evidence digest mismatch")
        return cls(**unsigned, evidence_digest=evidence_digest)


def issue_p3_canary_validate_evidence(
    *,
    state_root: str | Path,
    project_alias: str,
    candidate_run_id: str,
    admission_request_id: str,
    admission_request_digest: str,
    admission_evidence_digest: str,
    admission_digest: str,
    approval_ref: str,
) -> P3CanaryValidateEvidence:
    """Seal only the explicitly approved, validation-only P3 candidate."""
    unsigned = {
        "schema_version": _SCHEMA,
        "project_alias": _safe_id(project_alias, "project alias"),
        "candidate_run_id": _safe_id(candidate_run_id, "candidate run ID"),
        "admission_request_id": _safe_id(admission_request_id, "admission request ID"),
        "admission_request_digest": _digest(admission_request_digest, "admission request digest"),
        "admission_evidence_digest": _digest(admission_evidence_digest, "admission evidence digest"),
        "admission_digest": _digest(admission_digest, "admission digest"),
        "approval_ref": _safe_id(approval_ref, "approval reference"),
        "scope": "P3_CANARY_VALIDATE",
    }
    evidence = P3CanaryValidateEvidence(
        **unsigned,
        evidence_digest=hashlib.sha256(_canonical(unsigned)).hexdigest(),
    )
    root = Path(state_root).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise P3CanaryValidateEvidenceError("unsafe state root")
    target_root = root / "p3-canary-validate-evidence"
    target_root.mkdir(mode=0o700, exist_ok=True)
    if target_root.is_symlink() or not target_root.is_dir() or target_root.resolve() != target_root:
        raise P3CanaryValidateEvidenceError("unsafe evidence root")
    path = target_root / f"{evidence.admission_digest}.json"
    payload = _canonical(evidence.to_dict())
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise P3CanaryValidateEvidenceError("evidence conflict")
        return evidence
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise P3CanaryValidateEvidenceError("evidence conflict")
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return evidence
