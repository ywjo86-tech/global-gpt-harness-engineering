from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from runtime.agents import AGENT_REGISTRY

from .contracts import canonical_digest

CAPABILITY_NEED_SCHEMA_V1 = "ai-office.capability-need.v1"
CAPABILITY_DISPATCH_SCHEMA_V1 = "ai-office.capability-dispatch.v1"
AGENT_CANDIDATE_SCHEMA_V1 = "ai-office.agent-candidate.v1"
OWNER_BOUNDARIES = frozenset({"FULL_PLAN", "MULTI_PROVIDER_ROUTER", "MPRF", "EXECUTION_BACKEND", "AI_OFFICE"})

OWNER_CAPABILITIES = {
    "FULL_PLAN": frozenset({"planning", "task_decomposition", "final_assignment", "task_fanin"}),
    "MULTI_PROVIDER_ROUTER": frozenset({"reasoning", "read_only", "review", "documentation", "code_generation"}),
    "MPRF": frozenset({"provider_runtime", "provider_health", "provider_checkpoint", "provider_observability"}),
    "EXECUTION_BACKEND": frozenset({"filesystem_write", "shell", "git", "activation", "state_change"}),
    "AI_OFFICE": frozenset({"office_state", "context_assembly", "foundry", "governance", "reporting", "recovery_coordination"}),
}


class CapabilityGovernanceError(ValueError):
    pass
def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise CapabilityGovernanceError(f"invalid {label}")
    return value.strip()


def _capabilities(values: Iterable[str]) -> tuple[str, ...]:
    items = tuple(sorted({_text(item, "capability") for item in values}))
    if not items:
        raise CapabilityGovernanceError("capabilities are required")
    return items


@dataclass(frozen=True, slots=True)
class CapabilityNeedV1:
    schema_version: str
    capability_need_id: str
    required_capabilities: tuple[str, ...]
    execution_authority: str
    purpose_ref: str
    scope_ref: str

    def __post_init__(self) -> None:
        if self.schema_version != CAPABILITY_NEED_SCHEMA_V1:
            raise CapabilityGovernanceError("unsupported capability need schema")
        object.__setattr__(self, "capability_need_id", _text(self.capability_need_id, "capability_need_id"))
        object.__setattr__(self, "required_capabilities", _capabilities(self.required_capabilities))
        if self.execution_authority not in {"READ_ONLY", "STATE_CHANGING"}:
            raise CapabilityGovernanceError("invalid execution authority")
        object.__setattr__(self, "purpose_ref", _text(self.purpose_ref, "purpose_ref"))
        object.__setattr__(self, "scope_ref", _text(self.scope_ref, "scope_ref"))
    @property
    def need_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class CapabilityDispatchDecisionV1:
    schema_version: str
    capability_need_id: str
    owner_boundary: str
    disposition: str
    rationale_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CAPABILITY_DISPATCH_SCHEMA_V1:
            raise CapabilityGovernanceError("unsupported capability dispatch schema")
        object.__setattr__(self, "capability_need_id", _text(self.capability_need_id, "capability_need_id"))
        if self.owner_boundary and self.owner_boundary not in OWNER_BOUNDARIES:
            raise CapabilityGovernanceError("unknown owner boundary")
        if self.disposition not in {"ROUTABLE", "BLOCKED"}:
            raise CapabilityGovernanceError("invalid capability disposition")
        if self.disposition == "ROUTABLE" and not self.owner_boundary:
            raise CapabilityGovernanceError("routable capability requires owner boundary")
        refs = tuple(_text(ref, "rationale_ref") for ref in self.rationale_refs)
        object.__setattr__(self, "rationale_refs", refs)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "decision_digest": canonical_digest(asdict(self))}

@dataclass(frozen=True, slots=True)
class AgentCandidateV1:
    schema_version: str
    agent_id: str
    version_ref: str
    matched_capabilities: tuple[str, ...]
    inventory_ref: str
    permission_eligible: bool
    risk_eligible: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CANDIDATE_SCHEMA_V1:
            raise CapabilityGovernanceError("unsupported agent candidate schema")
        if self.agent_id not in AGENT_REGISTRY:
            raise CapabilityGovernanceError("candidate agent is not in governed registry")
        object.__setattr__(self, "version_ref", _text(self.version_ref, "version_ref"))
        object.__setattr__(self, "matched_capabilities", _capabilities(self.matched_capabilities))
        object.__setattr__(self, "inventory_ref", _text(self.inventory_ref, "inventory_ref"))
        refs = tuple(_text(ref, "evidence_ref") for ref in self.evidence_refs)
        if len(refs) != len(set(refs)):
            raise CapabilityGovernanceError("duplicate candidate evidence ref")
        object.__setattr__(self, "evidence_refs", refs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
def route_capability_need(need: CapabilityNeedV1) -> CapabilityDispatchDecisionV1:
    owners = {
        owner for owner, capabilities in OWNER_CAPABILITIES.items()
        if set(need.required_capabilities).intersection(capabilities)
    }
    unknown = {
        capability for capability in need.required_capabilities
        if not any(capability in values for values in OWNER_CAPABILITIES.values())
    }
    if unknown or len(owners) != 1:
        reason = "unknown-capability" if unknown else "multi-owner-capability"
        return CapabilityDispatchDecisionV1(
            CAPABILITY_DISPATCH_SCHEMA_V1, need.capability_need_id, "", "BLOCKED", (reason,)
        )
    owner = next(iter(owners))
    if need.execution_authority == "STATE_CHANGING" and owner == "MULTI_PROVIDER_ROUTER":
        return CapabilityDispatchDecisionV1(
            CAPABILITY_DISPATCH_SCHEMA_V1, need.capability_need_id, "", "BLOCKED",
            ("read-capability-cannot-own-state-change",),
        )
    return CapabilityDispatchDecisionV1(
        CAPABILITY_DISPATCH_SCHEMA_V1, need.capability_need_id, owner, "ROUTABLE",
        (f"owner-boundary:{owner}",),
    )
def find_agents(
    need: CapabilityNeedV1,
    inventory: Iterable[Mapping[str, Any]],
) -> tuple[AgentCandidateV1, ...]:
    forbidden = {"provider", "provider_ref", "model", "model_ref", "selected", "final_assignee"}
    candidates: list[AgentCandidateV1] = []
    seen: set[str] = set()
    for row in inventory:
        if not isinstance(row, Mapping) or forbidden.intersection(row):
            raise CapabilityGovernanceError("inventory contains forbidden routing/assignment material")
        agent_id = str(row.get("agent_id", ""))
        if agent_id in seen:
            raise CapabilityGovernanceError("duplicate agent identity")
        seen.add(agent_id)
        if agent_id not in AGENT_REGISTRY or not row.get("approved", False):
            continue
        available = set(_capabilities(tuple(row.get("capabilities", ()))))
        required = set(need.required_capabilities)
        if not required.issubset(available):
            continue
        if not row.get("permission_eligible", False) or not row.get("risk_eligible", False):
            continue
        candidates.append(AgentCandidateV1(
            AGENT_CANDIDATE_SCHEMA_V1,
            agent_id,
            _text(row.get("version_ref"), "version_ref"),
            tuple(sorted(required)),
            _text(row.get("inventory_ref"), "inventory_ref"),
            True,
            True,
            tuple(row.get("evidence_refs", ())),
        ))
    return tuple(sorted(candidates, key=lambda item: (item.agent_id, item.version_ref)))
