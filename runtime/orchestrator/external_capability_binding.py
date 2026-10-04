"""Contract-only binding for externally hosted capabilities."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


BINDING_KINDS = frozenset({"MCP_ENDPOINT", "ADAPTER", "LOCAL_SKILL"})
EFFECT_POLICIES = frozenset({"READ_ONLY", "GATEWAY_REQUIRED"})


class ExternalCapabilityBindingError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _field(value: object, name: str, default: object = "") -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


@dataclass(frozen=True, slots=True)
class ExternalCapabilityBindingV1:
    binding_kind: str
    endpoint_ref: str
    stable_asset_identifier: str
    allowed_capabilities: tuple[str, ...]
    blocked_capabilities: tuple[str, ...]
    permission_scope: tuple[str, ...]
    effect_policy: str
    evaluation_evidence_ref: str
    binding_digest: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["allowed_capabilities"] = list(self.allowed_capabilities)
        value["blocked_capabilities"] = list(self.blocked_capabilities)
        value["permission_scope"] = list(self.permission_scope)
        return value


def qualify_external_binding(
    *,
    evaluation: object,
    binding_kind: str,
    endpoint_ref: str,
    requested_capabilities: tuple[str, ...],
    allowed_capabilities: tuple[str, ...],
    blocked_capabilities: tuple[str, ...],
    effect_policy: str,
    permission_scope: tuple[str, ...] = (),
    local_skill_asset_id: str = "",
) -> ExternalCapabilityBindingV1:
    if binding_kind not in BINDING_KINDS:
        raise ExternalCapabilityBindingError("unsupported binding kind")
    if effect_policy not in EFFECT_POLICIES:
        raise ExternalCapabilityBindingError("unsupported effect policy")
    raw_state = _field(evaluation, "evaluation_state", _field(evaluation, "state", ""))
    state = str(getattr(raw_state, "value", raw_state))
    if state != "SAFE_FOR_CONSIDERATION":
        raise ExternalCapabilityBindingError("candidate evaluation is not safe for consideration")
    evidence_ref = str(
        _field(
            evaluation,
            "evidence_reference",
            _field(evaluation, "evidence_ref", _field(evaluation, "evaluation_evidence_ref", "")),
        )
    ).strip()
    if not evidence_ref:
        raise ExternalCapabilityBindingError("evaluation evidence is required")
    requested = tuple(dict.fromkeys(str(item) for item in requested_capabilities))
    allowed = tuple(dict.fromkeys(str(item) for item in allowed_capabilities))
    blocked = tuple(dict.fromkeys(str(item) for item in blocked_capabilities))
    if set(allowed) & set(blocked):
        raise ExternalCapabilityBindingError("allowed and blocked capabilities overlap")
    if set(allowed) | set(blocked) != set(requested):
        raise ExternalCapabilityBindingError("requested capability surface must be fully classified")
    endpoint = str(endpoint_ref or "").strip()
    if binding_kind in {"MCP_ENDPOINT", "ADAPTER"}:
        if not endpoint or local_skill_asset_id:
            raise ExternalCapabilityBindingError("external endpoint binding is incomplete")
    elif not local_skill_asset_id:
        raise ExternalCapabilityBindingError("local skill binding requires authorized asset identity")

    unsigned = {
        "binding_kind": binding_kind,
        "endpoint_ref": endpoint,
        "local_skill_asset_id": str(local_skill_asset_id or ""),
        "allowed_capabilities": list(allowed),
        "blocked_capabilities": list(blocked),
        "permission_scope": list(permission_scope),
        "effect_policy": effect_policy,
        "evaluation_evidence_ref": evidence_ref,
    }
    identity_digest = _digest(unsigned)
    stable_asset_identifier = "external-capability:sha256:" + identity_digest
    binding_digest = _digest({**unsigned, "stable_asset_identifier": stable_asset_identifier})
    return ExternalCapabilityBindingV1(
        binding_kind=binding_kind,
        endpoint_ref=endpoint,
        stable_asset_identifier=stable_asset_identifier,
        allowed_capabilities=allowed,
        blocked_capabilities=blocked,
        permission_scope=tuple(str(item) for item in permission_scope),
        effect_policy=effect_policy,
        evaluation_evidence_ref=evidence_ref,
        binding_digest=binding_digest,
    )
