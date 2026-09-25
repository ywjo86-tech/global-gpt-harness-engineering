"""Provider-bound, non-authoritative Jev typed-judgment adapter.

The adapter accepts an already-issued Router request/decision pair, verifies the
immutable provider/model binding, invokes one injected transport once, and
normalizes only advisory evidence.  It owns no selection or effect authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Callable, Mapping

from .external_advisory_contract import (
    ExternalCapabilityError,
    ExternalCapabilityRequestV1,
    ExternalCapabilityResultV1,
)
from .provider_router import RouterDecisionV2, RouterRequestV2

JEV_CAPABILITY_ID = "external.jev.typed_judgment.v1"
JEV_CAPABILITY_VERSION = "typesafe-api-0.2.0"


class JevProviderBoundAdapterError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class JevRateLimitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JevTransportResponseV1:
    result: Mapping[str, Any]
    actual_provider_ref: str
    actual_model_ref: str
    actual_route_ref: str
    confidence: float | None
    usage: Mapping[str, Any] | None
    latency_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.result, Mapping):
            raise JevProviderBoundAdapterError(
                "CAPABILITY_RESULT_INVALID", "Jev transport result must be a mapping"
            )
        for field in ("actual_provider_ref", "actual_model_ref", "actual_route_ref"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise JevProviderBoundAdapterError(
                    "CAPABILITY_RESULT_INVALID", f"Jev transport {field} is missing"
                )
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise JevProviderBoundAdapterError(
                "CAPABILITY_RESULT_INVALID", "Jev transport confidence is invalid"
            )
        if self.usage is not None and not isinstance(self.usage, Mapping):
            raise JevProviderBoundAdapterError(
                "CAPABILITY_RESULT_INVALID", "Jev transport usage is invalid"
            )
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int) or self.latency_ms < 0:
            raise JevProviderBoundAdapterError(
                "CAPABILITY_RESULT_INVALID", "Jev transport latency is invalid"
            )


JevTransport = Callable[[ExternalCapabilityRequestV1, int], JevTransportResponseV1]


def jev_route_ref(decision: RouterDecisionV2) -> str:
    if not decision.eligible or not decision.provider_ref or not decision.model_ref:
        raise JevProviderBoundAdapterError(
            "CAPABILITY_PROVIDER_BINDING_MISMATCH",
            "eligible Router provider/model binding is required",
        )
    material = (
        f"{decision.decision_digest}|{decision.provider_ref}|{decision.model_ref}"
    ).encode("utf-8")
    return "route:" + hashlib.sha256(material).hexdigest()


def _binding_error(message: str) -> JevProviderBoundAdapterError:
    return JevProviderBoundAdapterError("CAPABILITY_PROVIDER_BINDING_MISMATCH", message)


class JevProviderBoundAdapter:
    """Validate one immutable Router binding and perform one advisory call."""

    def __init__(self, transport: JevTransport) -> None:
        if not callable(transport):
            raise JevProviderBoundAdapterError(
                "CAPABILITY_UNAVAILABLE", "Jev transport is unavailable"
            )
        self._transport = transport

    def _validate_binding(
        self,
        router_request: RouterRequestV2,
        router_decision: RouterDecisionV2,
        capability_request: ExternalCapabilityRequestV1,
    ) -> None:
        if router_decision.stage == "ACTION" or router_request.stage == "ACTION":
            raise JevProviderBoundAdapterError(
                "CAPABILITY_SIDE_EFFECT_DENIED",
                "Jev advisory cannot execute for ACTION stage",
            )
        if router_request.stage not in {"PREPARE", "VERIFY", "REVIEW"}:
            raise _binding_error("Router stage is not eligible for Jev advisory")
        if not router_decision.eligible:
            raise _binding_error("eligible Router decision is required")
        if (
            router_decision.request_digest != router_request.request_digest
            or router_decision.stage != router_request.stage
        ):
            raise _binding_error("Router request/decision binding mismatch")
        if capability_request.capability_id != JEV_CAPABILITY_ID:
            raise _binding_error("Jev capability identity mismatch")
        if capability_request.capability_version != JEV_CAPABILITY_VERSION:
            raise JevProviderBoundAdapterError(
                "CAPABILITY_VERSION_UNAPPROVED", "Jev capability version is not approved"
            )
        if (
            capability_request.project_id != router_request.project_id
            or capability_request.project_run_id != router_request.run_id
            or capability_request.task_id != router_request.task_id
            or capability_request.task_execution_id != router_request.task_execution_id
        ):
            raise _binding_error("Jev lifecycle identity mismatch")
        if not capability_request.provider_bound:
            raise _binding_error("Jev request lacks provider binding")
        if (
            capability_request.provider_decision_ref != router_decision.decision_digest
            or capability_request.provider_id != router_decision.provider_ref
            or capability_request.model_id != router_decision.model_ref
            or capability_request.route_ref != jev_route_ref(router_decision)
        ):
            raise _binding_error("Jev provider/model/decision binding mismatch")

    def _error_result(
        self,
        capability_request: ExternalCapabilityRequestV1,
        *,
        evidence_ref: str,
        code: str,
        message: str,
    ) -> ExternalCapabilityResultV1:
        return ExternalCapabilityResultV1.from_external_payload(
            request=capability_request,
            external_payload={},
            evidence_ref=evidence_ref,
            actual_provider_id=capability_request.provider_id,
            actual_model_id=capability_request.model_id,
            actual_route_ref=capability_request.route_ref,
            error=ExternalCapabilityError(code=code, message=message, retryable=False),
        )

    def execute(
        self,
        router_request: RouterRequestV2,
        router_decision: RouterDecisionV2,
        capability_request: ExternalCapabilityRequestV1,
        *,
        evidence_ref: str,
    ) -> ExternalCapabilityResultV1:
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise JevProviderBoundAdapterError(
                "CAPABILITY_RESULT_INVALID", "Jev evidence reference is required"
            )
        self._validate_binding(router_request, router_decision, capability_request)
        try:
            response = self._transport(capability_request, capability_request.deadline_ms)
        except TimeoutError:
            return self._error_result(
                capability_request,
                evidence_ref=evidence_ref,
                code="CAPABILITY_TIMEOUT",
                message="Jev advisory timed out",
            )
        except JevRateLimitError:
            return self._error_result(
                capability_request,
                evidence_ref=evidence_ref,
                code="CAPABILITY_RATE_LIMITED",
                message="Jev advisory was rate limited",
            )
        except ConnectionError:
            return self._error_result(
                capability_request,
                evidence_ref=evidence_ref,
                code="CAPABILITY_UNAVAILABLE",
                message="Jev advisory transport is unavailable",
            )
        if not isinstance(response, JevTransportResponseV1):
            raise JevProviderBoundAdapterError(
                "CAPABILITY_RESULT_INVALID", "Jev transport returned an invalid response envelope"
            )
        if (
            response.actual_provider_ref != capability_request.provider_id
            or response.actual_model_ref != capability_request.model_id
            or response.actual_route_ref != capability_request.route_ref
        ):
            raise _binding_error("Jev transport identity differs from Router binding")
        return ExternalCapabilityResultV1.from_external_payload(
            request=capability_request,
            external_payload=dict(response.result),
            evidence_ref=evidence_ref,
            actual_provider_id=response.actual_provider_ref,
            actual_model_id=response.actual_model_ref,
            actual_route_ref=response.actual_route_ref,
            confidence=response.confidence,
            usage=dict(response.usage) if response.usage is not None else None,
            latency_ms=response.latency_ms,
        )


def build_jev_read_runner(transport: JevTransport):
    adapter = JevProviderBoundAdapter(transport)

    def run(*, router_request: RouterRequestV2, router_decision: RouterDecisionV2,
            capability_request: ExternalCapabilityRequestV1, evidence_ref: str):
        return adapter.execute(
            router_request,
            router_decision,
            capability_request,
            evidence_ref=evidence_ref,
        )

    return run
