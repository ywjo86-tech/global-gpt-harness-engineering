"""Versioned provider/model admission contracts for MPRF."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

PROVIDER_RECORD_SCHEMA_V1 = "mprf.provider-record.v1"
MODEL_RECORD_SCHEMA_V1 = "mprf.model-record.v1"
ADMISSION_RECORD_SCHEMA_V1 = "mprf.admission-record.v1"
ELIGIBILITY_FACT_SCHEMA_V1 = "mprf.eligibility-fact.v1"

NVIDIA_PROVIDER = "nvidia"
CODEX_PROVIDER = "codex"
BUILTIN_PROVIDER_IDS = frozenset({NVIDIA_PROVIDER, CODEX_PROVIDER})
# Backward-compatible export: this is the currently activated built-in production set,
# not the provider identity domain accepted by versioned MPRF contracts.
APPROVED_PROVIDER_IDS = BUILTIN_PROVIDER_IDS
_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

ADMISSION_ADMITTED = "ADMITTED"
ADMISSION_DISABLED = "DISABLED"
ADMISSION_STATES_V1 = frozenset({ADMISSION_ADMITTED, ADMISSION_DISABLED})

ELIGIBLE_REASON = "ADMITTED"
INELIGIBLE_REASONS_V1 = frozenset({
    "UNKNOWN_PROVIDER", "UNKNOWN_MODEL", "NO_ADMISSION",
    "ADMISSION_DISABLED", "STALE_ADMISSION",
})

class MPRFContractError(ValueError):
    pass

def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MPRFContractError(f"{field} must be a non-empty string")


def validate_provider_id(value: str) -> str:
    if not isinstance(value, str) or not _PROVIDER_ID.fullmatch(value):
        raise MPRFContractError("provider_id is invalid")
    return value


def _require_version(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MPRFContractError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class ProviderRecordV1:
    schema_version: str
    provider_id: str
    record_version: int

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_RECORD_SCHEMA_V1:
            raise MPRFContractError("unsupported provider record schema")
        validate_provider_id(self.provider_id)
        _require_version(self.record_version, "record_version")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "provider_id": self.provider_id,
                "record_version": self.record_version}


@dataclass(frozen=True, slots=True)
class ModelRecordV1:
    schema_version: str
    provider_id: str
    model_ref: str
    record_version: int

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_RECORD_SCHEMA_V1:
            raise MPRFContractError("unsupported model record schema")
        validate_provider_id(self.provider_id)
        _require_text(self.model_ref, "model_ref")
        _require_version(self.record_version, "record_version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "model_ref": self.model_ref,
            "record_version": self.record_version,
        }


@dataclass(frozen=True, slots=True)
class AdmissionRecordV1:
    schema_version: str
    admission_id: str
    provider_id: str
    model_ref: str
    registry_version: int
    state: str = ADMISSION_ADMITTED

    def __post_init__(self) -> None:
        if self.schema_version != ADMISSION_RECORD_SCHEMA_V1:
            raise MPRFContractError("unsupported admission record schema")
        _require_text(self.admission_id, "admission_id")
        validate_provider_id(self.provider_id)
        _require_text(self.model_ref, "model_ref")
        _require_version(self.registry_version, "registry_version")
        if self.state not in ADMISSION_STATES_V1:
            raise MPRFContractError("unknown admission state")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "admission_id": self.admission_id,
                "provider_id": self.provider_id, "model_ref": self.model_ref,
                "registry_version": self.registry_version, "state": self.state}


@dataclass(frozen=True, slots=True)
class EligibilityFactV1:
    schema_version: str
    provider_id: str
    model_ref: str
    registry_version: int
    eligible: bool
    reason_code: str
    admission_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != ELIGIBILITY_FACT_SCHEMA_V1:
            raise MPRFContractError("unsupported eligibility fact schema")
        _require_text(self.provider_id, "provider_id")
        _require_version(self.registry_version, "registry_version")
        if self.eligible:
            if self.reason_code != ELIGIBLE_REASON or not self.model_ref or not self.admission_id:
                raise MPRFContractError("eligible fact is incomplete")
        elif self.reason_code not in INELIGIBLE_REASONS_V1:
            raise MPRFContractError("unknown ineligible reason")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "provider_id": self.provider_id,
                "model_ref": self.model_ref, "registry_version": self.registry_version,
                "eligible": self.eligible, "reason_code": self.reason_code,
                "admission_id": self.admission_id}
