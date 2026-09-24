"""Immutable, non-authoritative contracts for external advisory capabilities.

This module intentionally owns no routing, approval, effect, completion, network,
or persistence authority.  It only validates and normalizes evidence that may be
considered by existing Harness authorities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import re
from typing import Any, Mapping

DESCRIPTOR_SCHEMA_V1 = "external-capability.descriptor.v1"
REQUEST_SCHEMA_V1 = "external-capability.request.v1"
RESULT_SCHEMA_V1 = "external-capability.result.v1"

ALLOWED_LIFECYCLE_STATES = frozenset({
    "DISCOVERED", "QUALIFIED", "SHADOW", "CANARY",
    "READY_FOR_ACTIVATION", "ACTIVE", "QUARANTINED", "DISABLED",
})
FORBIDDEN_EXTERNAL_CONTROL_FIELDS = frozenset({
    "provider_ref", "model_ref", "provider_id", "model_id", "route", "route_ref",
    "approval", "approval_state", "authorization", "authorization_ref",
    "action", "action_state", "lifecycle_state", "completion", "completion_proof",
    "merge", "ship", "patch_apply", "execution_authority",
})

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ExternalCapabilityContractError(ValueError):
    pass


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExternalCapabilityContractError(f"{field} must be a non-empty string")
    return value


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ExternalCapabilityContractError(f"{field} digest is invalid")
    return value


def _plain(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def canonical_external_digest(value: object) -> str:
    payload = json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _reject_external_control_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_EXTERNAL_CONTROL_FIELDS:
                raise ExternalCapabilityContractError(
                    f"external payload contains forbidden control field: {key}"
                )
            _reject_external_control_fields(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_external_control_fields(item)


@dataclass(frozen=True, slots=True)
class ExternalCapabilityError:
    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        _require_text(self.code, "error code")
        _require_text(self.message, "error message")
        if self.retryable:
            raise ExternalCapabilityContractError("external advisory errors cannot grant retry authority")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExternalCapabilityDescriptorV1:
    schema_version: str
    capability_id: str
    capability_kind: str
    authority_class: str
    effect_class: str
    trust_class: str
    lifecycle_state: str
    capability_version: str
    package_or_endpoint_digest: str
    schema_digest: str
    model_backed: bool
    provider_binding_required: bool
    egress_policy_ref: str
    budget_ref: str
    retry_policy: str
    max_delegation_depth: int
    source_binding_required: bool

    def __post_init__(self) -> None:
        if self.schema_version != DESCRIPTOR_SCHEMA_V1:
            raise ExternalCapabilityContractError("unsupported descriptor schema")
        for field in (
            "capability_id", "capability_kind", "trust_class", "capability_version",
            "egress_policy_ref", "budget_ref",
        ):
            _require_text(getattr(self, field), field)
        if self.authority_class != "NONE":
            raise ExternalCapabilityContractError("external capability authority must be NONE")
        if self.effect_class not in {"READ_ONLY", "READ_ONLY_EVIDENCE"}:
            raise ExternalCapabilityContractError("external capability must be read-only")
        if self.lifecycle_state not in ALLOWED_LIFECYCLE_STATES:
            raise ExternalCapabilityContractError("unknown external capability lifecycle state")
        _require_digest(self.package_or_endpoint_digest, "package_or_endpoint_digest")
        _require_digest(self.schema_digest, "schema_digest")
        if self.retry_policy != "NONE":
            raise ExternalCapabilityContractError("external capability retry policy must be NONE")
        if isinstance(self.max_delegation_depth, bool) or self.max_delegation_depth != 0:
            raise ExternalCapabilityContractError("external capability delegation depth must be zero")
        if self.model_backed != self.provider_binding_required:
            raise ExternalCapabilityContractError("model-backed capability provider binding is inconsistent")
        if not self.source_binding_required:
            raise ExternalCapabilityContractError("source binding is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExternalCapabilityRequestV1:
    schema_version: str
    project_id: str
    project_run_id: str
    task_id: str
    task_execution_id: str
    correlation_id: str
    operation_request_id: str
    capability_id: str
    capability_version: str
    schema_digest: str
    input_set_digest: str
    source_snapshot_digest: str
    capability_admission_ref: str
    policy_ref: str
    egress_policy_ref: str
    budget_ref: str
    deadline_ms: int
    attempt: int
    payload_digest: str
    provider_decision_ref: str = ""
    provider_id: str = ""
    model_id: str = ""
    route_ref: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != REQUEST_SCHEMA_V1:
            raise ExternalCapabilityContractError("unsupported request schema")
        for field in (
            "project_id", "project_run_id", "task_id", "task_execution_id",
            "correlation_id", "operation_request_id", "capability_id", "capability_version",
            "capability_admission_ref", "policy_ref", "egress_policy_ref", "budget_ref",
        ):
            _require_text(getattr(self, field), field)
        for field in ("schema_digest", "input_set_digest", "source_snapshot_digest", "payload_digest"):
            _require_digest(getattr(self, field), field)
        if isinstance(self.deadline_ms, bool) or not isinstance(self.deadline_ms, int) or self.deadline_ms <= 0:
            raise ExternalCapabilityContractError("deadline_ms must be a positive integer")
        if isinstance(self.attempt, bool) or self.attempt != 1:
            raise ExternalCapabilityContractError("attempt must be exactly one")
        provider_binding = (
            self.provider_decision_ref, self.provider_id, self.model_id, self.route_ref
        )
        present = tuple(bool(str(value).strip()) for value in provider_binding)
        if any(present) and not all(present):
            raise ExternalCapabilityContractError("unexpected provider binding is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def request_digest(self) -> str:
        return canonical_external_digest(self.to_dict())

    @property
    def provider_bound(self) -> bool:
        return bool(self.provider_decision_ref)


@dataclass(frozen=True, slots=True)
class ExternalCapabilityResultV1:
    schema_version: str
    capability_id: str
    capability_version: str
    request_digest: str
    input_set_digest: str
    source_snapshot_digest: str
    schema_digest: str
    result: Mapping[str, Any]
    result_digest: str
    evidence_ref: str
    provider_decision_ref: str = ""
    actual_provider_id: str = ""
    actual_model_id: str = ""
    actual_route_ref: str = ""
    confidence: float | None = None
    usage: Mapping[str, Any] | None = None
    latency_ms: int = 0
    error: ExternalCapabilityError | None = None
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != RESULT_SCHEMA_V1:
            raise ExternalCapabilityContractError("unsupported result schema")
        for field in ("capability_id", "capability_version", "evidence_ref"):
            _require_text(getattr(self, field), field)
        for field in (
            "request_digest", "input_set_digest", "source_snapshot_digest",
            "schema_digest", "result_digest",
        ):
            _require_digest(getattr(self, field), field)
        if not isinstance(self.result, Mapping):
            raise ExternalCapabilityContractError("external advisory result must be a mapping")
        _reject_external_control_fields(self.result)
        if self.latency_ms < 0:
            raise ExternalCapabilityContractError("latency_ms cannot be negative")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ExternalCapabilityContractError("confidence must be between zero and one")
        if self.non_authoritative is not True:
            raise ExternalCapabilityContractError("external advisory result must be non-authoritative")
        actual_binding = (
            self.provider_decision_ref, self.actual_provider_id,
            self.actual_model_id, self.actual_route_ref,
        )
        present = tuple(bool(str(value).strip()) for value in actual_binding)
        if any(present) and not all(present):
            raise ExternalCapabilityContractError("result provider binding is incomplete")

    @classmethod
    def from_external_payload(
        cls,
        *,
        request: ExternalCapabilityRequestV1,
        external_payload: Mapping[str, Any],
        evidence_ref: str,
        actual_provider_id: str = "",
        actual_model_id: str = "",
        actual_route_ref: str = "",
        confidence: float | None = None,
        usage: Mapping[str, Any] | None = None,
        latency_ms: int = 0,
        error: ExternalCapabilityError | None = None,
    ) -> "ExternalCapabilityResultV1":
        if not isinstance(external_payload, Mapping):
            raise ExternalCapabilityContractError("external payload must be a mapping")
        _reject_external_control_fields(external_payload)
        result = dict(external_payload)
        return cls(
            schema_version=RESULT_SCHEMA_V1,
            capability_id=request.capability_id,
            capability_version=request.capability_version,
            request_digest=request.request_digest,
            input_set_digest=request.input_set_digest,
            source_snapshot_digest=request.source_snapshot_digest,
            schema_digest=request.schema_digest,
            result=result,
            result_digest=canonical_external_digest(result),
            evidence_ref=evidence_ref,
            provider_decision_ref=request.provider_decision_ref,
            actual_provider_id=actual_provider_id,
            actual_model_id=actual_model_id,
            actual_route_ref=actual_route_ref,
            confidence=confidence,
            usage=dict(usage) if usage is not None else None,
            latency_ms=latency_ms,
            error=error,
            non_authoritative=True,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result"] = dict(self.result)
        payload["usage"] = dict(self.usage) if self.usage is not None else None
        payload["error"] = self.error.to_dict() if self.error is not None else None
        payload["non_authoritative"] = True
        return payload


def validate_advisory_freshness(
    request: ExternalCapabilityRequestV1,
    result: ExternalCapabilityResultV1,
) -> bool:
    if (
        result.schema_version != RESULT_SCHEMA_V1
        or result.capability_id != request.capability_id
        or result.capability_version != request.capability_version
        or result.request_digest != request.request_digest
        or result.input_set_digest != request.input_set_digest
        or result.source_snapshot_digest != request.source_snapshot_digest
        or result.schema_digest != request.schema_digest
        or result.provider_decision_ref != request.provider_decision_ref
    ):
        return False
    if request.provider_bound:
        return (
            result.actual_provider_id == request.provider_id
            and result.actual_model_id == request.model_id
            and result.actual_route_ref == request.route_ref
        )
    return not any((result.actual_provider_id, result.actual_model_id, result.actual_route_ref))
