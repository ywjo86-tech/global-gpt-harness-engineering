from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping

from .provider_router import ELIGIBILITY_SCHEMA_V1, ProviderEligibilitySnapshotV1

PROVIDER_CANDIDATE_SCHEMA_V1 = "gch.provider-candidate.v1"
ADMISSION_STATES = ("DISCOVERED", "CANDIDATE", "VALIDATING", "QUALIFIED", "APPROVAL", "ACTIVE")
ALLOWED_TRANSITIONS = {
    "DISCOVERED": {"CANDIDATE"},
    "CANDIDATE": {"VALIDATING"},
    "VALIDATING": {"QUALIFIED", "CANDIDATE"},
    "QUALIFIED": {"APPROVAL"},
    "APPROVAL": {"ACTIVE", "QUALIFIED"},
    "ACTIVE": set(),
}
_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class CandidateInventoryError(ValueError):
    pass


def _clean_tuple(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    cleaned = tuple(str(value).strip() for value in values)
    if any(not value for value in cleaned) or len(cleaned) != len(set(cleaned)):
        raise CandidateInventoryError(f"invalid {field}")
    return cleaned


@dataclass(frozen=True, slots=True)
class ProviderCandidateRecordV1:
    schema_version: str
    provider_id: str
    protocol_class: str
    state: str
    model_refs: tuple[str, ...]
    credential_required: bool
    cost_class: str
    capability_refs: tuple[str, ...]
    readiness_evidence_refs: tuple[str, ...] = ()
    action_evidence_ref: str = ""
    reroute_evidence_ref: str = ""
    activation_approval_ref: str = ""
    cost_risk_approval_ref: str = ""
    connection_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_CANDIDATE_SCHEMA_V1:
            raise CandidateInventoryError("unsupported candidate schema")
        provider_id = self.provider_id.strip().lower()
        if not _PROVIDER_ID.fullmatch(provider_id) or provider_id in {"auto", "model:auto"}:
            raise CandidateInventoryError("invalid provider id")
        if not self.protocol_class.strip() or self.state not in ADMISSION_STATES:
            raise CandidateInventoryError("invalid candidate identity/state")
        models = _clean_tuple(self.model_refs, field="model refs") if self.model_refs else ()
        if any(model.lower() == "auto" or model.lower().endswith(":auto") for model in models):
            raise CandidateInventoryError("automatic model selection is forbidden")
        capabilities = _clean_tuple(self.capability_refs, field="capability refs") if self.capability_refs else ()
        readiness = _clean_tuple(self.readiness_evidence_refs, field="readiness evidence") if self.readiness_evidence_refs else ()
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_refs", models)
        object.__setattr__(self, "capability_refs", capabilities)
        object.__setattr__(self, "readiness_evidence_refs", readiness)
        if self.state in {"QUALIFIED", "APPROVAL", "ACTIVE"}:
            if len(models) != 1:
                raise CandidateInventoryError(f"{self.state} requires exactly one explicit model")
            if not readiness or not self.action_evidence_ref.strip() or not self.reroute_evidence_ref.strip():
                raise CandidateInventoryError(f"{self.state} requires complete live qualification evidence")
        if self.state == "ACTIVE":
            if not self.activation_approval_ref.strip():
                raise CandidateInventoryError("ACTIVE requires activation approval")
            if self.cost_class.strip().lower() == "paid" and not self.cost_risk_approval_ref.strip():
                raise CandidateInventoryError("paid ACTIVE requires cost/risk approval")


@dataclass(frozen=True, slots=True)
class ProviderCandidateInventoryV1:
    records: tuple[ProviderCandidateRecordV1, ...]

    def __post_init__(self) -> None:
        ids = tuple(record.provider_id for record in self.records)
        if len(ids) != len(set(ids)):
            raise CandidateInventoryError("duplicate provider id in candidate inventory")


def transition_candidate(record: ProviderCandidateRecordV1, new_state: str, **changes: Any) -> ProviderCandidateRecordV1:
    if new_state not in ALLOWED_TRANSITIONS.get(record.state, set()):
        raise CandidateInventoryError(f"invalid admission transition: {record.state}->{new_state}")
    return replace(record, state=new_state, **changes)


def import_omniroute_discovery(payload: Mapping[str, Any]) -> ProviderCandidateInventoryV1:
    raw = payload.get("providers")
    if not isinstance(raw, list):
        raise CandidateInventoryError("OmniRoute discovery providers list required")
    records: list[ProviderCandidateRecordV1] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise CandidateInventoryError("malformed OmniRoute provider record")
        if "state" in item and str(item.get("state", "DISCOVERED")) != "DISCOVERED":
            raise CandidateInventoryError("discovery cannot import elevated state")
        provider_id = str(item.get("id", "")).strip().lower()
        category = str(item.get("category", "unknown")).strip().lower() or "unknown"
        records.append(ProviderCandidateRecordV1(
            schema_version=PROVIDER_CANDIDATE_SCHEMA_V1,
            provider_id=provider_id,
            protocol_class=str(item.get("protocol_class", "unknown")).strip() or "unknown",
            state="DISCOVERED",
            model_refs=(),
            credential_required=category != "free",
            cost_class="free" if bool(item.get("hasFree")) or category == "free" else "unknown",
            capability_refs=(),
        ))
    return ProviderCandidateInventoryV1(tuple(records))


def project_active_candidates(
    base: ProviderEligibilitySnapshotV1, inventory: ProviderCandidateInventoryV1,
) -> ProviderEligibilitySnapshotV1:
    eligible = dict(base.provider_eligible)
    models = dict(base.model_refs)
    capabilities = dict(base.provider_capabilities or {})
    evidence = list(base.evidence_refs)
    for record in inventory.records:
        if record.state != "ACTIVE":
            continue
        if record.provider_id in eligible or record.provider_id in models:
            raise CandidateInventoryError("candidate provider collides with existing production provider")
        eligible[record.provider_id] = True
        models[record.provider_id] = record.model_refs[0]
        capabilities[record.provider_id] = record.capability_refs
        evidence.extend(record.readiness_evidence_refs)
        evidence.extend((record.action_evidence_ref, record.reroute_evidence_ref, record.activation_approval_ref))
        if record.cost_risk_approval_ref:
            evidence.append(record.cost_risk_approval_ref)
    return ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1,
        f"{base.snapshot_id}-candidates",
        eligible,
        models,
        tuple(dict.fromkeys(ref for ref in evidence if ref)),
        base.failure_classes,
        base.model_fallback_refs,
        capabilities or None,
    )
