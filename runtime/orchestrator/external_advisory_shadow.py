"""Immutable SHADOW evidence for external advisory capabilities.

Only digests and bounded metadata are retained.  The supplied canonical decision
is hashed but never mutated or copied into the record, and the record has no API
for applying advisory output to canonical state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .external_advisory_contract import (
    ExternalCapabilityRequestV1,
    ExternalCapabilityResultV1,
    canonical_external_digest,
    validate_advisory_freshness,
)

ADVISORY_SHADOW_SCHEMA_V1 = "external-capability.shadow-record.v1"


class AdvisoryShadowError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AdvisoryShadowRecordV1:
    schema_version: str
    project_id: str
    project_run_id: str
    task_id: str
    task_execution_id: str
    correlation_id: str
    operation_request_id: str
    capability_id: str
    capability_version: str
    request_digest: str
    payload_digest: str
    input_set_digest: str
    source_snapshot_digest: str
    schema_digest: str
    baseline_canonical_decision_digest: str
    advisory_result_digest: str
    evidence_ref: str
    status: str
    latency_ms: int
    confidence: float | None
    usage_digest: str
    error_code: str
    canonical_decision_delta: int = 0
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != ADVISORY_SHADOW_SCHEMA_V1:
            raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", "unsupported SHADOW record schema")
        for field in (
            "project_id", "project_run_id", "task_id", "task_execution_id",
            "correlation_id", "operation_request_id", "capability_id",
            "capability_version", "request_digest", "payload_digest",
            "input_set_digest", "source_snapshot_digest", "schema_digest",
            "baseline_canonical_decision_digest", "advisory_result_digest", "evidence_ref",
        ):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", f"SHADOW {field} is required")
        if self.status not in {"RECORDED", "UNAVAILABLE", "ERROR"}:
            raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", "SHADOW status is invalid")
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int) or self.latency_ms < 0:
            raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", "SHADOW latency is invalid")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", "SHADOW confidence is invalid")
        if self.canonical_decision_delta != 0:
            raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", "SHADOW canonical decision delta must be zero")
        if self.non_authoritative is not True:
            raise AdvisoryShadowError("CAPABILITY_RESULT_INVALID", "SHADOW evidence must be non-authoritative")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["canonical_decision_delta"] = 0
        payload["non_authoritative"] = True
        return payload


def record_shadow_advisory(
    *,
    baseline_canonical_decision: Mapping[str, Any],
    request: ExternalCapabilityRequestV1,
    result: ExternalCapabilityResultV1,
) -> AdvisoryShadowRecordV1:
    if not isinstance(baseline_canonical_decision, Mapping):
        raise AdvisoryShadowError(
            "CAPABILITY_RESULT_INVALID", "canonical decision must be a mapping"
        )
    if not validate_advisory_freshness(request, result):
        raise AdvisoryShadowError(
            "CAPABILITY_EVIDENCE_STALE", "advisory evidence does not match the current request"
        )
    error_code = result.error.code if result.error is not None else ""
    status = (
        "UNAVAILABLE" if error_code == "CAPABILITY_UNAVAILABLE"
        else "ERROR" if error_code
        else "RECORDED"
    )
    usage_digest = canonical_external_digest(dict(result.usage or {}))
    return AdvisoryShadowRecordV1(
        schema_version=ADVISORY_SHADOW_SCHEMA_V1,
        project_id=request.project_id,
        project_run_id=request.project_run_id,
        task_id=request.task_id,
        task_execution_id=request.task_execution_id,
        correlation_id=request.correlation_id,
        operation_request_id=request.operation_request_id,
        capability_id=request.capability_id,
        capability_version=request.capability_version,
        request_digest=request.request_digest,
        payload_digest=request.payload_digest,
        input_set_digest=request.input_set_digest,
        source_snapshot_digest=request.source_snapshot_digest,
        schema_digest=request.schema_digest,
        baseline_canonical_decision_digest=canonical_external_digest(
            dict(baseline_canonical_decision)
        ),
        advisory_result_digest=result.result_digest,
        evidence_ref=result.evidence_ref,
        status=status,
        latency_ms=result.latency_ms,
        confidence=result.confidence,
        usage_digest=usage_digest,
        error_code=error_code,
        canonical_decision_delta=0,
        non_authoritative=True,
    )
