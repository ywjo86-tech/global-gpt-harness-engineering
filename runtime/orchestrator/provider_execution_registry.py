"""Provider-neutral execution profile and runner registry.

Router selects provider/model and projects an execution profile. This module only
maps that already-selected profile to an execution mechanism and resolves an
already-selected provider to a registered read/action runner. It has no routing,
approval, or effect authority.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping

from .production_execution_gateway import HOST_GATEWAY
from .provider_action_execution import PROVIDER_ACTION_BACKEND
from .provider_router import (
    EXECUTION_PROFILE_NATIVE_TOOL,
    EXECUTION_PROFILE_PROVIDER_GENERATION,
    RouterDecisionV2,
    RouterRequestV2,
)

PROVIDER_READ_ONLY_BACKEND = "PROVIDER_READ_ONLY"
ProviderRunner = Callable[..., Mapping[str, Any]]


class ProviderExecutionRegistryError(ValueError):
    pass


class ProviderRunnerRegistry:
    def __init__(self, *, read_runners: Mapping[str, ProviderRunner] | None = None,
                 action_runners: Mapping[str, ProviderRunner] | None = None) -> None:
        self._read = MappingProxyType(self._normalize(read_runners or {}))
        self._action = MappingProxyType(self._normalize(action_runners or {}))

    @staticmethod
    def _normalize(values: Mapping[str, ProviderRunner]) -> dict[str, ProviderRunner]:
        out: dict[str, ProviderRunner] = {}
        for provider_id, runner in dict(values).items():
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise ProviderExecutionRegistryError("provider runner identity is invalid")
            if not callable(runner):
                raise ProviderExecutionRegistryError("provider runner must be callable")
            out[provider_id.strip()] = runner
        return out

    def resolve_read(self, provider_id: str) -> ProviderRunner | None:
        return self._read.get(str(provider_id))

    def resolve_action(self, provider_id: str) -> ProviderRunner | None:
        return self._action.get(str(provider_id))


def execution_backend_for_route(request: RouterRequestV2, decision: RouterDecisionV2) -> str:
    if not decision.eligible or decision.request_digest != request.request_digest:
        raise ProviderExecutionRegistryError("eligible bound Router decision is required")
    if decision.execution_profile == EXECUTION_PROFILE_NATIVE_TOOL:
        return HOST_GATEWAY
    if decision.execution_profile != EXECUTION_PROFILE_PROVIDER_GENERATION:
        raise ProviderExecutionRegistryError("Router execution profile is missing or invalid")
    return PROVIDER_ACTION_BACKEND if decision.stage == "ACTION" else PROVIDER_READ_ONLY_BACKEND


def build_active_provider_runner_registry(inventory: Any, runner_factory: Callable[[Any], ProviderRunner], *, base_read: Mapping[str, ProviderRunner] | None = None, base_action: Mapping[str, ProviderRunner] | None = None) -> ProviderRunnerRegistry:
    read = dict(base_read or {}); action = dict(base_action or {})
    for record in inventory.records:
        if record.state == "ACTIVE":
            if record.provider_id in read or record.provider_id in action:
                raise ProviderExecutionRegistryError("active provider runner collision")
            runner = runner_factory(record)
            read[record.provider_id] = runner; action[record.provider_id] = runner
    return ProviderRunnerRegistry(read_runners=read, action_runners=action)
