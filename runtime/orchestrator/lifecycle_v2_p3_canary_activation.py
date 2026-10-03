"""Fail-closed authorization contract for Lifecycle V2 P3 bounded canary activation.

This module does not execute effects. It authorizes only registration of the single fresh
Full Plan candidate already admitted by the read-only P3 Promotion Admission seam. All
later lifecycle authorities remain explicitly false.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .approved_full_plan_activation_contract import (
    ApprovedFullPlanActivationContractError,
    ApprovedFullPlanActivationRequestV1,
)
from .lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionError,
    LifecycleV2P3PromotionAdmissionRequest,
    LifecycleV2P3PromotionAdmissionResult,
)


LIFECYCLE_V2_P3_CANARY_ACTIVATION_SCHEMA = (
    "orchestration.lifecycle-v2-p3-canary-activation-request.v1"
)
LIFECYCLE_V2_P3_CANARY_ACTIVATION_RESULT_SCHEMA = (
    "orchestration.lifecycle-v2-p3-canary-activation-result.v1"
)

_REQUEST_FIELDS = {
    "schema_version",
    "request_id",
    "admission_request",
    "admission_request_digest",
    "admission_evidence_digest",
    "admission_digest",
    "admission_status",
    "full_plan_activation",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class LifecycleV2P3CanaryActivationError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise LifecycleV2P3CanaryActivationError(f"invalid {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise LifecycleV2P3CanaryActivationError(f"invalid {label}")
    return text


@dataclass(frozen=True, slots=True)
class LifecycleV2P3CanaryActivationRequest:
    schema_version: str
    request_id: str
    admission_request: LifecycleV2P3PromotionAdmissionRequest
    admission_request_digest: str
    admission_evidence_digest: str
    admission_digest: str
    admission_status: str
    full_plan_activation: ApprovedFullPlanActivationRequestV1

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
    ) -> "LifecycleV2P3CanaryActivationRequest":
        if not isinstance(raw, Mapping):
            raise LifecycleV2P3CanaryActivationError("request must be an object")
        if set(raw) != _REQUEST_FIELDS:
            raise LifecycleV2P3CanaryActivationError("request fields mismatch")
        if raw.get("schema_version") != LIFECYCLE_V2_P3_CANARY_ACTIVATION_SCHEMA:
            raise LifecycleV2P3CanaryActivationError("unsupported request schema")
        if not isinstance(raw.get("admission_request"), Mapping):
            raise LifecycleV2P3CanaryActivationError("admission request must be an object")
        if not isinstance(raw.get("full_plan_activation"), Mapping):
            raise LifecycleV2P3CanaryActivationError("Full Plan activation must be an object")
        try:
            admission = LifecycleV2P3PromotionAdmissionRequest.from_mapping(
                raw["admission_request"]
            )
        except LifecycleV2P3PromotionAdmissionError as exc:
            raise LifecycleV2P3CanaryActivationError(
                f"invalid admission request: {exc}"
            ) from exc
        try:
            activation = ApprovedFullPlanActivationRequestV1.from_mapping(
                raw["full_plan_activation"]
            )
        except ApprovedFullPlanActivationContractError as exc:
            raise LifecycleV2P3CanaryActivationError(
                f"invalid Full Plan activation: {exc}"
            ) from exc

        request = cls(
            schema_version=LIFECYCLE_V2_P3_CANARY_ACTIVATION_SCHEMA,
            request_id=_safe_id(raw["request_id"], "request ID"),
            admission_request=admission,
            admission_request_digest=_digest(
                raw["admission_request_digest"], "admission request digest"
            ),
            admission_evidence_digest=_digest(
                raw["admission_evidence_digest"], "admission evidence digest"
            ),
            admission_digest=_digest(raw["admission_digest"], "admission digest"),
            admission_status=_safe_id(raw["admission_status"], "admission status"),
            full_plan_activation=activation,
        )
        request._validate_boundary()
        return request

    def _validate_boundary(self) -> None:
        admission = self.admission_request
        activation = self.full_plan_activation
        if self.admission_status != "P3_CANARY_ADMISSION_READY":
            raise LifecycleV2P3CanaryActivationError("P3 admission is not ready")
        if self.admission_request_digest != admission.request_digest:
            raise LifecycleV2P3CanaryActivationError("admission request digest mismatch")
        if activation.activation_request_id != admission.candidate_run_id:
            raise LifecycleV2P3CanaryActivationError("candidate activation ID mismatch")
        if activation.project_alias != admission.project_alias:
            raise LifecycleV2P3CanaryActivationError("candidate project mismatch")
        if activation.expected_branch != admission.expected_branch:
            raise LifecycleV2P3CanaryActivationError("candidate branch mismatch")
        if activation.expected_head != admission.expected_head:
            raise LifecycleV2P3CanaryActivationError("candidate HEAD mismatch")
        if admission.candidate_run_origin != "FRESH_ACTIVATION":
            raise LifecycleV2P3CanaryActivationError("candidate must be a fresh activation")
        if tuple(admission.canary_scope) != (admission.candidate_run_id,):
            raise LifecycleV2P3CanaryActivationError("canary scope must contain only candidate")
        if admission.runtime_current_switch_requested:
            raise LifecycleV2P3CanaryActivationError("runtime-current switch is forbidden")
        if admission.existing_run_migration_requested:
            raise LifecycleV2P3CanaryActivationError("existing run migration is forbidden")
        if admission.predecessor_quiesce_requested:
            raise LifecycleV2P3CanaryActivationError("predecessor quiesce is forbidden")
        if not admission.predecessor_serving_required:
            raise LifecycleV2P3CanaryActivationError("predecessor must remain serving")

    @property
    def request_digest(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "admission_request": self.admission_request.to_dict(),
            "admission_request_digest": self.admission_request_digest,
            "admission_evidence_digest": self.admission_evidence_digest,
            "admission_digest": self.admission_digest,
            "admission_status": self.admission_status,
            "full_plan_activation": self.full_plan_activation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LifecycleV2P3CanaryActivationResult:
    schema_version: str
    request_id: str
    project_alias: str
    request_digest: str
    admission_digest: str
    status: str
    canary_run_id: str
    candidate_run_registration_authorized: bool
    runtime_current_switch_authorized: bool
    existing_run_migration_authorized: bool
    predecessor_shutdown_authorized: bool
    generic_mutation_authorized: bool
    authorization_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "project_alias": self.project_alias,
            "request_digest": self.request_digest,
            "admission_digest": self.admission_digest,
            "status": self.status,
            "canary_run_id": self.canary_run_id,
            "candidate_run_registration_authorized": self.candidate_run_registration_authorized,
            "runtime_current_switch_authorized": self.runtime_current_switch_authorized,
            "existing_run_migration_authorized": self.existing_run_migration_authorized,
            "predecessor_shutdown_authorized": self.predecessor_shutdown_authorized,
            "generic_mutation_authorized": self.generic_mutation_authorized,
            "authorization_digest": self.authorization_digest,
        }


def evaluate_p3_canary_activation(
    request: LifecycleV2P3CanaryActivationRequest,
    admission: LifecycleV2P3PromotionAdmissionResult,
) -> LifecycleV2P3CanaryActivationResult:
    if not isinstance(request, LifecycleV2P3CanaryActivationRequest):
        raise LifecycleV2P3CanaryActivationError("validated activation request required")
    if not isinstance(admission, LifecycleV2P3PromotionAdmissionResult):
        raise LifecycleV2P3CanaryActivationError("validated admission result required")
    if admission.status != "P3_CANARY_ADMISSION_READY":
        raise LifecycleV2P3CanaryActivationError("P3 admission is not ready")
    if admission.request_id != request.admission_request.request_id:
        raise LifecycleV2P3CanaryActivationError("admission request ID mismatch")
    if admission.project_alias != request.admission_request.project_alias:
        raise LifecycleV2P3CanaryActivationError("admission project mismatch")
    if admission.request_digest != request.admission_request_digest:
        raise LifecycleV2P3CanaryActivationError("admission request digest mismatch")
    if admission.evidence_digest != request.admission_evidence_digest:
        raise LifecycleV2P3CanaryActivationError("admission evidence digest mismatch")
    if admission.admission_digest != request.admission_digest:
        raise LifecycleV2P3CanaryActivationError("admission digest mismatch")
    if admission.canary_run_id != request.admission_request.candidate_run_id:
        raise LifecycleV2P3CanaryActivationError("admitted candidate mismatch")
    if (
        admission.mutation_authorized
        or admission.runtime_current_switch_authorized
        or admission.existing_run_migration_authorized
        or admission.predecessor_shutdown_authorized
    ):
        raise LifecycleV2P3CanaryActivationError("admission authority boundary widened")

    unsigned = {
        "schema_version": LIFECYCLE_V2_P3_CANARY_ACTIVATION_RESULT_SCHEMA,
        "request_id": request.request_id,
        "project_alias": request.admission_request.project_alias,
        "request_digest": request.request_digest,
        "admission_digest": request.admission_digest,
        "status": "P3_CANARY_ACTIVATION_AUTHORIZED",
        "canary_run_id": request.admission_request.candidate_run_id,
        "candidate_run_registration_authorized": True,
        "runtime_current_switch_authorized": False,
        "existing_run_migration_authorized": False,
        "predecessor_shutdown_authorized": False,
        "generic_mutation_authorized": False,
    }
    return LifecycleV2P3CanaryActivationResult(
        **unsigned,
        authorization_digest=_sha256(unsigned),
    )
