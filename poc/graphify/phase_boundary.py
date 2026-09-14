from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

FORBIDDEN_OWNERSHIP_PREFIXES = (
    "runtime/orchestrator/",
    "runtime/jarvis_bridge/",
    "runtime/knot_v2/",
)
FORBIDDEN_PHASE_TERMS = (
    "execution_backend_contract_implementation",
    "full_mcp_implementation",
    "ai_office_implementation",
    "jarvis_implementation",
    "project_continuity_memory_implementation",
)


def verify_phase2_scope(
    implementation_targets: Iterable[str],
    declared_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    targets = [Path(value).as_posix().lstrip("./") for value in implementation_targets]
    capabilities = [str(value).strip().lower() for value in declared_capabilities]
    violations: list[str] = []
    for target in targets:
        if target.startswith(FORBIDDEN_OWNERSHIP_PREFIXES):
            violations.append(f"forbidden_phase2_target:{target}")
    for capability in capabilities:
        if capability in FORBIDDEN_PHASE_TERMS:
            violations.append(f"forbidden_phase_capability:{capability}")
    return {
        "record_type": "PhaseBoundaryCheck",
        "implementation_targets": targets,
        "declared_capabilities": capabilities,
        "next_master_phase": "PHASE_3_EXECUTION_BACKEND_CONTRACT_FINALIZATION",
        "violations": violations,
        "verified": not violations,
    }
