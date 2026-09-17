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


class ProviderRouterContractError(ValueError):
    pass


def _canonical_digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderEligibilitySnapshotV1:
    schema_version: str
    snapshot_id: str
    provider_eligible: Mapping[str, bool]
    model_refs: Mapping[str, str]
    evidence_refs: tuple[str, ...] = ()
    failure_classes: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.schema_version != ELIGIBILITY_SCHEMA_V1 or not self.snapshot_id:
            raise ProviderRouterContractError("invalid eligibility snapshot")
        if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in self.provider_eligible):
            raise ProviderRouterContractError("unapproved provider in eligibility snapshot")
        if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in self.model_refs):
            raise ProviderRouterContractError("unapproved provider model binding")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "provider_eligible": dict(self.provider_eligible),
            "model_refs": dict(self.model_refs),
            "evidence_refs": list(self.evidence_refs),
            "failure_classes": dict(self.failure_classes or {}),
        }

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
        if self.stage == "ACTION" and not self.state_change_required:
            raise ProviderRouterContractError("ACTION requires state_change_required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "request_id": self.request_id,
            "project_id": self.project_id, "run_id": self.run_id, "task_id": self.task_id,
            "task_execution_id": self.task_execution_id, "directive_digest": self.directive_digest,
            "stage": self.stage, "required_capabilities": list(self.required_capabilities),
            "state_change_required": self.state_change_required, "policy_profile": self.policy_profile,
            "eligibility_snapshot": self.eligibility_snapshot.to_dict(), "failure_class": self.failure_class,
            "failover_request_ref": self.failover_request_ref,
        }

    @property
    def request_digest(self) -> str:
        return _canonical_digest(self.to_dict())


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

    def __post_init__(self) -> None:
        if self.schema_version != ROUTER_DECISION_SCHEMA_V2:
            raise ProviderRouterContractError("unsupported RouterDecision schema")
        if self.eligible:
            if self.provider_ref not in {NVIDIA_PROVIDER, CODEX_PROVIDER} or not self.model_ref:
                raise ProviderRouterContractError("eligible RouterDecision requires provider/model binding")
        elif self.provider_ref or self.model_ref:
            raise ProviderRouterContractError("blocked RouterDecision cannot bind a provider/model")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "decision_id": self.decision_id,
            "request_digest": self.request_digest, "stage": self.stage,
            "provider_ref": self.provider_ref, "model_ref": self.model_ref,
            "reason_code": self.reason_code, "required_capabilities": list(self.required_capabilities),
            "eligible": self.eligible, "eligibility_evidence_refs": list(self.eligibility_evidence_refs),
            "policy_version": self.policy_version, "action_state": self.action_state,
        }

    @property
    def decision_digest(self) -> str:
        return _canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "decision_digest": self.decision_digest}


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

    reason = "governed_action_to_codex" if provider == CODEX_PROVIDER else "governed_read_stage_to_nvidia"
    action_state = "ACTION_PENDING" if request.stage == "ACTION" else f"{request.stage}_PENDING"
    return RouterDecisionV2(
        schema_version=ROUTER_DECISION_SCHEMA_V2,
        decision_id=f"decision-{request.request_id}", request_digest=request.request_digest,
        stage=request.stage, provider_ref=provider, model_ref=model_ref, reason_code=reason,
        required_capabilities=request.required_capabilities, eligible=True,
        eligibility_evidence_refs=tuple(request.eligibility_snapshot.evidence_refs),
        policy_version=GOVERNED_POLICY_V1, action_state=action_state,
    )
