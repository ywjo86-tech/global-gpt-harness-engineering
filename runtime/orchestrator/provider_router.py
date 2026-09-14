from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

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


STATE_CHANGING_CAPABILITIES = frozenset({"filesystem_write", "shell", "test", "git"})


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
