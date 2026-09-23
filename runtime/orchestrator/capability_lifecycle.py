"""Operational lifecycle contracts for external capabilities.

Admission/discovery remain owned by the existing capability pipeline. This module
only tracks an already evaluated/authorized runtime contract and owns no final
agent assignment, provider selection, or state-changing effect authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Any


LIFECYCLE_STATES = frozenset({
    "DISCOVERED", "CANDIDATE", "SANDBOX", "QUALIFIED", "ACTIVE",
    "DEGRADED", "QUARANTINED", "DISABLE_NEW_ASSIGNMENT", "DRAINING",
    "SUPERSEDED", "DEPRECATED", "RETIRED",
})
BINDING_KINDS = frozenset({"MCP_ENDPOINT", "ADAPTER", "LOCAL_SKILL"})
HEALTH_STATES = frozenset({"HEALTHY", "WARN", "DEGRADED", "UNHEALTHY", "UNKNOWN"})
_ALLOWED = {
    "DISCOVERED": {"CANDIDATE"},
    "CANDIDATE": {"SANDBOX", "QUARANTINED"},
    "SANDBOX": {"QUALIFIED", "QUARANTINED"},
    "QUALIFIED": {"ACTIVE", "QUARANTINED"},
    "ACTIVE": {"DEGRADED", "QUARANTINED", "DISABLE_NEW_ASSIGNMENT", "RETIRED"},
    "DEGRADED": {"ACTIVE", "QUARANTINED", "DISABLE_NEW_ASSIGNMENT"},
    "QUARANTINED": {"ACTIVE", "DISABLE_NEW_ASSIGNMENT"},
    "DISABLE_NEW_ASSIGNMENT": {"DRAINING"},
    "DRAINING": {"SUPERSEDED", "DEPRECATED", "RETIRED"},
    "SUPERSEDED": {"RETIRED"},
    "DEPRECATED": {"RETIRED"},
}
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}\Z")


class CapabilityLifecycleError(ValueError):
    pass


def _safe(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if allow_empty and not text:
        return ""
    if not _SAFE.fullmatch(text) or ".." in text:
        raise CapabilityLifecycleError(f"invalid {label}")
    return text


def _tuple(values: tuple[str, ...] | list[str], label: str) -> tuple[str, ...]:
    result = tuple(_safe(item, label) for item in values)
    if len(result) != len(set(result)):
        raise CapabilityLifecycleError(f"duplicate {label}")
    return result


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CapabilityContractRefV1:
    contract_id: str
    contract_version: str
    binding_kind: str
    endpoint_ref: str
    stable_asset_identifier: str
    endpoint_version: str
    activation_epoch: int
    allowed_capabilities: tuple[str, ...] = ()
    blocked_capabilities: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _safe(self.contract_id, "contract ID"))
        object.__setattr__(self, "contract_version", _safe(self.contract_version, "contract version"))
        if self.binding_kind not in BINDING_KINDS:
            raise CapabilityLifecycleError("invalid binding kind")
        endpoint = _safe(self.endpoint_ref, "endpoint ref", allow_empty=True)
        asset = _safe(self.stable_asset_identifier, "stable asset identifier", allow_empty=True)
        if self.binding_kind in {"MCP_ENDPOINT", "ADAPTER"}:
            if not endpoint or asset:
                raise CapabilityLifecycleError("MCP/Adapter binding requires endpoint ref and forbids installed asset")
        elif not asset:
            raise CapabilityLifecycleError("LOCAL_SKILL binding requires authorized stable asset identifier")
        object.__setattr__(self, "endpoint_ref", endpoint)
        object.__setattr__(self, "stable_asset_identifier", asset)
        object.__setattr__(self, "endpoint_version", _safe(self.endpoint_version, "endpoint version"))
        if isinstance(self.activation_epoch, bool) or not isinstance(self.activation_epoch, int) or self.activation_epoch <= 0:
            raise CapabilityLifecycleError("activation epoch must be positive")
        allowed = _tuple(self.allowed_capabilities, "allowed capability")
        blocked = _tuple(self.blocked_capabilities, "blocked capability")
        if set(allowed) & set(blocked):
            raise CapabilityLifecycleError("allowed and blocked capabilities overlap")
        object.__setattr__(self, "allowed_capabilities", allowed)
        object.__setattr__(self, "blocked_capabilities", blocked)
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs, "contract evidence ref"))


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleRecordV1:
    contract: CapabilityContractRefV1
    state: str
    health: str
    active_dependency_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    record_digest: str

    @property
    def active_dependency_count(self) -> int:
        return len(self.active_dependency_ids)

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("record_digest", None)
        return value

    def expected_digest(self) -> str:
        return _digest(self.unsigned_dict())

    def valid(self) -> bool:
        return self.record_digest == self.expected_digest()

    @classmethod
    def create(cls, *, contract: CapabilityContractRefV1, state: str, health: str,
               active_dependency_ids: tuple[str, ...], evidence_refs: tuple[str, ...]) -> "CapabilityLifecycleRecordV1":
        if state not in LIFECYCLE_STATES:
            raise CapabilityLifecycleError("invalid lifecycle state")
        if health not in HEALTH_STATES:
            raise CapabilityLifecycleError("invalid health state")
        dependencies = _tuple(active_dependency_ids, "dependency ID")
        evidence = _tuple(evidence_refs, "lifecycle evidence ref")
        provisional = cls(contract, state, health, dependencies, evidence, "")
        return replace(provisional, record_digest=provisional.expected_digest())


def transition_capability_lifecycle(record: CapabilityLifecycleRecordV1, target_state: str,
                                    evidence_refs: tuple[str, ...]) -> CapabilityLifecycleRecordV1:
    if not isinstance(record, CapabilityLifecycleRecordV1):
        raise CapabilityLifecycleError("lifecycle record is required")
    if target_state not in LIFECYCLE_STATES:
        raise CapabilityLifecycleError("invalid target lifecycle state")
    if target_state not in _ALLOWED.get(record.state, set()):
        raise CapabilityLifecycleError("lifecycle transition is not allowed")
    if target_state == "RETIRED" and record.active_dependency_count:
        raise CapabilityLifecycleError("cannot retire capability with active dependencies")
    transition_evidence = _tuple(evidence_refs, "transition evidence ref")
    if target_state == "RETIRED" and not transition_evidence:
        raise CapabilityLifecycleError("retire evidence is required")
    if not record.valid():
        raise CapabilityLifecycleError("lifecycle record digest mismatch")
    evidence = tuple(dict.fromkeys((*record.evidence_refs, *transition_evidence)))
    return CapabilityLifecycleRecordV1.create(
        contract=record.contract,
        state=target_state,
        health=record.health,
        active_dependency_ids=record.active_dependency_ids,
        evidence_refs=evidence,
    )
