from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .execution_modes import CODEX_CLI, HYBRID, MANUAL, MOCK, NVIDIA, normalize_execution_mode


CODEX_PROVIDER = "codex"
LOCAL_PROVIDER = "local"
MANUAL_PROVIDER = "manual"
NVIDIA_PROVIDER = "nvidia"
BUILTIN_PROVIDER_IDS = frozenset({CODEX_PROVIDER, NVIDIA_PROVIDER})
_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _valid_provider_id(value: object) -> bool:
    return isinstance(value, str) and _PROVIDER_ID.fullmatch(value) is not None


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
        return ProviderRouteDecision(
            MANUAL_PROVIDER, normalized_mode, "hybrid_state_change_requires_governed_router", capabilities, False
        )
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
EXECUTION_PROFILE_NATIVE_TOOL = "NATIVE_TOOL"
EXECUTION_PROFILE_PROVIDER_GENERATION = "PROVIDER_GENERATION"
EXECUTION_PROFILES_V1 = frozenset({EXECUTION_PROFILE_NATIVE_TOOL, EXECUTION_PROFILE_PROVIDER_GENERATION})

REROUTE_ELIGIBLE_FAILURE_CLASSES_V1 = frozenset({
    "MODEL_FAILURE", "PROVIDER_FAILURE", "RATE_LIMIT", "QUOTA_EXHAUSTION", "NETWORK_FAILURE",
    "INVALID_RESPONSE",
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
    provider_capabilities: Mapping[str, tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        if self.schema_version != ELIGIBILITY_SCHEMA_V1 or not self.snapshot_id:
            raise ProviderRouterContractError("invalid eligibility snapshot")
        if any(not _valid_provider_id(provider) for provider in self.provider_eligible):
            raise ProviderRouterContractError("invalid provider in eligibility snapshot")
        if any(not _valid_provider_id(provider) for provider in self.model_refs):
            raise ProviderRouterContractError("invalid provider model binding")
        fallbacks = self.model_fallback_refs or {}
        provider_caps = self.provider_capabilities or {}
        if any(not _valid_provider_id(provider) for provider in provider_caps):
            raise ProviderRouterContractError("invalid provider capability binding")
        for provider, refs in provider_caps.items():
            normalized_caps = tuple(sorted({str(ref).strip() for ref in refs if str(ref).strip()}))
            if not normalized_caps or len(normalized_caps) != len(tuple(refs)):
                raise ProviderRouterContractError("invalid provider capability binding")
        if any(not _valid_provider_id(provider) for provider in fallbacks):
            raise ProviderRouterContractError("invalid provider fallback binding")
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
        if self.provider_capabilities:
            payload["provider_capabilities"] = {
                provider: list(refs) for provider, refs in self.provider_capabilities.items() if refs
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
    failed_provider_ref: str = ""
    failed_model_ref: str = ""

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
        if self.failover_request_ref and self.request_source != MPRF_REROUTE_SOURCE_V1:
            raise ProviderRouterContractError("failover request requires MPRF reroute source")
        if self.request_source == MPRF_REROUTE_SOURCE_V1:
            if not self.failover_request_ref or not _valid_provider_id(self.failed_provider_ref) or not self.failed_model_ref:
                raise ProviderRouterContractError("MPRF reroute requires failed provider/model binding")
        elif self.failed_provider_ref or self.failed_model_ref:
            raise ProviderRouterContractError("failed provider/model binding requires MPRF reroute source")
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
            "failed_provider_ref": self.failed_provider_ref, "failed_model_ref": self.failed_model_ref,
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
    execution_profile: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != ROUTER_DECISION_SCHEMA_V2:
            raise ProviderRouterContractError("unsupported RouterDecision schema")
        if self.eligible:
            if not _valid_provider_id(self.provider_ref) or not self.model_ref:
                raise ProviderRouterContractError("eligible RouterDecision requires provider/model binding")
        elif self.provider_ref or self.model_ref:
            raise ProviderRouterContractError("blocked RouterDecision cannot bind a provider/model")
        if len(self.model_fallback_refs) != len(set(self.model_fallback_refs)):
            raise ProviderRouterContractError("duplicate RouterDecision fallback model")
        if self.model_ref and self.model_ref in self.model_fallback_refs:
            raise ProviderRouterContractError("RouterDecision fallback repeats primary model")
        if self.execution_profile and self.execution_profile not in EXECUTION_PROFILES_V1:
            raise ProviderRouterContractError("RouterDecision execution profile is invalid")

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
        if self.execution_profile:
            payload["execution_profile"] = self.execution_profile
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
        provider_capabilities={
            str(provider): tuple(refs) for provider, refs in dict(value.get("provider_capabilities", {})).items()
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
        failed_provider_ref=str(value.get("failed_provider_ref", "")),
        failed_model_ref=str(value.get("failed_model_ref", "")),
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


EFFECT_ONLY_CAPABILITIES = frozenset({"filesystem_write", "shell", "git", "activation"})
ACTION_GENERATION_ALIASES = {
    "implementation_apply": "implementation_generation",
    "test_execution": "test_design",
}
ACTION_PROPOSAL_CAPABILITY = "patch_generation"


def provider_generation_requirements(request: RouterRequestV2) -> tuple[str, ...]:
    """Translate task/effect requirements into model-generation capabilities.

    Effect authority (write/shell/git/activation) belongs to Execution Backend,
    never to the selected model. ACTION providers only need to generate a
    bounded proposal for those effects.
    """
    required: set[str] = set()
    for capability in request.required_capabilities:
        if capability in EFFECT_ONLY_CAPABILITIES:
            continue
        required.add(ACTION_GENERATION_ALIASES.get(capability, capability))
    if request.stage == "ACTION":
        required.add(ACTION_PROPOSAL_CAPABILITY)
    return tuple(sorted(required))


def _legacy_provider_capabilities(provider: str) -> frozenset[str]:
    # Only the sealed built-in legacy snapshots receive implicit capabilities.
    # Any newly admitted provider must carry an explicit capability projection.
    if provider not in BUILTIN_PROVIDER_IDS:
        return frozenset()
    base = set(READ_ONLY_CAPABILITIES) | {"integration", "implementation_generation", "test_design"}
    if provider == NVIDIA_PROVIDER:
        base.discard(ACTION_PROPOSAL_CAPABILITY)
    if provider == CODEX_PROVIDER:
        base.add(ACTION_PROPOSAL_CAPABILITY)
    return frozenset(base)


def _provider_capability_set(snapshot: ProviderEligibilitySnapshotV1, provider: str) -> frozenset[str]:
    supplied = (snapshot.provider_capabilities or {}).get(provider)
    return frozenset(supplied) if supplied else _legacy_provider_capabilities(provider)


def _select_provider(request: RouterRequestV2) -> tuple[str, str] | None:
    required = set(provider_generation_requirements(request))
    candidates: list[tuple[str, str, str]] = []
    for provider, eligible in request.eligibility_snapshot.provider_eligible.items():
        if not bool(eligible):
            continue
        model = str(request.eligibility_snapshot.model_refs.get(provider, "")).strip()
        if not model:
            continue
        capabilities = _provider_capability_set(request.eligibility_snapshot, provider)
        if not required.issubset(capabilities):
            continue
        # Candidate identity is never a priority key. All eligible/capable
        # candidates are ranked by a request-bound cryptographic digest so the
        # result is deterministic without Codex/NVIDIA/capability-count/lexical bias.
        material = f"{request.request_digest}:{provider}:{model}".encode("utf-8")
        candidates.append((hashlib.sha256(material).hexdigest(), provider, model))
    if not candidates:
        return None
    best_rank = min(rank for rank, _, _ in candidates)
    winners = [(provider, model) for rank, provider, model in candidates if rank == best_rank]
    if len(winners) != 1:
        return None
    return winners[0]


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

    reroute = bool(request.failover_request_ref)
    if reroute:
        state = "ACTION_PROVIDER_BLOCKED" if request.stage == "ACTION" else "ROUTE_BLOCKED"
        if request.failure_class not in REROUTE_ELIGIBLE_FAILURE_CLASSES_V1:
            return _blocked_decision(request, "reroute_failure_class_prohibited", state)
        failed_still_eligible = bool(request.eligibility_snapshot.provider_eligible.get(request.failed_provider_ref, False))
        failed_model = str(request.eligibility_snapshot.model_refs.get(request.failed_provider_ref, "")).strip()
        if failed_still_eligible and failed_model == request.failed_model_ref:
            return _blocked_decision(request, "reroute_failed_provider_not_excluded", state)

    blocked_state = "ACTION_PROVIDER_BLOCKED" if request.stage == "ACTION" else "ROUTE_BLOCKED"
    if request.stage != "ACTION" and STATE_CHANGING_CAPABILITIES.intersection(request.required_capabilities):
        return _blocked_decision(request, "state_change_capability_outside_action_stage", "ROUTE_BLOCKED")
    if request.stage == "ACTION" and not STATE_CHANGING_CAPABILITIES.intersection(request.required_capabilities):
        return _blocked_decision(request, "action_stage_without_state_change_capability", "ACTION_PROVIDER_BLOCKED")

    selected = _select_provider(request)
    if selected is None:
        any_runtime = any(bool(value) for value in request.eligibility_snapshot.provider_eligible.values())
        if not any_runtime:
            reason = "action_provider_unavailable" if request.stage == "ACTION" else "read_provider_unavailable"
        else:
            reason = "provider_capability_mismatch"
        return _blocked_decision(request, reason, blocked_state)
    provider, model_ref = selected
    if reroute and provider == request.failed_provider_ref and model_ref == request.failed_model_ref:
        return _blocked_decision(request, "reroute_failed_candidate_reselected", blocked_state)
    fallback_refs = tuple((request.eligibility_snapshot.model_fallback_refs or {}).get(provider, ()))
    reason = (
        "governed_reroute_by_neutral_rank" if reroute else
        "governed_action_by_neutral_rank" if request.stage == "ACTION" else "governed_read_by_neutral_rank"
    )
    action_state = "ACTION_PENDING" if request.stage == "ACTION" else f"{request.stage}_PENDING"
    provider_caps = set((request.eligibility_snapshot.provider_capabilities or {}).get(provider, ()))
    execution_profile = (
        EXECUTION_PROFILE_NATIVE_TOOL if "native_tool_action" in provider_caps
        else EXECUTION_PROFILE_PROVIDER_GENERATION
    )
    return RouterDecisionV2(
        schema_version=ROUTER_DECISION_SCHEMA_V2,
        decision_id=f"decision-{request.request_id}", request_digest=request.request_digest,
        stage=request.stage, provider_ref=provider, model_ref=model_ref, reason_code=reason,
        required_capabilities=request.required_capabilities, eligible=True,
        eligibility_evidence_refs=tuple(request.eligibility_snapshot.evidence_refs),
        policy_version=GOVERNED_POLICY_V1, action_state=action_state,
        model_fallback_refs=fallback_refs, execution_profile=execution_profile,
    )
