from __future__ import annotations

from typing import Any, Iterable

from .contracts import CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES

FORBIDDEN_CAPABILITIES = {
    "memory_persistence",
    "project_continuity",
    "workflow_governance",
    "execution_runtime_state",
    "execution_backend_control",
    "context_assembly",
}


def verify_current_repository_boundary(capabilities: Iterable[str]) -> dict[str, Any]:
    requested = {str(value).strip() for value in capabilities if str(value).strip()}
    allowed = set(CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES)
    unsupported = sorted(requested - allowed)
    forbidden = sorted(requested.intersection(FORBIDDEN_CAPABILITIES))
    return {
        "record_type": "CurrentRepositoryIntelligenceBoundaryResult",
        "requested_capabilities": sorted(requested),
        "allowed_capabilities": sorted(allowed),
        "unsupported_capabilities": unsupported,
        "forbidden_capabilities": forbidden,
        "verified": not unsupported and not forbidden,
    }
