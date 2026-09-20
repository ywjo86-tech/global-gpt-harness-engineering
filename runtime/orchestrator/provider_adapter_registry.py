"""Provider-neutral adapter registry for governed Router decisions.

Registration alone never admits or activates a Provider. Eligibility and selection
remain Router/MPRF authority; this registry only resolves an already-selected
provider identity to an execution adapter.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping

ProviderAdapter = Callable[[Any, Any, str], Mapping[str, Any]]


class ProviderAdapterRegistryError(ValueError):
    pass


class ProviderAdapterRegistry:
    def __init__(self, adapters: Mapping[str, ProviderAdapter]) -> None:
        normalized: dict[str, ProviderAdapter] = {}
        for provider_id, adapter in dict(adapters).items():
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise ProviderAdapterRegistryError("provider adapter identity is invalid")
            if not callable(adapter):
                raise ProviderAdapterRegistryError("provider adapter must be callable")
            normalized[provider_id] = adapter
        self._adapters = MappingProxyType(normalized)

    def resolve(self, provider_id: str) -> ProviderAdapter | None:
        if not isinstance(provider_id, str) or not provider_id:
            return None
        return self._adapters.get(provider_id)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def build_active_provider_adapter_registry(inventory: Any, adapter_factory: Callable[[Any], ProviderAdapter], *, base: Mapping[str, ProviderAdapter] | None = None) -> ProviderAdapterRegistry:
    adapters = dict(base or {})
    for record in inventory.records:
        if record.state == "ACTIVE":
            if record.provider_id in adapters:
                raise ProviderAdapterRegistryError("active provider adapter collision")
            adapters[record.provider_id] = adapter_factory(record)
    return ProviderAdapterRegistry(adapters)
