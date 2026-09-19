"""Immutable provider/model registry and admission fact projection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import (
    ADMISSION_ADMITTED,
    ADMISSION_DISABLED,
    ELIGIBILITY_FACT_SCHEMA_V1,
    AdmissionRecordV1,
    EligibilityFactV1,
    ModelRecordV1,
    MPRFContractError,
    ProviderRecordV1,
)

REGISTRY_SCHEMA_V1 = "mprf.provider-model-registry.v1"


@dataclass(frozen=True, slots=True)
class ProviderModelRegistryV1:
    schema_version: str
    registry_id: str
    registry_version: int
    providers: tuple[ProviderRecordV1, ...]
    models: tuple[ModelRecordV1, ...]
    admissions: tuple[AdmissionRecordV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_SCHEMA_V1:
            raise MPRFContractError("unsupported registry schema")
        if not isinstance(self.registry_id, str) or not self.registry_id.strip():
            raise MPRFContractError("registry_id must be non-empty")
        if isinstance(self.registry_version, bool) or not isinstance(self.registry_version, int) or self.registry_version < 1:
            raise MPRFContractError("registry_version must be positive")
        object.__setattr__(self, "providers", tuple(self.providers))
        object.__setattr__(self, "models", tuple(self.models))
        object.__setattr__(self, "admissions", tuple(self.admissions))

        provider_ids = [item.provider_id for item in self.providers]
        if not provider_ids or len(provider_ids) != len(set(provider_ids)):
            raise MPRFContractError("registry provider identities must be non-empty and unique")
        provider_domain = set(provider_ids)

        model_keys = [(item.provider_id, item.model_ref) for item in self.models]
        if len(model_keys) != len(set(model_keys)):
            raise MPRFContractError("duplicate model identity")
        if any(provider not in provider_domain for provider, _ in model_keys):
            raise MPRFContractError("model references unknown provider")

        admission_ids = [item.admission_id for item in self.admissions]
        if len(admission_ids) != len(set(admission_ids)):
            raise MPRFContractError("duplicate admission identity")

        model_key_set = set(model_keys)
        admission_keys: set[tuple[str, str, int]] = set()
        current_provider_ids: set[str] = set()
        for item in self.admissions:
            key = (item.provider_id, item.model_ref, item.registry_version)
            if key in admission_keys:
                raise MPRFContractError("duplicate admission record")
            admission_keys.add(key)
            if (item.provider_id, item.model_ref) not in model_key_set:
                raise MPRFContractError("admission references unknown model")
            if item.registry_version > self.registry_version:
                raise MPRFContractError("future admission version is invalid")
            if item.registry_version == self.registry_version:
                if item.provider_id in current_provider_ids:
                    raise MPRFContractError("conflicting current admission for provider")
                current_provider_ids.add(item.provider_id)

    def _historical_admissions(self, provider_id: str, model_ref: str = "") -> list[AdmissionRecordV1]:
        return [item for item in self.admissions
                if item.provider_id == provider_id and (not model_ref or item.model_ref == model_ref)]

    def eligibility_fact(self, provider_id: str, model_ref: str = "") -> EligibilityFactV1:
        provider_domain = {item.provider_id for item in self.providers}
        if provider_id not in provider_domain:
            return self._ineligible(provider_id, model_ref, "UNKNOWN_PROVIDER")
        if model_ref and (provider_id, model_ref) not in {(m.provider_id, m.model_ref) for m in self.models}:
            return self._ineligible(provider_id, model_ref, "UNKNOWN_MODEL")

        history = self._historical_admissions(provider_id, model_ref)
        current = [item for item in history if item.registry_version == self.registry_version]
        if not current:
            reason = "STALE_ADMISSION" if history else "NO_ADMISSION"
            stale_model = model_ref or (history[-1].model_ref if history else "")
            return self._ineligible(provider_id, stale_model, reason)
        admission = current[0]
        if admission.state == ADMISSION_DISABLED:
            return self._ineligible(provider_id, admission.model_ref, "ADMISSION_DISABLED", admission.admission_id)
        if admission.state != ADMISSION_ADMITTED:
            return self._ineligible(provider_id, admission.model_ref, "NO_ADMISSION", admission.admission_id)
        return EligibilityFactV1(
            schema_version=ELIGIBILITY_FACT_SCHEMA_V1,
            provider_id=provider_id,
            model_ref=admission.model_ref,
            registry_version=self.registry_version,
            eligible=True,
            reason_code="ADMITTED",
            admission_id=admission.admission_id,
        )

    def _ineligible(self, provider_id: str, model_ref: str, reason: str,
                    admission_id: str = "") -> EligibilityFactV1:
        return EligibilityFactV1(
            schema_version=ELIGIBILITY_FACT_SCHEMA_V1, provider_id=provider_id,
            model_ref=model_ref, registry_version=self.registry_version,
            eligible=False, reason_code=reason, admission_id=admission_id,
        )

    def export_router_snapshot(self, snapshot_id: str,
                               evidence_refs: Iterable[str] = ()):
        """Project MPRF facts into the Router-owned public eligibility contract."""
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise MPRFContractError("snapshot_id must be non-empty")
        from runtime.orchestrator.provider_router import (
            ELIGIBILITY_SCHEMA_V1,
            ProviderEligibilitySnapshotV1,
        )

        facts = {provider: self.eligibility_fact(provider)
                 for provider in sorted(item.provider_id for item in self.providers)}
        eligible = {provider: fact.eligible for provider, fact in facts.items()}
        model_refs = {provider: fact.model_ref for provider, fact in facts.items()
                      if fact.eligible}
        return ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1,
            snapshot_id=snapshot_id,
            provider_eligible=eligible,
            model_refs=model_refs,
            evidence_refs=tuple(str(item) for item in evidence_refs),
            failure_classes=None,
        )
