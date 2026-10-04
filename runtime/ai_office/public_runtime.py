"""Provider-neutral AI Office public runtime facade.

The facade is intentionally composition-only. Authority-owning handlers are
injected by the runtime composition root; this module does not construct or
select a provider, execution backend, approval authority, or effect owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


PUBLIC_RUNTIME_STATUSES = frozenset(
    {
        "INVALID_CONTRACT",
        "CAPABILITY_UNAVAILABLE",
        "APPROVAL_REQUIRED",
        "POLICY_BLOCKED",
        "EXECUTION_UNAVAILABLE",
        "PROVIDER_RUNTIME_UNAVAILABLE",
        "PARTIAL_RESULT",
        "RECOVERY_REQUIRED",
        "COMPLETED",
    }
)
_FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {"provider", "provider_ref", "model", "model_ref", "backend", "backend_ref"}
)


class AIOfficePublicRuntimeError(ValueError):
    pass


PublicHandler = Callable[[Any], Mapping[str, Any]]
PublicReadHandler = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class AIOfficePublicRuntimeHandlersV1:
    submit_work: PublicHandler
    request_capability: PublicHandler
    request_approval: PublicHandler
    submit_execution_intent: PublicHandler
    read_effect_evidence: PublicReadHandler
    read_status: PublicReadHandler
    transport_business_event: PublicHandler

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if not callable(getattr(self, name)):
                raise AIOfficePublicRuntimeError(
                    f"public runtime handler is not callable: {name}"
                )


class AIOfficePublicRuntimeFacade:
    """Thin public facade over existing authority-owning runtime handlers."""

    def __init__(self, handlers: AIOfficePublicRuntimeHandlersV1) -> None:
        if not isinstance(handlers, AIOfficePublicRuntimeHandlersV1):
            raise AIOfficePublicRuntimeError(
                "AIOfficePublicRuntimeHandlersV1 is required"
            )
        self._handlers = handlers

    @staticmethod
    def _mapping(operation: str, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise AIOfficePublicRuntimeError(
                f"{operation} returned a non-mapping public result"
            )
        payload = dict(value)
        forbidden = sorted(_FORBIDDEN_AUTHORITY_FIELDS.intersection(payload))
        if forbidden:
            raise AIOfficePublicRuntimeError(
                f"{operation} leaked authority-selection fields: {forbidden}"
            )
        return payload

    @classmethod
    def _outcome(cls, operation: str, value: object) -> dict[str, Any]:
        payload = cls._mapping(operation, value)
        status = payload.get("status")
        if status not in PUBLIC_RUNTIME_STATUSES:
            raise AIOfficePublicRuntimeError(
                f"{operation} returned unsupported public status"
            )
        reasons = payload.get("reason_codes", ())
        if not isinstance(reasons, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in reasons
        ):
            raise AIOfficePublicRuntimeError(
                f"{operation} returned invalid reason_codes"
            )
        payload["reason_codes"] = list(reasons)
        return payload

    def submit_work(self, request: Any) -> dict[str, Any]:
        return self._outcome(
            "submit_work",
            self._handlers.submit_work(request),
        )

    def request_capability(self, request: Any) -> dict[str, Any]:
        return self._outcome(
            "request_capability",
            self._handlers.request_capability(request),
        )

    def request_approval(self, request: Any) -> dict[str, Any]:
        return self._outcome(
            "request_approval",
            self._handlers.request_approval(request),
        )

    def submit_execution_intent(self, intent: Any) -> dict[str, Any]:
        return self._outcome(
            "submit_execution_intent",
            self._handlers.submit_execution_intent(intent),
        )

    def read_effect_evidence(self, intent_id: str) -> dict[str, Any]:
        if not isinstance(intent_id, str) or not intent_id:
            raise AIOfficePublicRuntimeError("intent_id is required")
        payload = self._mapping(
            "read_effect_evidence",
            self._handlers.read_effect_evidence(intent_id),
        )
        observed = payload.get("intent_id")
        if observed is not None and observed != intent_id:
            raise AIOfficePublicRuntimeError(
                "read_effect_evidence identity mismatch"
            )
        return payload

    def read_status(self, workflow_ref: str) -> dict[str, Any]:
        if not isinstance(workflow_ref, str) or not workflow_ref:
            raise AIOfficePublicRuntimeError("workflow_ref is required")
        payload = self._mapping(
            "read_status",
            self._handlers.read_status(workflow_ref),
        )
        observed = payload.get("workflow_ref")
        if observed is not None and observed != workflow_ref:
            raise AIOfficePublicRuntimeError("read_status identity mismatch")
        return payload

    def transport_business_event(self, envelope: Any) -> dict[str, Any]:
        return self._outcome(
            "transport_business_event",
            self._handlers.transport_business_event(envelope),
        )


def compose_public_runtime_facade(
    handlers: AIOfficePublicRuntimeHandlersV1,
) -> AIOfficePublicRuntimeFacade:
    """Compose the public facade without creating any underlying authority."""

    return AIOfficePublicRuntimeFacade(handlers)
