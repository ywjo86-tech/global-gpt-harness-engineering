from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contracts import AIOfficeContractError, canonical_digest

REQUIREMENT_ENVELOPE_SCHEMA_V1 = "ai-office.requirement-envelope.v1"


class RequirementIntakeError(ValueError):
    pass


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise RequirementIntakeError(f"invalid {label}")
    text = value.strip()
    if any(ch in text for ch in ("\x00", "\n", "\r")):
        raise RequirementIntakeError(f"invalid {label}")
    return text


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise RequirementIntakeError(f"invalid {label}")
    return text
@dataclass(frozen=True, slots=True)
class RequirementEnvelopeV1:
    schema_version: str
    requirement_id: str
    source_ref: str
    source_digest: str
    planning_authority_ref: str
    constraints_refs: tuple[str, ...]
    correlation_id: str

    def __post_init__(self) -> None:
        if self.schema_version != REQUIREMENT_ENVELOPE_SCHEMA_V1:
            raise RequirementIntakeError("unsupported requirement envelope schema")
        object.__setattr__(self, "requirement_id", _required_text(self.requirement_id, "requirement_id"))
        object.__setattr__(self, "source_ref", _required_text(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_digest", _sha256(self.source_digest, "source_digest"))
        object.__setattr__(self, "planning_authority_ref", _required_text(self.planning_authority_ref, "planning_authority_ref"))
        refs = tuple(_required_text(ref, "constraint_ref") for ref in self.constraints_refs)
        if len(refs) != len(set(refs)):
            raise RequirementIntakeError("duplicate constraint ref")
        object.__setattr__(self, "constraints_refs", refs)
        object.__setattr__(self, "correlation_id", _required_text(self.correlation_id, "correlation_id"))

    def unsigned_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def envelope_digest(self) -> str:
        return canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "envelope_digest": self.envelope_digest}
def intake_requirement(
    candidate: Mapping[str, Any], *, approved_register: Mapping[str, Mapping[str, Any]]
) -> RequirementEnvelopeV1:
    if not isinstance(candidate, Mapping):
        raise RequirementIntakeError("requirement candidate must be a mapping")
    allowed = {"requirement_id", "source_ref", "source_digest", "planning_authority_ref", "constraints_refs", "correlation_id"}
    if set(candidate) != allowed:
        raise RequirementIntakeError("requirement candidate shape mismatch")
    requirement_id = _required_text(candidate["requirement_id"], "requirement_id")
    approved = approved_register.get(requirement_id)
    if not isinstance(approved, Mapping):
        raise RequirementIntakeError("SOURCE_BINDING_BLOCKED: unknown approved requirement")
    for key in ("source_ref", "source_digest", "planning_authority_ref"):
        if candidate.get(key) != approved.get(key):
            raise RequirementIntakeError(f"SOURCE_BINDING_BLOCKED: {key} mismatch")
    approved_constraints = tuple(approved.get("constraints_refs", ()))
    if tuple(candidate.get("constraints_refs", ())) != approved_constraints:
        raise RequirementIntakeError("SOURCE_BINDING_BLOCKED: constraint binding mismatch")
    try:
        return RequirementEnvelopeV1(
            REQUIREMENT_ENVELOPE_SCHEMA_V1, requirement_id, str(candidate["source_ref"]),
            str(candidate["source_digest"]), str(candidate["planning_authority_ref"]),
            tuple(candidate["constraints_refs"]), str(candidate["correlation_id"]),
        )
    except AIOfficeContractError as exc:
        raise RequirementIntakeError(str(exc)) from exc
