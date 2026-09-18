from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .execution_modes import CODEX_CLI, HYBRID, MANUAL, MOCK, NVIDIA, normalize_execution_mode


CODEX_PROVIDER = "codex"
LOCAL_PROVIDER = "local"
MANUAL_PROVIDER = "manual"
NVIDIA_PROVIDER = "nvidia"


@dataclass(frozen=True, slots=True)
class ProviderRouteDecision:
    provider: str
    mode: str
    reason_code: str
    required_capabilities: tuple[str, ...]
    eligible: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


STATE_CHANGING_CAPABILITIES = frozenset(
    {"filesystem_write", "shell", "test", "test_execution", "git", "implementation",
     "implementation_apply", "integration", "activation"}
)
READ_ONLY_CAPABILITIES = frozenset(
    {"read_only", "reasoning", "evidence_analysis", "code_generation", "patch_generation",
     "test_design", "implementation_generation", "review", "diagnostics", "documentation", "security_review"}
)


def route_provider(mode: str | None, required_capabilities: Iterable[str] | None) -> ProviderRouteDecision:
    normalized_mode = normalize_execution_mode(mode)
    capabilities = tuple(sorted({str(item).strip() for item in (required_capabilities or ()) if str(item).strip()}))
    has_state_change = bool(STATE_CHANGING_CAPABILITIES.intersection(capabilities))
    read_only = "read_only" in capabilities and not has_state_change

    if normalized_mode == MOCK:
        return ProviderRouteDecision(LOCAL_PROVIDER, normalized_mode, "mode_mock_local", capabilities, True)
    if normalized_mode == MANUAL:
        return ProviderRouteDecision(MANUAL_PROVIDER, normalized_mode, "mode_manual", capabilities, True)
    if normalized_mode == CODEX_CLI:
        return ProviderRouteDecision(CODEX_PROVIDER, normalized_mode, "mode_codex_cli", capabilities, True)
    if normalized_mode == NVIDIA:
        if read_only:
            return ProviderRouteDecision(NVIDIA_PROVIDER, normalized_mode, "nvidia_read_only", capabilities, True)
        return ProviderRouteDecision(MANUAL_PROVIDER, normalized_mode, "nvidia_rejects_state_changing", capabilities, False)
    if normalized_mode == HYBRID:
        if read_only:
            return ProviderRouteDecision(NVIDIA_PROVIDER, normalized_mode, "hybrid_read_only_to_nvidia", capabilities, True)
        return ProviderRouteDecision(CODEX_PROVIDER, normalized_mode, "hybrid_state_changing_to_codex", capabilities, True)
    raise ValueError(f"Unsupported execution mode: {mode}")


ROUTER_REQUEST_SCHEMA_V2 = "orchestration.router-request.v2"
ROUTER_DECISION_SCHEMA_V2 = "orchestration.router-decision.v2"
ELIGIBILITY_SCHEMA_V1 = "orchestration.provider-eligibility-snapshot.v1"
GOVERNED_POLICY_V1 = "NVIDIA_PRIMARY_CODEX_SECONDARY_V1"
ROUTER_REQUEST_SOURCE_V2 = "governed_v2"
LEGACY_REQUEST_SOURCE_V1 = "legacy_v1_mode_capabilities"
MPRF_REROUTE_SOURCE_V1 = "mprf_reroute_v1"

FAILURE_CLASSES_V1 = frozenset({
    "TASK_FAILURE", "MODEL_FAILURE", "PROVIDER_FAILURE", "AUTH_FAILURE", "RATE_LIMIT",
    "QUOTA_EXHAUSTION", "NETWORK_FAILURE", "INVALID_RESPONSE", "POLICY_REJECTION",
    "CHECKPOINT_FAILURE", "EXECUTION_BACKEND_FAILURE", "ACTION_SIDE_EFFECT_AMBIGUOUS",
    "RECOVERY_REQUIRED", "UNKNOWN_FAILURE",
})
REROUTE_ELIGIBLE_FAILURE_CLASSES_V1 = frozenset({
    "MODEL_FAILURE", "PROVIDER_FAILURE", "RATE_LIMIT", "QUOTA_EXHAUSTION", "NETWORK_FAILURE",
})
LEGACY_CAPABILITY_ALIASES_V2 = {
    "test": "test_execution",
    "implementation": "implementation_apply",
}


class ProviderRouterContractError(ValueError):
    pass


def _canonical_digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def normalize_capabilities_v2(required_capabilities: Iterable[str] | None) -> tuple[str, ...]:
    normalized: set[str] = set()
    for item in required_capabilities or ():
        capability = str(item).strip()
        if not capability:
            continue
        normalized.add(LEGACY_CAPABILITY_ALIASES_V2.get(capability, capability))
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class ProviderEligibilitySnapshotV1:
    schema_version: str
    snapshot_id: str
    provider_eligible: Mapping[str, bool]
    model_refs: Mapping[str, str]
    evidence_refs: tuple[str, ...] = ()
    failure_classes: Mapping[str, str] | None = None
    model_fallback_refs: Mapping[str, tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        if self.schema_version != ELIGIBILITY_SCHEMA_V1 or not self.snapshot_id:
            raise ProviderRouterContractError("invalid eligibility snapshot")
        if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in self.provider_eligible):
            raise ProviderRouterContractError("unapproved provider in eligibility snapshot")
        if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in self.model_refs):
            raise ProviderRouterContractError("unapproved provider model binding")
        fallbacks = self.model_fallback_refs or {}
        if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in fallbacks):
            raise ProviderRouterContractError("unapproved provider fallback binding")
        for provider, refs in fallbacks.items():
            normalized = tuple(str(ref).strip() for ref in refs)
            if any(not ref for ref in normalized) or len(normalized) != len(set(normalized)):
                raise ProviderRouterContractError("invalid provider fallback model binding")
            primary = str(self.model_refs.get(provider, "")).strip()
            if primary and primary in normalized:
                raise ProviderRouterContractError("primary model cannot repeat in fallback binding")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "provider_eligible": dict(self.provider_eligible),
            "model_refs": dict(self.model_refs),
            "evidence_refs": list(self.evidence_refs),
            "failure_classes": dict(self.failure_classes or {}),
        }
        if self.model_fallback_refs:
            payload["model_fallback_refs"] = {
                provider: list(refs) for provider, refs in self.model_fallback_refs.items() if refs
            }
        return payload

    @property
    def snapshot_digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class RouterRequestV2:
    schema_version: str
    request_id: str
    project_id: str
    run_id: str
    task_id: str
    task_execution_id: str
    directive_digest: str
    stage: str
    required_capabilities: tuple[str, ...]
    state_change_required: bool
    policy_profile: str
    eligibility_snapshot: ProviderEligibilitySnapshotV1
    eligibility_snapshot_ref: str = ""
    eligibility_snapshot_digest: str = ""
    request_source: str = ROUTER_REQUEST_SOURCE_V2
    failure_class: str = ""
    failover_request_ref: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != ROUTER_REQUEST_SCHEMA_V2:
            raise ProviderRouterContractError("unsupported RouterRequest schema")
        if not all((self.request_id, self.project_id, self.run_id, self.task_id, self.task_execution_id, self.directive_digest)):
            raise ProviderRouterContractError("RouterRequest identity is incomplete")
        if self.stage not in {"PREPARE", "ACTION", "VERIFY", "REVIEW"}:
            raise ProviderRouterContractError("RouterRequest stage is invalid")
        if self.policy_profile != GOVERNED_POLICY_V1:
            raise ProviderRouterContractError("RouterRequest policy is unsupported")
        if self.request_source not in {ROUTER_REQUEST_SOURCE_V2, LEGACY_REQUEST_SOURCE_V1, MPRF_REROUTE_SOURCE_V1}:
            raise ProviderRouterContractError("RouterRequest source is unsupported")
        normalized_capabilities = normalize_capabilities_v2(self.required_capabilities)
        object.__setattr__(self, "required_capabilities", normalized_capabilities)
        if self.stage == "ACTION" and not self.state_change_required:
            raise ProviderRouterContractError("ACTION requires state_change_required")
        if self.failure_class and self.failure_class not in FAILURE_CLASSES_V1:
            raise ProviderRouterContractError("unknown FailureClass.v1 value")
        if self.failover_request_ref and not self.failure_class:
            raise ProviderRouterContractError("failover request requires failure_class")
        if not self.eligibility_snapshot_ref:
            object.__setattr__(self, "eligibility_snapshot_ref", self.eligibility_snapshot.snapshot_id)
        if not self.eligibility_snapshot_digest:
            object.__setattr__(self, "eligibility_snapshot_digest", self.eligibility_snapshot.snapshot_digest)

    @property
    def eligibility_binding_valid(self) -> bool:
        return (
            self.eligibility_snapshot_ref == self.eligibility_snapshot.snapshot_id
            and self.eligibility_snapshot_digest == self.eligibility_snapshot.snapshot_digest
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "request_id": self.request_id,
            "project_id": self.project_id, "run_id": self.run_id, "task_id": self.task_id,
            "task_execution_id": self.task_execution_id, "directive_digest": self.directive_digest,
            "stage": self.stage, "required_capabilities": list(self.required_capabilities),
            "state_change_required": self.state_change_required, "policy_profile": self.policy_profile,
            "eligibility_snapshot_ref": self.eligibility_snapshot_ref,
            "eligibility_snapshot_digest": self.eligibility_snapshot_digest,
            "eligibility_snapshot": self.eligibility_snapshot.to_dict(),
            "request_source": self.request_source, "failure_class": self.failure_class,
            "failover_request_ref": self.failover_request_ref,
        }

    @property
    def request_digest(self) -> str:
        return _canonical_digest(self.to_dict())


def normalize_legacy_hybrid_request(
    *,
    required_capabilities: Iterable[str] | None,
    eligibility_snapshot: ProviderEligibilitySnapshotV1,
    request_id: str,
    project_id: str,
    run_id: str,
    task_id: str,
    task_execution_id: str,
    directive_digest: str,
    policy_profile: str = GOVERNED_POLICY_V1,
) -> RouterRequestV2:
    """Normalize the legacy HYBRID capability contract into RouterRequest.v2 without failure context."""
    capabilities = normalize_capabilities_v2(required_capabilities)
    state_change_required = bool(STATE_CHANGING_CAPABILITIES.intersection(capabilities))
    stage = "ACTION" if state_change_required else "PREPARE"
    return RouterRequestV2(
        schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id=request_id, project_id=project_id, run_id=run_id,
        task_id=task_id, task_execution_id=task_execution_id, directive_digest=directive_digest, stage=stage,
        required_capabilities=capabilities, state_change_required=state_change_required,
        policy_profile=policy_profile, eligibility_snapshot=eligibility_snapshot,
        request_source=LEGACY_REQUEST_SOURCE_V1, failure_class="", failover_request_ref="",
    )


@dataclass(frozen=True, slots=True)
class RouterDecisionV2:
    schema_version: str
    decision_id: str
    request_digest: str
    stage: str
    provider_ref: str
    model_ref: str
    reason_code: str
    required_capabilities: tuple[str, ...]
    eligible: bool
    eligibility_evidence_refs: tuple[str, ...]
    policy_version: str
    action_state: str
    model_fallback_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != ROUTER_DECISION_SCHEMA_V2:
            raise ProviderRouterContractError("unsupported RouterDecision schema")
        if self.eligible:
            if self.provider_ref not in {NVIDIA_PROVIDER, CODEX_PROVIDER} or not self.model_ref:
                raise ProviderRouterContractError("eligible RouterDecision requires provider/model binding")
        elif self.provider_ref or self.model_ref:
            raise ProviderRouterContractError("blocked RouterDecision cannot bind a provider/model")
        if self.model_fallback_refs and self.provider_ref != NVIDIA_PROVIDER:
            raise ProviderRouterContractError("model failover is only approved inside NVIDIA provider")
        if len(self.model_fallback_refs) != len(set(self.model_fallback_refs)):
            raise ProviderRouterContractError("duplicate RouterDecision fallback model")
        if self.model_ref and self.model_ref in self.model_fallback_refs:
            raise ProviderRouterContractError("RouterDecision fallback repeats primary model")

    def unsigned_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version, "decision_id": self.decision_id,
            "request_digest": self.request_digest, "stage": self.stage,
            "provider_ref": self.provider_ref, "model_ref": self.model_ref,
            "reason_code": self.reason_code, "required_capabilities": list(self.required_capabilities),
            "eligible": self.eligible, "eligibility_evidence_refs": list(self.eligibility_evidence_refs),
            "policy_version": self.policy_version, "action_state": self.action_state,
        }
        if self.model_fallback_refs:
            payload["model_fallback_refs"] = list(self.model_fallback_refs)
        return payload

    @property
    def decision_digest(self) -> str:
        return _canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "decision_digest": self.decision_digest}


def eligibility_snapshot_from_mapping(value: Mapping[str, Any]) -> ProviderEligibilitySnapshotV1:
    if not isinstance(value, Mapping):
        raise ProviderRouterContractError("eligibility snapshot mapping is invalid")
    raw_fallbacks = value.get("model_fallback_refs", {})
    if raw_fallbacks is None:
        raw_fallbacks = {}
    if not isinstance(raw_fallbacks, Mapping):
        raise ProviderRouterContractError("eligibility fallback mapping is invalid")
    return ProviderEligibilitySnapshotV1(
        schema_version=str(value.get("schema_version", "")),
        snapshot_id=str(value.get("snapshot_id", "")),
        provider_eligible=dict(value.get("provider_eligible", {})),
        model_refs=dict(value.get("model_refs", {})),
        evidence_refs=tuple(value.get("evidence_refs", ())),
        failure_classes=dict(value.get("failure_classes", {})),
        model_fallback_refs={
            str(provider): tuple(refs)
            for provider, refs in raw_fallbacks.items()
        } or None,
    )


def router_request_from_mapping(value: Mapping[str, Any]) -> RouterRequestV2:
    if not isinstance(value, Mapping) or not isinstance(value.get("eligibility_snapshot"), Mapping):
        raise ProviderRouterContractError("Router request mapping is invalid")
    snapshot = eligibility_snapshot_from_mapping(value["eligibility_snapshot"])
    return RouterRequestV2(
        schema_version=str(value.get("schema_version", "")),
        request_id=str(value.get("request_id", "")),
        project_id=str(value.get("project_id", "")),
        run_id=str(value.get("run_id", "")),
        task_id=str(value.get("task_id", "")),
        task_execution_id=str(value.get("task_execution_id", "")),
        directive_digest=str(value.get("directive_digest", "")),
        stage=str(value.get("stage", "")),
        required_capabilities=tuple(value.get("required_capabilities", ())),
        state_change_required=bool(value.get("state_change_required")),
        policy_profile=str(value.get("policy_profile", "")),
        eligibility_snapshot=snapshot,
        eligibility_snapshot_ref=str(value.get("eligibility_snapshot_ref", "")),
        eligibility_snapshot_digest=str(value.get("eligibility_snapshot_digest", "")),
        request_source=str(value.get("request_source", ROUTER_REQUEST_SOURCE_V2)),
        failure_class=str(value.get("failure_class", "")),
        failover_request_ref=str(value.get("failover_request_ref", "")),
    )


def validate_router_envelope(value: Mapping[str, Any]) -> tuple[RouterRequestV2, RouterDecisionV2]:
    if not isinstance(value, Mapping) or set(value) != {"request", "decision"}:
        raise ProviderRouterContractError("provider route envelope is invalid")
    request = router_request_from_mapping(value["request"])
    supplied = value["decision"]
    if not isinstance(supplied, Mapping):
        raise ProviderRouterContractError("provider route decision is invalid")
    decision = route_request(request)
    if dict(supplied) != decision.to_dict():
        raise ProviderRouterContractError("provider route decision is not canonical")
    return request, decision


def _blocked_decision(request: RouterRequestV2, reason: str, state: str) -> RouterDecisionV2:
    return RouterDecisionV2(
        schema_version=ROUTER_DECISION_SCHEMA_V2,
        decision_id=f"decision-{request.request_id}", request_digest=request.request_digest,
        stage=request.stage, provider_ref="", model_ref="", reason_code=reason,
        required_capabilities=request.required_capabilities, eligible=False,
        eligibility_evidence_refs=tuple(request.eligibility_snapshot.evidence_refs),
        policy_version=GOVERNED_POLICY_V1, action_state=state,
    )


def route_request(request: RouterRequestV2) -> RouterDecisionV2:
    """Governed HYBRID route. Selection authority lives here and never in a task/adapter."""
    if not request.eligibility_binding_valid:
        state = "ACTION_PROVIDER_BLOCKED" if request.stage == "ACTION" else "ROUTE_BLOCKED"
        return _blocked_decision(request, "eligibility_snapshot_binding_mismatch", state)

    if request.failover_request_ref:
        if request.failure_class not in REROUTE_ELIGIBLE_FAILURE_CLASSES_V1:
            state = "ACTION_PROVIDER_BLOCKED" if request.stage == "ACTION" else "ROUTE_BLOCKED"
            return _blocked_decision(request, "reroute_failure_class_prohibited", state)
        # TASK-002 accepts and validates future MPRF reroute context, but does not
        # implement provider lifecycle/failover policy. TASK-012 activates reroute
        # only after checkpoint/artifact/effect/auth/policy prerequisites exist.
        state = "ACTION_PROVIDER_BLOCKED" if request.stage == "ACTION" else "ROUTE_BLOCKED"
        return _blocked_decision(request, "reroute_policy_not_activated_pre_mprf", state)

    if request.stage == "ACTION":
        provider = CODEX_PROVIDER
        blocked_state = "ACTION_PROVIDER_BLOCKED"
    else:
        provider = NVIDIA_PROVIDER
        blocked_state = "ROUTE_BLOCKED"

    if not bool(request.eligibility_snapshot.provider_eligible.get(provider, False)):
        reason = "action_provider_unavailable" if request.stage == "ACTION" else "read_provider_unavailable"
        return _blocked_decision(request, reason, blocked_state)
    model_ref = str(request.eligibility_snapshot.model_refs.get(provider, "")).strip()
    if not model_ref:
        return _blocked_decision(request, "router_model_binding_missing", blocked_state)

    if request.stage != "ACTION" and STATE_CHANGING_CAPABILITIES.intersection(request.required_capabilities):
        return _blocked_decision(request, "state_change_capability_outside_action_stage", "ROUTE_BLOCKED")
    if request.stage == "ACTION" and not STATE_CHANGING_CAPABILITIES.intersection(request.required_capabilities):
        return _blocked_decision(request, "action_stage_without_state_change_capability", "ACTION_PROVIDER_BLOCKED")

    fallback_refs = tuple((request.eligibility_snapshot.model_fallback_refs or {}).get(provider, ()))
    reason = "governed_action_to_codex" if provider == CODEX_PROVIDER else "governed_read_stage_to_nvidia"
    action_state = "ACTION_PENDING" if request.stage == "ACTION" else f"{request.stage}_PENDING"
    return RouterDecisionV2(
        schema_version=ROUTER_DECISION_SCHEMA_V2,
        decision_id=f"decision-{request.request_id}", request_digest=request.request_digest,
        stage=request.stage, provider_ref=provider, model_ref=model_ref, reason_code=reason,
        required_capabilities=request.required_capabilities, eligible=True,
        eligibility_evidence_refs=tuple(request.eligibility_snapshot.evidence_refs),
        policy_version=GOVERNED_POLICY_V1, action_state=action_state,
        model_fallback_refs=fallback_refs,
    )
