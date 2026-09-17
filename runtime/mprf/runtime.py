"""MPRF registry runtime facade; facts only, never provider selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import EligibilityFactV1, MPRFContractError
from .registry import ProviderModelRegistryV1

RUNTIME_SCHEMA_V1 = "mprf.runtime.v1"


@dataclass(frozen=True, slots=True)
class MPRFRuntimeV1:
    schema_version: str
    registry: ProviderModelRegistryV1

    def __post_init__(self) -> None:
        if self.schema_version != RUNTIME_SCHEMA_V1:
            raise MPRFContractError("unsupported MPRF runtime schema")
        if not isinstance(self.registry, ProviderModelRegistryV1):
            raise MPRFContractError("registry contract is required")

    def eligibility_fact(self, provider_id: str, model_ref: str = "") -> EligibilityFactV1:
        return self.registry.eligibility_fact(provider_id, model_ref)

    def export_router_snapshot(self, snapshot_id: str,
                               evidence_refs: Iterable[str] = ()):
        return self.registry.export_router_snapshot(snapshot_id, evidence_refs)
