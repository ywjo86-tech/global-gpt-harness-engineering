"""Typed, validation-only remote request for an already admitted P3 candidate."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionError,
    LifecycleV2P3PromotionAdmissionRequest,
)
from .p3_canary_validate_binding import (
    P3CanaryValidateBinding,
    P3CanaryValidateBindingError,
)
from .p3_canary_validate_evidence import (
    P3CanaryValidateEvidence,
    P3CanaryValidateEvidenceError,
)


P3_CANARY_VALIDATE_REGISTRATION_SCHEMA = (
    "orchestration.lifecycle-v2-p3-canary-validate-registration-request.v1"
)
_FIELDS = {
    "schema_version",
    "request_id",
    "admission_request",
    "admission_request_digest",
    "admission_evidence_digest",
    "admission_digest",
    "admission_status",
    "binding",
    "evidence",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class P3CanaryValidateRegistrationRequestError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise P3CanaryValidateRegistrationRequestError(f"invalid {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise P3CanaryValidateRegistrationRequestError(f"invalid {label}")
    return text


@dataclass(frozen=True, slots=True)
class P3CanaryValidateRegistrationRequest:
    schema_version: str
    request_id: str
    admission_request: LifecycleV2P3PromotionAdmissionRequest
    admission_request_digest: str
    admission_evidence_digest: str
    admission_digest: str
    admission_status: str
    binding: P3CanaryValidateBinding
    evidence: P3CanaryValidateEvidence

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "P3CanaryValidateRegistrationRequest":
        if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
            raise P3CanaryValidateRegistrationRequestError("request fields mismatch")
        if raw.get("schema_version") != P3_CANARY_VALIDATE_REGISTRATION_SCHEMA:
            raise P3CanaryValidateRegistrationRequestError("unsupported request schema")
        try:
            admission = LifecycleV2P3PromotionAdmissionRequest.from_mapping(raw["admission_request"])
            binding = P3CanaryValidateBinding.from_mapping(raw["binding"])
            evidence = P3CanaryValidateEvidence.from_mapping(raw["evidence"])
        except (
            LifecycleV2P3PromotionAdmissionError,
            P3CanaryValidateBindingError,
            P3CanaryValidateEvidenceError,
            TypeError,
        ) as exc:
            raise P3CanaryValidateRegistrationRequestError("invalid P3 validation lineage") from exc
        request = cls(
            schema_version=P3_CANARY_VALIDATE_REGISTRATION_SCHEMA,
            request_id=_safe_id(raw["request_id"], "request ID"),
            admission_request=admission,
            admission_request_digest=_digest(raw["admission_request_digest"], "admission request digest"),
            admission_evidence_digest=_digest(raw["admission_evidence_digest"], "admission evidence digest"),
            admission_digest=_digest(raw["admission_digest"], "admission digest"),
            admission_status=_safe_id(raw["admission_status"], "admission status"),
            binding=binding,
            evidence=evidence,
        )
        request._validate_boundary()
        return request

    def _validate_boundary(self) -> None:
        admission = self.admission_request
        binding = self.binding
        evidence = self.evidence
        if self.admission_status != "P3_CANARY_ADMISSION_READY":
            raise P3CanaryValidateRegistrationRequestError("P3 admission is not ready")
        if self.admission_request_digest != admission.request_digest:
            raise P3CanaryValidateRegistrationRequestError("admission request digest mismatch")
        if (
            binding.project_alias != admission.project_alias
            or binding.candidate_run_id != admission.candidate_run_id
            or binding.admission_request_id != admission.request_id
            or binding.admission_request_digest != self.admission_request_digest
            or binding.admission_evidence_digest != self.admission_evidence_digest
            or binding.admission_digest != self.admission_digest
            or binding.p3_canary_validate_evidence_digest != evidence.evidence_digest
        ):
            raise P3CanaryValidateRegistrationRequestError("binding lineage mismatch")
        if (
            evidence.project_alias != admission.project_alias
            or evidence.candidate_run_id != admission.candidate_run_id
            or evidence.admission_request_id != admission.request_id
            or evidence.admission_request_digest != self.admission_request_digest
            or evidence.admission_evidence_digest != self.admission_evidence_digest
            or evidence.admission_digest != self.admission_digest
            or evidence.approval_ref != binding.approval_ref
            or evidence.scope != "P3_CANARY_VALIDATE"
        ):
            raise P3CanaryValidateRegistrationRequestError("evidence lineage mismatch")

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "admission_request": self.admission_request.to_dict(),
            "admission_request_digest": self.admission_request_digest,
            "admission_evidence_digest": self.admission_evidence_digest,
            "admission_digest": self.admission_digest,
            "admission_status": self.admission_status,
            "binding": self.binding.to_dict(),
            "evidence": self.evidence.to_dict(),
        }
