"""Consumer-safe dual-domain observability references for AI Office."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

ACTION_OBSERVATION_SCHEMA_V1 = "ai-office.action-runtime-observation-ref.v1"
PROVIDER_OBSERVATION_SCHEMA_V1 = "ai-office.provider-runtime-observation-ref.v1"
CORRELATED_OBSERVATION_SCHEMA_V1 = "ai-office.correlated-observation.v1"
ACTION_SOURCE_DOMAIN = "FULL_MCP_ACTION_RUNTIME"
PROVIDER_SOURCE_DOMAIN = "MPRF_PROVIDER_RUNTIME"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
ACTION_STATES = frozenset({"RECEIVED", "AUTHENTICATED", "AUTHORIZED", "EFFECT_INTENT", "RUNNING",
                           "EFFECT_RECEIPT", "RESULT_SEALED", "VALIDATED", "BLOCKED", "FAILED",
                           "CANCELLED", "RECOVERY_REQUIRED", "RESTORED_PENDING_VALIDATION", "COMPLETED"})
PROVIDER_EVENTS = frozenset({"PROVIDER", "MODEL", "HEALTH", "QUOTA", "TRANSITION", "FAILOVER", "RETRY", "EXCLUSION"})


class PublicObservabilityContractError(ValueError):
    pass


def canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PublicObservabilityContractError(f"{label} is invalid")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise PublicObservabilityContractError(f"{label} is invalid")
    return value


def _source_ref(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024 or ".." in value or any(ord(ch) < 32 for ch in value):
        raise PublicObservabilityContractError("source_ref is invalid")
    return value


def _identity(project_id: str, project_run_id: str, task_execution_id: str,
              correlation_id: str, operation_request_id: str) -> None:
    for value, label in ((project_id, "project_id"), (project_run_id, "project_run_id"),
                         (task_execution_id, "task_execution_id"), (correlation_id, "correlation_id"),
                         (operation_request_id, "operation_request_id")):
        _safe_id(value, label)


@dataclass(frozen=True, slots=True)
class ActionRuntimeObservationRefV1:
    schema_version: str
    project_id: str
    project_run_id: str
    task_execution_id: str
    correlation_id: str
    operation_request_id: str
    source_domain: str
    source_ref: str
    event_digest: str
    sequence: int
    bounded_state: str

    def __post_init__(self) -> None:
        if self.schema_version != ACTION_OBSERVATION_SCHEMA_V1 or self.source_domain != ACTION_SOURCE_DOMAIN:
            raise PublicObservabilityContractError("action observation schema/source domain mismatch")
        _identity(self.project_id, self.project_run_id, self.task_execution_id, self.correlation_id, self.operation_request_id)
        _source_ref(self.source_ref); _sha(self.event_digest, "event_digest")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise PublicObservabilityContractError("action observation sequence is invalid")
        if self.bounded_state not in ACTION_STATES:
            raise PublicObservabilityContractError("action bounded_state is invalid")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderRuntimeObservationRefV1:
    schema_version: str
    project_id: str
    project_run_id: str
    task_execution_id: str
    correlation_id: str
    operation_request_id: str
    source_domain: str
    source_ref: str
    event_digest: str
    sequence: int
    bounded_event_type: str

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_OBSERVATION_SCHEMA_V1 or self.source_domain != PROVIDER_SOURCE_DOMAIN:
            raise PublicObservabilityContractError("provider observation schema/source domain mismatch")
        _identity(self.project_id, self.project_run_id, self.task_execution_id, self.correlation_id, self.operation_request_id)
        _source_ref(self.source_ref); _sha(self.event_digest, "event_digest")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise PublicObservabilityContractError("provider observation sequence is invalid")
        if self.bounded_event_type not in PROVIDER_EVENTS:
            raise PublicObservabilityContractError("provider bounded_event_type is invalid")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class CorrelatedObservationV1:
    schema_version: str
    project_id: str
    project_run_id: str
    task_execution_id: str
    correlation_id: str
    operation_request_id: str
    action_observations: tuple[ActionRuntimeObservationRefV1, ...] = ()
    provider_observations: tuple[ProviderRuntimeObservationRefV1, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != CORRELATED_OBSERVATION_SCHEMA_V1:
            raise PublicObservabilityContractError("unsupported correlated observation schema")
        _identity(self.project_id, self.project_run_id, self.task_execution_id, self.correlation_id, self.operation_request_id)
        if not self.action_observations and not self.provider_observations:
            raise PublicObservabilityContractError("correlation requires at least one source observation")
        refs: set[tuple[str, str, int]] = set()
        for item in (*self.action_observations, *self.provider_observations):
            if (item.project_id, item.project_run_id, item.task_execution_id, item.correlation_id, item.operation_request_id) != (
                self.project_id, self.project_run_id, self.task_execution_id, self.correlation_id, self.operation_request_id
            ):
                raise PublicObservabilityContractError("cross-domain observation identity mismatch")
            key = (item.source_domain, item.source_ref, item.sequence)
            if key in refs:
                raise PublicObservabilityContractError("duplicate source observation ref")
            refs.add(key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "project_id": self.project_id,
            "project_run_id": self.project_run_id, "task_execution_id": self.task_execution_id,
            "correlation_id": self.correlation_id, "operation_request_id": self.operation_request_id,
            "action_observations": [item.to_dict() for item in self.action_observations],
            "provider_observations": [item.to_dict() for item in self.provider_observations],
        }

    @property
    def correlation_digest(self) -> str: return canonical_digest(self.to_dict())
