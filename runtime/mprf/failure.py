"""Closed MPRF failure taxonomy and failover eligibility facts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import MPRFContractError

FAILURE_CLASS_SCHEMA_V1 = "mprf.failure-class.v1"
FAILOVER_PREREQUISITES_SCHEMA_V1 = "mprf.failover-prerequisites.v1"
FAILURE_DISPOSITION_SCHEMA_V1 = "mprf.failure-disposition.v1"
FAILOVER_POLICY_VERSION_V1 = "MPRF_FAILOVER_V1"
EFFECT_STATE_UNKNOWN = "UNKNOWN"
EFFECT_STATE_NO_EFFECT = "CONFIRMED_NO_EFFECT"
EFFECT_STATE_EFFECT_CONFIRMED = "CONFIRMED_EFFECT"
EFFECT_STATES_V1 = frozenset({EFFECT_STATE_UNKNOWN, EFFECT_STATE_NO_EFFECT, EFFECT_STATE_EFFECT_CONFIRMED})


class FailureClassV1(str, Enum):
    TASK_FAILURE = "TASK_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    AUTH_FAILURE = "AUTH_FAILURE"
    RATE_LIMIT = "RATE_LIMIT"
    QUOTA_EXHAUSTION = "QUOTA_EXHAUSTION"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    POLICY_REJECTION = "POLICY_REJECTION"
    CHECKPOINT_FAILURE = "CHECKPOINT_FAILURE"
    EXECUTION_BACKEND_FAILURE = "EXECUTION_BACKEND_FAILURE"
    ACTION_SIDE_EFFECT_AMBIGUOUS = "ACTION_SIDE_EFFECT_AMBIGUOUS"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


ELIGIBLE_BASE_CLASSES_V1 = frozenset({
    FailureClassV1.MODEL_FAILURE,
    FailureClassV1.PROVIDER_FAILURE,
    FailureClassV1.RATE_LIMIT,
    FailureClassV1.QUOTA_EXHAUSTION,
    FailureClassV1.NETWORK_FAILURE,
})

FAILURE_DISPOSITIONS_V1 = {
    FailureClassV1.TASK_FAILURE: "TASK_FAILURE_RECLASSIFICATION_REQUIRED",
    FailureClassV1.MODEL_FAILURE: "ELIGIBLE_AFTER_RECOVERY_CHECKS",
    FailureClassV1.PROVIDER_FAILURE: "ELIGIBLE_AFTER_RECOVERY_CHECKS",
    FailureClassV1.AUTH_FAILURE: "AUTH_FAILURE_REROUTE_PROHIBITED",
    FailureClassV1.RATE_LIMIT: "ELIGIBLE_AFTER_RECOVERY_CHECKS",
    FailureClassV1.QUOTA_EXHAUSTION: "ELIGIBLE_AFTER_RECOVERY_CHECKS",
    FailureClassV1.NETWORK_FAILURE: "NETWORK_SAFE_POLICY_REQUIRED",
    FailureClassV1.INVALID_RESPONSE: "INVALID_RESPONSE_REROUTE_PROHIBITED",
    FailureClassV1.POLICY_REJECTION: "POLICY_REJECTION_REROUTE_PROHIBITED",
    FailureClassV1.CHECKPOINT_FAILURE: "CHECKPOINT_RECOVERY_REQUIRED",
    FailureClassV1.EXECUTION_BACKEND_FAILURE: "EXECUTION_BACKEND_REROUTE_PROHIBITED",
    FailureClassV1.ACTION_SIDE_EFFECT_AMBIGUOUS: "EFFECT_RECONCILIATION_REQUIRED",
    FailureClassV1.RECOVERY_REQUIRED: "RECOVERY_REQUIRED_REROUTE_PROHIBITED",
    FailureClassV1.UNKNOWN_FAILURE: "UNKNOWN_FAILURE_CLASSIFICATION_REQUIRED",
}


def failure_class(value: FailureClassV1 | str) -> FailureClassV1:
    if isinstance(value, FailureClassV1):
        return value
    try:
        return FailureClassV1(value)
    except (TypeError, ValueError) as exc:
        raise MPRFContractError("unknown FailureClass.v1 value") from exc


@dataclass(frozen=True, slots=True)
class FailoverPrerequisitesV1:
    schema_version: str
    checkpoint_integrity_ref: str
    artifact_integrity_ref: str
    effect_reconciliation_ref: str
    authorization_validation_ref: str
    policy_validation_ref: str
    network_safe_policy_evidence_ref: str = ""
    effect_state: str = EFFECT_STATE_UNKNOWN

    def __post_init__(self) -> None:
        if self.schema_version != FAILOVER_PREREQUISITES_SCHEMA_V1:
            raise MPRFContractError("unsupported failover prerequisite schema")
        for name in ("checkpoint_integrity_ref", "artifact_integrity_ref", "effect_reconciliation_ref",
                     "authorization_validation_ref", "policy_validation_ref"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise MPRFContractError(f"{name} must be a string")
        if not isinstance(self.network_safe_policy_evidence_ref, str):
            raise MPRFContractError("network_safe_policy_evidence_ref must be a string")
        if self.effect_state not in EFFECT_STATES_V1:
            raise MPRFContractError("unknown effect reconciliation state")

    @property
    def recovery_checks_complete(self) -> bool:
        return all((self.checkpoint_integrity_ref, self.artifact_integrity_ref,
                    self.effect_reconciliation_ref, self.authorization_validation_ref,
                    self.policy_validation_ref))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class FailureDispositionV1:
    schema_version: str
    failure_class: FailureClassV1
    reroute_eligible: bool
    reason_code: str
    recovery_checks_complete: bool

    def __post_init__(self) -> None:
        if self.schema_version != FAILURE_DISPOSITION_SCHEMA_V1:
            raise MPRFContractError("unsupported failure disposition schema")
        if self.failure_class not in FAILURE_DISPOSITIONS_V1:
            raise MPRFContractError("failure class has no disposition")
        if not isinstance(self.reroute_eligible, bool) or not isinstance(self.recovery_checks_complete, bool):
            raise MPRFContractError("failure disposition booleans are invalid")
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise MPRFContractError("failure disposition reason is missing")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "failure_class": self.failure_class.value,
                "reroute_eligible": self.reroute_eligible, "reason_code": self.reason_code,
                "recovery_checks_complete": self.recovery_checks_complete}


def evaluate_failover(value: FailureClassV1 | str, prerequisites: FailoverPrerequisitesV1,
                      *, permission_related_auth: bool = False) -> FailureDispositionV1:
    fc = failure_class(value)
    if not isinstance(prerequisites, FailoverPrerequisitesV1):
        raise MPRFContractError("failover prerequisites contract is required")
    complete = prerequisites.recovery_checks_complete
    if fc is FailureClassV1.INVALID_RESPONSE:
        if not complete:
            return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, False,
                                        "RECOVERY_PREREQUISITES_INCOMPLETE", False)
        if prerequisites.effect_state != EFFECT_STATE_NO_EFFECT:
            return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, False,
                                        "INVALID_RESPONSE_NO_EFFECT_REQUIRED", True)
        return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, True,
                                    "REROUTE_REQUEST_ELIGIBLE", True)
    if fc not in ELIGIBLE_BASE_CLASSES_V1:
        reason = FAILURE_DISPOSITIONS_V1[fc]
        if fc is FailureClassV1.AUTH_FAILURE and permission_related_auth:
            reason = "PERMISSION_AUTH_FAILURE_REROUTE_PROHIBITED"
        return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, False, reason, complete)
    if not complete:
        return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, False,
                                    "RECOVERY_PREREQUISITES_INCOMPLETE", False)
    if fc is FailureClassV1.NETWORK_FAILURE and not prerequisites.network_safe_policy_evidence_ref:
        return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, False,
                                    "NETWORK_SAFE_POLICY_REQUIRED", True)
    return FailureDispositionV1(FAILURE_DISPOSITION_SCHEMA_V1, fc, True,
                                "REROUTE_REQUEST_ELIGIBLE", True)
