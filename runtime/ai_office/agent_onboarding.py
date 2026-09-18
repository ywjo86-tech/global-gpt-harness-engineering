from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from .contracts import canonical_digest

AGENT_ONBOARDING_SCHEMA_V1 = "ai-office.agent-onboarding.v1"


class AgentOnboardingError(ValueError):
    pass


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise AgentOnboardingError(f"invalid {label}")
    return value.strip()


def _sha(value: object, label: str) -> str:
    item = _text(value, label)
    if len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
        raise AgentOnboardingError(f"invalid {label}")
    return item


GovernedAdoptionValidator = Callable[[str, str, str], bool]
@dataclass(frozen=True, slots=True)
class AgentOnboardingRecordV1:
    schema_version: str
    agent_id: str
    source_ref: str
    source_digest: str
    version_ref: str
    risk_decision_ref: str
    permission_decision_ref: str
    human_approval_ref: str
    adoption_control_ref: str
    activation_version: int
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_ONBOARDING_SCHEMA_V1:
            raise AgentOnboardingError("unsupported onboarding schema")
        for field in ("agent_id", "source_ref", "version_ref", "risk_decision_ref",
                      "permission_decision_ref", "adoption_control_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "source_digest", _sha(self.source_digest, "source_digest"))
        if self.human_approval_ref:
            object.__setattr__(self, "human_approval_ref", _text(self.human_approval_ref, "human_approval_ref"))
        if isinstance(self.activation_version, bool) or not isinstance(self.activation_version, int) or self.activation_version < 1:
            raise AgentOnboardingError("invalid activation version")
        if self.status not in {"ELIGIBLE", "BLOCKED"}:
            raise AgentOnboardingError("invalid onboarding status")

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        return {**body, "record_digest": canonical_digest(body)}
def evaluate_onboarding(
    candidate: Mapping[str, Any], *, adoption_validator: GovernedAdoptionValidator,
    previous_record: AgentOnboardingRecordV1 | None = None,
) -> AgentOnboardingRecordV1:
    forbidden = {"provider", "provider_ref", "model", "model_ref", "provider_registry"}
    if not isinstance(candidate, Mapping) or forbidden.intersection(candidate):
        raise AgentOnboardingError("forbidden routing/runtime material in onboarding candidate")
    required = {
        "agent_id", "source_ref", "source_digest", "version_ref", "risk_decision_ref",
        "permission_decision_ref", "human_approval_ref", "adoption_control_ref",
        "activation_version", "approved_source", "immutable_version", "risk_allowed",
        "permission_allowed", "human_approval_required",
    }
    if set(candidate) != required:
        raise AgentOnboardingError("onboarding candidate shape mismatch")
    approved = bool(candidate["approved_source"] and candidate["immutable_version"] and
                    candidate["risk_allowed"] and candidate["permission_allowed"])
    if candidate["human_approval_required"] and not str(candidate["human_approval_ref"]).strip():
        approved = False
    if previous_record is not None:
        if previous_record.agent_id != candidate["agent_id"] or candidate["activation_version"] != previous_record.activation_version + 1:
            approved = False
    elif candidate["activation_version"] != 1:
        approved = False
    control_ok = False
    if approved:
        control_ok = bool(adoption_validator(
            str(candidate["source_ref"]), str(candidate["source_digest"]), str(candidate["adoption_control_ref"])
        ))
    status = "ELIGIBLE" if approved and control_ok else "BLOCKED"
    return AgentOnboardingRecordV1(
        AGENT_ONBOARDING_SCHEMA_V1, str(candidate["agent_id"]), str(candidate["source_ref"]),
        str(candidate["source_digest"]), str(candidate["version_ref"]), str(candidate["risk_decision_ref"]),
        str(candidate["permission_decision_ref"]), str(candidate["human_approval_ref"]),
        str(candidate["adoption_control_ref"]), int(candidate["activation_version"]), status,
    )
