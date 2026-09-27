"""Validation-only request that authorizes create-once P3 evidence issuance."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .lifecycle_v2_p3_promotion_admission import LifecycleV2P3PromotionAdmissionRequest


SCHEMA = "orchestration.lifecycle-v2-p3-canary-validate-evidence-issue-request.v1"
_FIELDS = {"schema_version", "request_id", "admission_request", "admission_request_digest", "admission_evidence_digest", "admission_digest", "admission_status", "approval_ref"}
_SAFE = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class P3CanaryValidateEvidenceIssueRequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class P3CanaryValidateEvidenceIssueRequest:
    schema_version: str
    request_id: str
    admission_request: LifecycleV2P3PromotionAdmissionRequest
    admission_request_digest: str
    admission_evidence_digest: str
    admission_digest: str
    admission_status: str
    approval_ref: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "P3CanaryValidateEvidenceIssueRequest":
        if not isinstance(raw, Mapping) or set(raw) != _FIELDS or raw.get("schema_version") != SCHEMA:
            raise P3CanaryValidateEvidenceIssueRequestError("request fields mismatch")
        try:
            admission = LifecycleV2P3PromotionAdmissionRequest.from_mapping(raw["admission_request"])
        except Exception as exc:
            raise P3CanaryValidateEvidenceIssueRequestError("invalid admission request") from exc
        values = {key: str(raw[key] or "") for key in _FIELDS - {"schema_version", "admission_request"}}
        if any(not _SAFE.fullmatch(values[key]) or ".." in values[key] for key in ("request_id", "admission_status", "approval_ref")):
            raise P3CanaryValidateEvidenceIssueRequestError("invalid request identity")
        if any(not _SHA.fullmatch(values[key]) for key in ("admission_request_digest", "admission_evidence_digest", "admission_digest")):
            raise P3CanaryValidateEvidenceIssueRequestError("invalid admission digest")
        if values["admission_status"] != "P3_CANARY_ADMISSION_READY" or values["admission_request_digest"] != admission.request_digest:
            raise P3CanaryValidateEvidenceIssueRequestError("admission lineage mismatch")
        return cls(SCHEMA, values["request_id"], admission, values["admission_request_digest"], values["admission_evidence_digest"], values["admission_digest"], values["admission_status"], values["approval_ref"])

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "request_id": self.request_id, "admission_request": self.admission_request.to_dict(), "admission_request_digest": self.admission_request_digest, "admission_evidence_digest": self.admission_evidence_digest, "admission_digest": self.admission_digest, "admission_status": self.admission_status, "approval_ref": self.approval_ref}
