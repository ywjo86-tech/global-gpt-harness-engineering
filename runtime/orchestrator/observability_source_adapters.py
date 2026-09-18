"""Read-only source adapters for Full MCP and MPRF observability domains."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from runtime.mprf.observability import EVENT_SCHEMA_V1, ProviderRuntimeEventV1
from .public_observability_contract import (
    ACTION_OBSERVATION_SCHEMA_V1, ACTION_SOURCE_DOMAIN, PROVIDER_OBSERVATION_SCHEMA_V1,
    PROVIDER_SOURCE_DOMAIN, ActionRuntimeObservationRefV1, ProviderRuntimeObservationRefV1,
    PublicObservabilityContractError,
)


class ObservabilitySourceAdapterError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def action_runtime_observation_from_record(
    record: Mapping[str, Any], *, project_id: str, project_run_id: str,
    task_execution_id: str, source_ref: str,
) -> ActionRuntimeObservationRefV1:
    if not isinstance(record, Mapping):
        raise ObservabilitySourceAdapterError("action-runtime source record must be a mapping")
    schema = record.get("schema_version")
    if schema not in {"gch.full-mcp.execution-event.v1", "gch.full-mcp.result-index.v1"}:
        raise ObservabilitySourceAdapterError("unsupported action-runtime source schema")
    correlation_id = str(record.get("correlation_id", ""))
    operation_request_id = str(record.get("operation_request_id", ""))
    if schema == "gch.full-mcp.execution-event.v1":
        sequence = record.get("sequence")
        state = str(record.get("state", ""))
        unsigned = dict(record); unsigned.pop("audit_ref", None)
        event_digest = _digest(unsigned)
    else:
        sequence = 1
        state = str(record.get("state", ""))
        supplied = str(record.get("result_digest", ""))
        unsigned = dict(record); unsigned.pop("result_digest", None)
        if supplied != _digest(unsigned):
            raise ObservabilitySourceAdapterError("action-runtime result digest mismatch")
        event_digest = supplied
    try:
        return ActionRuntimeObservationRefV1(
            schema_version=ACTION_OBSERVATION_SCHEMA_V1, project_id=project_id,
            project_run_id=project_run_id, task_execution_id=task_execution_id,
            correlation_id=correlation_id, operation_request_id=operation_request_id,
            source_domain=ACTION_SOURCE_DOMAIN, source_ref=source_ref, event_digest=event_digest,
            sequence=int(sequence), bounded_state=state,
        )
    except (TypeError, ValueError, PublicObservabilityContractError) as exc:
        raise ObservabilitySourceAdapterError(str(exc)) from exc


def provider_runtime_observation_from_event(
    event: ProviderRuntimeEventV1, *, source_ref: str,
) -> ProviderRuntimeObservationRefV1:
    if not isinstance(event, ProviderRuntimeEventV1) or event.schema_version != EVENT_SCHEMA_V1:
        raise ObservabilitySourceAdapterError("ProviderRuntimeEventV1 is required")
    # Reconstructing validates the canonical source digest and durable-safe facts.
    try:
        validated = ProviderRuntimeEventV1(**event.to_dict())
        return ProviderRuntimeObservationRefV1(
            schema_version=PROVIDER_OBSERVATION_SCHEMA_V1,
            project_id=validated.project_id, project_run_id=validated.project_run_id,
            task_execution_id=validated.task_execution_id, correlation_id=validated.correlation_id,
            operation_request_id=validated.operation_request_id, source_domain=PROVIDER_SOURCE_DOMAIN,
            source_ref=source_ref, event_digest=validated.event_digest, sequence=validated.sequence,
            bounded_event_type=validated.event_type,
        )
    except (TypeError, ValueError) as exc:
        raise ObservabilitySourceAdapterError(str(exc)) from exc
