"""Immutable MPRF lifecycle and eligibility facts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import MPRFContractError, validate_provider_id

LIFECYCLE_FACT_SCHEMA_V1 = "mprf.lifecycle-fact.v1"
LIFECYCLE_STATE_SCHEMA_V1 = "mprf.lifecycle-state.v1"

HEALTHY = "HEALTHY"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
HEALTH_STATES_V1 = frozenset({HEALTHY, STALE, UNKNOWN})

QUOTA_AVAILABLE = "AVAILABLE"
QUOTA_EXHAUSTED = "EXHAUSTED"
QUOTA_UNKNOWN = "UNKNOWN"
QUOTA_STATES_V1 = frozenset({QUOTA_AVAILABLE, QUOTA_EXHAUSTED, QUOTA_UNKNOWN})

RATE_AVAILABLE = "AVAILABLE"
RATE_LIMITED = "LIMITED"
RATE_UNKNOWN = "UNKNOWN"
RATE_STATES_V1 = frozenset({RATE_AVAILABLE, RATE_LIMITED, RATE_UNKNOWN})

LIFECYCLE_OK = "LIFECYCLE_OK"
STALE_LIFECYCLE_VERSION = "STALE_LIFECYCLE_VERSION"
STALE_HEALTH = "STALE_HEALTH"
UNKNOWN_HEALTH = "UNKNOWN_HEALTH"
QUOTA_EXHAUSTED_REASON = "QUOTA_EXHAUSTED"
UNKNOWN_QUOTA = "UNKNOWN_QUOTA"
RATE_LIMITED_REASON = "RATE_LIMITED"
UNKNOWN_RATE = "UNKNOWN_RATE"
CAPABILITY_MISSING = "CAPABILITY_MISSING"


def _require_positive_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MPRFContractError(f"{field} must be a positive integer")


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MPRFContractError(f"{field} must be a non-empty string")


def _normalize_capabilities(values: Iterable[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise MPRFContractError("capabilities must contain non-empty strings")
        normalized.add(value.strip())
    return frozenset(normalized)

@dataclass(frozen=True, slots=True)
class LifecycleFactV1:
    schema_version: str
    provider_id: str
    model_ref: str
    registry_version: int
    lifecycle_version: int
    health_state: str
    quota_state: str
    rate_state: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if self.schema_version != LIFECYCLE_FACT_SCHEMA_V1:
            raise MPRFContractError("unsupported lifecycle fact schema")
        validate_provider_id(self.provider_id)
        _require_text(self.model_ref, "model_ref")
        _require_positive_int(self.registry_version, "registry_version")
        _require_positive_int(self.lifecycle_version, "lifecycle_version")
        if self.health_state not in HEALTH_STATES_V1:
            raise MPRFContractError("unknown health state")
        if self.quota_state not in QUOTA_STATES_V1:
            raise MPRFContractError("unknown quota state")
        if self.rate_state not in RATE_STATES_V1:
            raise MPRFContractError("unknown rate state")
        object.__setattr__(self, "capabilities", _normalize_capabilities(self.capabilities))


def evaluate_lifecycle(
    fact: LifecycleFactV1,
    required_capabilities: Iterable[str] = (),
    *,
    expected_registry_version: int | None = None,
    minimum_lifecycle_version: int | None = None,
) -> tuple[bool, str]:
    if not isinstance(fact, LifecycleFactV1):
        raise MPRFContractError("lifecycle fact is required")
    required = _normalize_capabilities(required_capabilities)
    if expected_registry_version is not None:
        _require_positive_int(expected_registry_version, "expected_registry_version")
        if fact.registry_version != expected_registry_version:
            return False, STALE_LIFECYCLE_VERSION
    if minimum_lifecycle_version is not None:
        _require_positive_int(minimum_lifecycle_version, "minimum_lifecycle_version")
        if fact.lifecycle_version < minimum_lifecycle_version:
            return False, STALE_LIFECYCLE_VERSION
    if fact.health_state == STALE:
        return False, STALE_HEALTH
    if fact.health_state != HEALTHY:
        return False, UNKNOWN_HEALTH
    if fact.quota_state == QUOTA_EXHAUSTED:
        return False, QUOTA_EXHAUSTED_REASON
    if fact.quota_state != QUOTA_AVAILABLE:
        return False, UNKNOWN_QUOTA
    if fact.rate_state == RATE_LIMITED:
        return False, RATE_LIMITED_REASON
    if fact.rate_state != RATE_AVAILABLE:
        return False, UNKNOWN_RATE
    if not required.issubset(fact.capabilities):
        return False, CAPABILITY_MISSING
    return True, LIFECYCLE_OK


@dataclass(frozen=True, slots=True)
class LifecycleStateV1:
    schema_version: str
    state_version: int
    facts: tuple[LifecycleFactV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != LIFECYCLE_STATE_SCHEMA_V1:
            raise MPRFContractError("unsupported lifecycle state schema")
        _require_positive_int(self.state_version, "state_version")
        object.__setattr__(self, "facts", tuple(self.facts))
        identities = [(item.provider_id, item.model_ref) for item in self.facts]
        if len(identities) != len(set(identities)):
            raise MPRFContractError("duplicate lifecycle identity")

    def fact_for(self, provider_id: str, model_ref: str) -> LifecycleFactV1 | None:
        for item in self.facts:
            if item.provider_id == provider_id and item.model_ref == model_ref:
                return item
        return None

    def transition(self, next_fact: LifecycleFactV1) -> "LifecycleStateV1":
        if not isinstance(next_fact, LifecycleFactV1):
            raise MPRFContractError("next lifecycle fact is required")
        current = self.fact_for(next_fact.provider_id, next_fact.model_ref)
        if current is None:
            if next_fact.lifecycle_version != 1:
                raise MPRFContractError("new lifecycle identity must start at version 1")
        else:
            if next_fact.registry_version < current.registry_version:
                raise MPRFContractError("registry version cannot move backwards")
            if next_fact.registry_version == current.registry_version:
                if next_fact.lifecycle_version != current.lifecycle_version + 1:
                    raise MPRFContractError("lifecycle version must advance exactly once")
            elif next_fact.lifecycle_version != 1:
                raise MPRFContractError("new registry binding must reset lifecycle version to 1")

        facts = [item for item in self.facts
                 if (item.provider_id, item.model_ref) != (next_fact.provider_id, next_fact.model_ref)]
        facts.append(next_fact)
        facts.sort(key=lambda item: (item.provider_id, item.model_ref))
        return LifecycleStateV1(
            LIFECYCLE_STATE_SCHEMA_V1,
            self.state_version + 1,
            tuple(facts),
        )
