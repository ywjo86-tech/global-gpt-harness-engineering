from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Sequence


_EXECUTION_AUTHORITIES = frozenset({
    "READ_ONLY",
    "STATE_CHANGING",
})

_DISPOSITIONS = frozenset({
    "DIRECT_READ_ALLOWED",
    "GATEWAY_REQUIRED",
    "BLOCKED",
})


@dataclass(frozen=True, slots=True)
class ExternalCapabilityInvocationDecisionV1:
    disposition: str
    capability_id: str
    required_effect_boundary: str
    reason: str

    def __post_init__(self) -> None:
        if self.disposition not in _DISPOSITIONS:
            raise ValueError("unsupported external capability disposition")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


def decide_external_capability_invocation(
    *,
    execution_authority: str,
    lifecycle_state: str,
    capability_id: str,
    approved_capabilities: Sequence[str],
) -> ExternalCapabilityInvocationDecisionV1:
    """Return policy only; never return or invoke an executor."""

    if (
        not isinstance(capability_id, str)
        or not capability_id
        or not isinstance(lifecycle_state, str)
        or not lifecycle_state
    ):
        return ExternalCapabilityInvocationDecisionV1(
            disposition="BLOCKED",
            capability_id=str(capability_id or ""),
            required_effect_boundary="",
            reason="external capability identity or lifecycle state is invalid",
        )

    if execution_authority not in _EXECUTION_AUTHORITIES:
        return ExternalCapabilityInvocationDecisionV1(
            disposition="BLOCKED",
            capability_id=capability_id,
            required_effect_boundary="",
            reason="execution authority is unsupported",
        )

    if lifecycle_state != "ACTIVE":
        return ExternalCapabilityInvocationDecisionV1(
            disposition="BLOCKED",
            capability_id=capability_id,
            required_effect_boundary="",
            reason="capability lifecycle is not active",
        )

    normalized = tuple(approved_capabilities)

    if (
        len(set(normalized)) != len(normalized)
        or any(not isinstance(item, str) or not item for item in normalized)
    ):
        return ExternalCapabilityInvocationDecisionV1(
            disposition="BLOCKED",
            capability_id=capability_id,
            required_effect_boundary="",
            reason="approved capability scope is malformed",
        )

    if capability_id not in normalized:
        return ExternalCapabilityInvocationDecisionV1(
            disposition="BLOCKED",
            capability_id=capability_id,
            required_effect_boundary="",
            reason="capability is outside approved scope",
        )

    if execution_authority == "STATE_CHANGING":
        return ExternalCapabilityInvocationDecisionV1(
            disposition="GATEWAY_REQUIRED",
            capability_id=capability_id,
            required_effect_boundary="PRODUCTION_EXECUTION_GATEWAY",
            reason="state-changing effects require the governed execution boundary",
        )

    return ExternalCapabilityInvocationDecisionV1(
        disposition="DIRECT_READ_ALLOWED",
        capability_id=capability_id,
        required_effect_boundary="",
        reason="approved active capability is limited to read-only invocation",
    )
