from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .lv_execution_package import canonical_json_bytes
from .project_isolation import AssetManifest, ProjectIsolation, route_assets
from .schemas import CapabilityRequirement, DiscoveryStatus
from .skill_discovery import (
    DiscoveryAdapterResult,
    DiscoveryRequest,
    DiscoveryTransportContract,
    HTTPDiscoveryResponse,
    TRUSTED_DISCOVERY_TRANSPORTS,
    run_http_read_only_discovery,
)


class CapabilityInventoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityInventoryResult:
    phase: str
    authoritative: bool
    requirements: tuple[CapabilityRequirement, ...]
    existing_assets: Mapping[str, str]
    gaps: tuple[str, ...]
    evidence: Mapping[str, Any]
    evidence_reference: str

    @property
    def discovery_required(self) -> bool:
        return bool(self.gaps)

    def ledger_projection(self) -> dict[str, Any]:
        return {
            "capability_requirements": [item.capability_id for item in self.requirements],
            "capability_gaps": list(self.gaps),
            "discovery_required": self.discovery_required,
            "capability_inventory_evidence_references": [self.evidence_reference],
        }


@dataclass(frozen=True, slots=True)
class LazyDiscoveryResult:
    decision: str
    inventory: CapabilityInventoryResult
    discovery: DiscoveryAdapterResult | None
    used_assets: tuple[str, ...]
    gate_state_preserved: bool

    def ledger_projection(self) -> dict[str, Any]:
        value = self.inventory.ledger_projection()
        value.update({
            "used_assets": list(self.used_assets),
            "discovered_candidates": [],
            "evaluated_candidates": [],
            "selected_candidate": "",
            "candidate_use_authorized": False,
            "discovery_evidence_references": [],
            "evaluation_evidence_references": [],
        })
        if self.discovery is not None:
            discovery = self.discovery.ledger_projection()
            discovery.pop("selection_rationale", None)
            value.update(discovery)
            value["used_assets"] = list(self.used_assets)
        return value


def _persist(isolation: ProjectIsolation | None, evidence: Mapping[str, Any]) -> str:
    digest = str(evidence["evidence_digest"])
    if isolation is None:
        return f"sha256:{digest}"
    relative = f"capability-inventory/{digest}.json"
    isolation.write_exclusive("artifact", relative, canonical_json_bytes(evidence))
    return f"artifact/{relative}"


def _validate_requirements(
    requirements: Sequence[CapabilityRequirement], *, project_id: str,
    canonical_plan_sha256: str, gate_lvs: Mapping[str, Sequence[str]], phase: str,
) -> tuple[CapabilityRequirement, ...]:
    if phase not in {"GATE0_FORECAST", "GATE_TIME"}:
        raise CapabilityInventoryError("unknown capability inventory phase")
    if len(canonical_plan_sha256) != 64 or any(char not in "0123456789abcdef" for char in canonical_plan_sha256):
        raise CapabilityInventoryError("canonical plan binding is invalid")
    values = tuple(requirements)
    expected = {(gate, lv) for gate, lvs in gate_lvs.items() for lv in lvs}
    actual = {(item.gate_id, item.lv_id) for item in values}
    if not values or (phase == "GATE0_FORECAST" and actual != expected) or (phase == "GATE_TIME" and not actual.issubset(expected)):
        raise CapabilityInventoryError("Full Plan capability requirements are incomplete")
    if len({(item.gate_id, item.lv_id, item.capability_id) for item in values}) != len(values):
        raise CapabilityInventoryError("capability requirement is duplicated")
    if not project_id:
        raise CapabilityInventoryError("project identity is missing")
    return values


def _exact_existing(
    requirement: CapabilityRequirement, *, project_assets: Sequence[AssetManifest],
    global_assets: Sequence[AssetManifest], agent_registry: Mapping[str, object],
) -> str:
    request = dict(
        capabilities={requirement.capability_id},
        permissions=set(requirement.required_permissions),
        owned_files=requirement.owned_files,
    )
    project = route_assets(project_assets, **request)["selected"]
    if project:
        return project[0]
    global_matches = route_assets(global_assets, **request)["selected"]
    if global_matches:
        return global_matches[0]
    return requirement.capability_id if requirement.capability_id in agent_registry else ""


def inventory_capabilities(
    *, project_id: str, canonical_plan_sha256: str,
    gate_lvs: Mapping[str, Sequence[str]], requirements: Sequence[CapabilityRequirement],
    project_assets: Sequence[AssetManifest] = (), global_assets: Sequence[AssetManifest] = (),
    agent_registry: Mapping[str, object] = {}, phase: str = "GATE0_FORECAST",
    isolation: ProjectIsolation | None = None,
) -> CapabilityInventoryResult:
    """Inventory the entire plan without performing discovery or any network I/O."""
    values = _validate_requirements(
        requirements, project_id=project_id, canonical_plan_sha256=canonical_plan_sha256,
        gate_lvs=gate_lvs, phase=phase,
    )
    existing: dict[str, str] = {}
    gaps: list[str] = []
    rows: list[dict[str, Any]] = []
    for item in values:
        asset = _exact_existing(item, project_assets=project_assets, global_assets=global_assets,
                                agent_registry=agent_registry)
        key = f"{item.gate_id}/{item.lv_id}/{item.capability_id}"
        if asset:
            existing[key] = asset
        else:
            gaps.append(key)
        rows.append({
            "gate_id": item.gate_id, "lv_id": item.lv_id,
            "capability_id": item.capability_id,
            "required_permissions": list(item.required_permissions),
            "owned_files": list(item.owned_files), "scope": "PROJECT_THEN_GLOBAL_THEN_AGENT",
            "existing_asset": asset, "gap_forecast": not bool(asset),
        })
    evidence: dict[str, Any] = {
        "schema_version": "orchestration.capability-inventory.evidence.v1",
        "phase": phase, "project_id": project_id,
        "canonical_plan_sha256": canonical_plan_sha256,
        "authoritative_for_execution": phase == "GATE_TIME",
        "execution_authorized": False, "network_attempted": False,
        "inventory": rows, "capability_gaps": gaps,
        "discovery_likely": bool(gaps), "dangerous_approval_likely": bool(gaps),
    }
    evidence["evidence_digest"] = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
    reference = _persist(isolation, evidence)
    return CapabilityInventoryResult(
        phase, phase == "GATE_TIME", values, existing, tuple(gaps), evidence, reference,
    )


def run_lazy_discovery(
    *, request: DiscoveryRequest, project_id: str, canonical_plan_sha256: str,
    gate_lvs: Mapping[str, Sequence[str]], project_assets: Sequence[AssetManifest] = (),
    global_assets: Sequence[AssetManifest] = (), agent_registry: Mapping[str, object] = {},
    authorized_permissions: Sequence[str], authorized_owned_files: Sequence[str],
    prior_used_assets: Sequence[str] = (), isolation: ProjectIsolation | None = None,
    http_executor: Callable[..., HTTPDiscoveryResponse],
    transport_registry: Mapping[str, DiscoveryTransportContract] = TRUSTED_DISCOVERY_TRANSPORTS,
) -> LazyDiscoveryResult:
    """Re-inventory one Gate/LV and invoke only the approved conditional HTTP transport."""
    requirement = request.requirement
    if request.project_id != project_id or request.canonical_plan_sha256 != canonical_plan_sha256:
        raise CapabilityInventoryError("project or canonical plan binding mismatch")
    if set(requirement.required_permissions) - set(authorized_permissions):
        raise CapabilityInventoryError("permission mismatch before discovery")
    if set(requirement.owned_files) - set(authorized_owned_files):
        raise CapabilityInventoryError("owned-file mismatch before discovery")
    inventory = inventory_capabilities(
        project_id=project_id, canonical_plan_sha256=canonical_plan_sha256,
        gate_lvs=gate_lvs, requirements=(requirement,), project_assets=project_assets,
        global_assets=global_assets, agent_registry=agent_registry,
        phase="GATE_TIME", isolation=isolation,
    )
    if not inventory.gaps:
        return LazyDiscoveryResult("EXISTING", inventory, None, tuple(prior_used_assets), True)
    result = run_http_read_only_discovery(
        request, http_executor=http_executor, isolation=isolation,
        transport_registry=transport_registry,
    )
    decision = "PENDING_EVALUATION" if result.status == DiscoveryStatus.DISCOVERY_COMPLETED else "BLOCKED"
    return LazyDiscoveryResult(decision, inventory, result, tuple(prior_used_assets), True)
