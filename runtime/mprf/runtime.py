"""MPRF runtime facade; provider-runtime facts only, never provider selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .contracts import APPROVED_PROVIDER_IDS, EligibilityFactV1, MPRFContractError
from .lifecycle import (
    LIFECYCLE_OK,
    UNKNOWN_HEALTH,
    LifecycleStateV1,
    evaluate_lifecycle,
)
from .registry import ProviderModelRegistryV1
from .observability import ProviderRuntimeEventStoreV1, ProviderRuntimeEventV1

RUNTIME_SCHEMA_V1 = "mprf.runtime.v1"


@dataclass(frozen=True, slots=True)
class MPRFRuntimeV1:
    schema_version: str
    registry: ProviderModelRegistryV1
    lifecycle_state: LifecycleStateV1 | None = None
    observability_store: ProviderRuntimeEventStoreV1 | None = None

    def __post_init__(self) -> None:
        if self.schema_version != RUNTIME_SCHEMA_V1:
            raise MPRFContractError("unsupported MPRF runtime schema")
        if not isinstance(self.registry, ProviderModelRegistryV1):
            raise MPRFContractError("registry contract is required")
        if self.lifecycle_state is not None and not isinstance(self.lifecycle_state, LifecycleStateV1):
            raise MPRFContractError("lifecycle state must use the v1 contract")
        if self.observability_store is not None and not isinstance(self.observability_store, ProviderRuntimeEventStoreV1):
            raise MPRFContractError("observability store must use the v1 contract")

    def eligibility_fact(self, provider_id: str, model_ref: str = "") -> EligibilityFactV1:
        return self.registry.eligibility_fact(provider_id, model_ref)

    def lifecycle_eligibility(
        self,
        provider_id: str,
        model_ref: str = "",
        required_capabilities: Iterable[str] = (),
    ) -> tuple[bool, str]:
        admission = self.registry.eligibility_fact(provider_id, model_ref)
        if not admission.eligible:
            return False, admission.reason_code
        if self.lifecycle_state is None:
            return True, LIFECYCLE_OK
        fact = self.lifecycle_state.fact_for(admission.provider_id, admission.model_ref)
        if fact is None:
            return False, UNKNOWN_HEALTH
        return evaluate_lifecycle(
            fact,
            required_capabilities,
            expected_registry_version=self.registry.registry_version,
        )

    def export_router_snapshot(
        self,
        snapshot_id: str,
        evidence_refs: Iterable[str] = (),
        required_capabilities: Iterable[str] = (),
    ):
        if self.lifecycle_state is None:
            return self.registry.export_router_snapshot(snapshot_id, evidence_refs)
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise MPRFContractError("snapshot_id must be non-empty")
        from runtime.orchestrator.provider_router import (
            ELIGIBILITY_SCHEMA_V1,
            ProviderEligibilitySnapshotV1,
        )

        eligible: dict[str, bool] = {}
        model_refs: dict[str, str] = {}
        for provider_id in sorted(APPROVED_PROVIDER_IDS):
            admission = self.registry.eligibility_fact(provider_id)
            if not admission.eligible:
                eligible[provider_id] = False
                continue
            lifecycle_ok, _ = self.lifecycle_eligibility(
                provider_id,
                admission.model_ref,
                required_capabilities,
            )
            eligible[provider_id] = lifecycle_ok
            if lifecycle_ok:
                model_refs[provider_id] = admission.model_ref

        return ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1,
            snapshot_id=snapshot_id,
            provider_eligible=eligible,
            model_refs=model_refs,
            evidence_refs=tuple(str(item) for item in evidence_refs),
            failure_classes=None,
        )

    def record_provider_runtime_event(
        self, *, project_id: str, task_id: str, task_execution_id: str, correlation_id: str,
        operation_request_id: str, provider_id: str, model_ref: str, event_type: str,
        facts: Mapping[str, Any] | None = None,
    ) -> ProviderRuntimeEventV1:
        if self.observability_store is None:
            raise MPRFContractError("provider runtime observability is not configured")
        return self.observability_store.append(
            project_id=project_id, task_id=task_id, task_execution_id=task_execution_id,
            correlation_id=correlation_id, operation_request_id=operation_request_id,
            provider_id=provider_id, model_ref=model_ref, event_type=event_type, facts=facts,
        )

    def failure_disposition(self, failure, prerequisites, *, permission_related_auth: bool = False):
        from .failure import evaluate_failover
        return evaluate_failover(failure, prerequisites, permission_related_auth=permission_related_auth)
