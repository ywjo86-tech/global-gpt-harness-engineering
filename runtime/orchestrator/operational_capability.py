from __future__ import annotations

"""Dry-run pre-WORKER capability orchestration.

This module deliberately owns no production executors.  Callers supply fixture
operations and evidence verifiers; the adapter only orders them, seals their
outputs, and revalidates a durable checkpoint before reuse.
"""

import hashlib
import dataclasses
import json
import re
import importlib
import inspect
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from .capability_inventory import inventory_capabilities
from .candidate_content_resolver import (
    CandidateContentResolutionRequest, CandidateResolutionIntent,
    ResolutionTransportContract, resolve_candidate_content,
)
from .skill_adoption import (
    decide_adoption, seal_install_plan, seal_supply_chain_review,
)
from .skill_candidate_evaluator import CandidateEvaluationRequest, evaluate_candidate
from .skill_discovery import (
    DiscoveryAdapterResult, DiscoveryRequest, DiscoveryTransportContract,
    RawDiscoveredCandidate, run_http_read_only_discovery,
)
from .skill_installer import SkillInstallRequest, install_project_skill
from .skill_use_authorization import (
    authorize_candidate_use, attest_installed_artifact, transition_used_asset,
)
from .lv_execution_package import canonical_json_bytes
from .project_isolation import AssetManifest, ProjectIsolation
from .schemas import CapabilityRequirement


CAPABILITY_CONTRACT_VERSION = "v1"
CAPABILITY_CONTRACT_STATES = frozenset({"UNDECLARED", "NO_CAPABILITY_REQUIREMENT", "REQUIRED", "BLOCKED", "ESCALATION_REQUIRED"})
_CAPABILITY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_CAPABILITY_PERMISSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class CapabilityRequirementEnvelope:
    project_id: str
    gate_id: str
    lv_id: str
    canonical_plan_sha256: str
    capability_contract_version: str
    capability_id: str
    required_permissions: tuple[str, ...]
    owned_files_digest: str
    execution_digest: str
    source_declaration_ref: str
    requirement_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self); value.pop("requirement_digest")
        return value

    def expected_digest(self) -> str:
        return _digest(self.unsigned())

    def valid(self, *, project_id: str, gate_id: str, lv_id: str,
              canonical_plan_sha256: str, owned_files: Sequence[str], execution: str) -> bool:
        return bool(
            self.project_id == project_id and self.gate_id == gate_id and self.lv_id == lv_id
            and self.canonical_plan_sha256 == canonical_plan_sha256
            and self.capability_contract_version == CAPABILITY_CONTRACT_VERSION
            and self.capability_id and self.required_permissions and self.source_declaration_ref
            and self.owned_files_digest == _digest(list(owned_files))
            and self.execution_digest == _digest(execution)
            and self.requirement_digest == self.expected_digest()
        )

    def requirement(self, owned_files: Sequence[str]) -> CapabilityRequirement:
        return CapabilityRequirement(self.capability_id, self.gate_id, self.lv_id,
                                     self.required_permissions, tuple(owned_files))


@dataclass(frozen=True, slots=True)
class CapabilityRequirementDerivation:
    status: str
    envelopes: tuple[CapabilityRequirementEnvelope, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in CAPABILITY_CONTRACT_STATES:
            raise ValueError("unknown capability contract derivation state")


def derive_capability_requirements(plan: object, lv_id: str) -> CapabilityRequirementDerivation:
    """Derive only explicitly declared requirements from a canonical Gate/LV."""
    lvs = getattr(plan, "lvs", ())
    lv = next((item for item in lvs if getattr(item, "lv_id", None) == lv_id), None)
    if lv is None:
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="canonical Gate/LV is missing")
    contract = getattr(lv, "capability_contract", None)
    if contract is None:
        return CapabilityRequirementDerivation("UNDECLARED", blocked_reason="capability contract is undeclared")
    if not isinstance(contract, Mapping) or set(contract) != {"version", "mode", "requirements"}:
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="capability contract field mismatch")
    if contract.get("version") != CAPABILITY_CONTRACT_VERSION:
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="unknown capability contract version")
    mode = contract.get("mode"); requirements = contract.get("requirements")
    if not isinstance(requirements, list):
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="capability requirements must be a list")
    if mode == "DECLARED_NONE":
        if requirements:
            return CapabilityRequirementDerivation("BLOCKED", blocked_reason="DECLARED_NONE requirements must be empty")
        return CapabilityRequirementDerivation("NO_CAPABILITY_REQUIREMENT")
    if mode != "REQUIRED":
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="unknown capability contract mode")
    if len(requirements) != 1:
        return CapabilityRequirementDerivation(
            "ESCALATION_REQUIRED" if len(requirements) > 1 else "BLOCKED",
            blocked_reason="Capability Contract v1 requires exactly one requirement")
    declaration = requirements[0]
    if not isinstance(declaration, Mapping) or set(declaration) != {"capability_id", "required_permissions", "source_ref"}:
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="capability requirement field mismatch")
    capability_id = declaration.get("capability_id")
    permissions = declaration.get("required_permissions")
    source_ref = declaration.get("source_ref")
    expected_ref = f"gate/{getattr(lv, 'gate_id', '')}/lv/{lv_id}/capability_contract/requirements/0"
    if (not isinstance(capability_id, str) or capability_id == "UNKNOWN" or not _CAPABILITY_ID.fullmatch(capability_id)
            or not isinstance(permissions, list) or not permissions
            or len(set(permissions)) != len(permissions)
            or any(not isinstance(value, str) or value == "UNKNOWN" or not _CAPABILITY_PERMISSION.fullmatch(value)
                   for value in permissions)
            or not isinstance(source_ref, str) or source_ref != expected_ref):
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="capability declaration is malformed")
    owned_files = getattr(lv, "owned_files", None); execution = getattr(lv, "execution", None)
    project_id = getattr(plan, "project_id", ""); plan_sha = getattr(plan, "canonical_plan_sha256", "")
    if (not project_id or not isinstance(plan_sha, str) or len(plan_sha) != 64
            or not isinstance(owned_files, list) or not owned_files or not isinstance(execution, str) or not execution):
        return CapabilityRequirementDerivation("BLOCKED", blocked_reason="canonical requirement binding is incomplete")
    envelope = CapabilityRequirementEnvelope(
        project_id, getattr(lv, "gate_id", ""), lv_id, plan_sha, CAPABILITY_CONTRACT_VERSION,
        capability_id, tuple(permissions), _digest(owned_files), _digest(execution), source_ref,
    )
    envelope = dataclasses.replace(envelope, requirement_digest=envelope.expected_digest())
    return CapabilityRequirementDerivation("REQUIRED", (envelope,))


def require_full_plan_capability_contract(derivation: CapabilityRequirementDerivation,
                                          *, legacy_test_only: bool = False) -> None:
    if derivation.status == "UNDECLARED" and legacy_test_only:
        return
    if derivation.status not in {"NO_CAPABILITY_REQUIREMENT", "REQUIRED"}:
        raise OperationalCapabilityError("FULL_PLAN capability contract is not production-authorized: " + derivation.status)


@dataclass(frozen=True, slots=True)
class ProductionCapabilityInventorySources:
    project_assets: tuple[AssetManifest, ...]
    global_assets: tuple[AssetManifest, ...]
    agent_registry: Mapping[str, object]
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class CapabilityApprovalEvidenceRef:
    relative: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class CanonicalCapabilityRuntimeSources:
    isolation: ProjectIsolation
    project_manifest_evidence: Mapping[str, str]
    global_manifest_evidence: Mapping[str, str]
    discovery_approval: CapabilityApprovalEvidenceRef | None = None
    install_approval: CapabilityApprovalEvidenceRef | None = None
    use_approval: CapabilityApprovalEvidenceRef | None = None
    discovery_transport: DiscoveryTransportContract | None = None
    resolution_transport: ResolutionTransportContract | None = None
    http_executor: Callable[..., object] | None = None
    fixture_repository_root: str = ""
    candidate_metadata: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = "2026-09-01T00:00:00Z"
    ledger: MutableMapping[str, Any] | None = None
    checkpoint_sink: Callable[[Mapping[str, Any]], None] | None = None
    verified_checkpoints: Mapping[str, Mapping[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class ExistingCapabilityDecision:
    requirement_digest: str
    selected_asset_id: str
    asset_source: str
    provider_identity: str
    inventory_evidence_digest: str
    project_id: str
    gate_id: str
    lv_id: str
    canonical_plan_sha256: str
    decision_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self); value.pop("decision_digest")
        return value

    def expected_digest(self) -> str:
        return _digest(self.unsigned())

    def valid(self) -> bool:
        return bool(self.selected_asset_id and self.provider_identity
                    and self.decision_digest == self.expected_digest())


@dataclass(frozen=True, slots=True)
class CanonicalCapabilityPrerequisiteResult:
    status: str
    worker_prerequisites_satisfied: bool
    runtime_selection: RuntimeSelection | None
    derivation: CapabilityRequirementDerivation
    operational_result: OperationalCapabilityResult | None = None
    existing_decision: ExistingCapabilityDecision | None = None
    blocked_reason: str = ""
    gate_passed: bool = False

    def ledger_projection(self) -> dict[str, Any]:
        if self.operational_result is not None:
            return self.operational_result.ledger_projection()
        return {"capability_requirements": [], "capability_gaps": [], "discovery_required": False,
                "candidate_use_authorized": False, "used_assets": [], "runtime_selections": []}


def production_inventory_sources(*, isolation: ProjectIsolation,
                                 project_manifest_evidence: Mapping[str, str],
                                 global_manifest_evidence: Mapping[str, str]) -> ProductionCapabilityInventorySources:
    """Load authoritative manifests and the built-in Agent registry, fail closed."""
    if (not isinstance(isolation, ProjectIsolation)
            or not isinstance(project_manifest_evidence, Mapping)
            or not isinstance(global_manifest_evidence, Mapping)):
        raise OperationalCapabilityError("production capability inventory source is unknown or malformed")
    def load_manifests(evidence: Mapping[str, str], scope: str) -> tuple[AssetManifest, ...]:
        loaded = []
        for reference, digest in evidence.items():
            if not isinstance(reference, str) or not isinstance(digest, str) or len(digest) != 64:
                raise OperationalCapabilityError("asset manifest provenance is malformed")
            try:
                raw = isolation.read("artifact", reference)
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise OperationalCapabilityError("asset manifest provenance digest mismatch")
                manifest = AssetManifest.from_mapping(json.loads(raw))
            except Exception as exc:
                if isinstance(exc, OperationalCapabilityError):
                    raise
                raise OperationalCapabilityError("asset manifest source is unreadable or malformed") from exc
            if manifest.scope != scope:
                raise OperationalCapabilityError("asset manifest source scope mismatch")
            loaded.append(manifest)
        return tuple(loaded)
    project_assets = load_manifests(project_manifest_evidence, "project")
    if global_manifest_evidence:
        raise OperationalCapabilityError("authoritative Global AssetManifest provider is unavailable")
    global_assets: tuple[AssetManifest, ...] = ()
    from runtime.agents import AGENT_REGISTRY
    agent_registry = dict(AGENT_REGISTRY)
    agent_identities = []
    for key, value in agent_registry.items():
        module_name = getattr(value, "__module__", "")
        source = inspect.getsourcefile(value) if inspect.isclass(value) else None
        try:
            module_value = getattr(importlib.import_module(module_name), getattr(value, "__name__", ""))
        except (ImportError, AttributeError):
            module_value = None
        if (not isinstance(key, str) or not key or not inspect.isclass(value)
                or getattr(value, "agent_name", None) != key
                or not module_name.startswith("runtime.agents.") or module_value is not value
                or source is None or not Path(source).is_file()):
            raise OperationalCapabilityError("built-in Agent registry identity is invalid")
        agent_identities.append({"agent_id":key, "module":module_name, "class":value.__qualname__,
                                 "source_sha256":hashlib.sha256(Path(source).read_bytes()).hexdigest()})
    serialize = lambda item: {"asset_id":item.asset_id, "scope":item.scope,
                              "capabilities":sorted(item.capabilities), "permissions":sorted(item.permissions),
                              "owned_files":list(item.owned_files)}
    payload = {"project_assets":[serialize(item) for item in project_assets],
               "global_assets":[serialize(item) for item in global_assets],
               "agent_identities":sorted(agent_identities, key=lambda item: item["agent_id"]),
               "project_manifest_evidence":dict(sorted(project_manifest_evidence.items())),
               "global_manifest_evidence":dict(sorted(global_manifest_evidence.items()))}
    return ProductionCapabilityInventorySources(tuple(project_assets), tuple(global_assets),
                                                dict(agent_registry), _digest(payload))


def load_capability_approval(isolation: ProjectIsolation, relative: str, *, intent: str,
                             project_id: str, gate_id: str, lv_id: str,
                             canonical_plan_sha256: str, evidence_digest: str,
                             candidate_id: str = "") -> object:
    """Read one typed approval from the existing project approval namespace."""
    if not isinstance(isolation, ProjectIsolation) or not isinstance(relative, str) or not relative:
        raise OperationalCapabilityError("capability approval source is invalid")
    try:
        raw = isolation.read("approval", relative)
        if len(evidence_digest) != 64 or hashlib.sha256(raw).hexdigest() != evidence_digest:
            raise OperationalCapabilityError("capability approval evidence digest mismatch")
        value = json.loads(raw)
    except Exception as exc:
        raise OperationalCapabilityError("capability approval evidence is missing or malformed") from exc
    if not isinstance(value, Mapping):
        raise OperationalCapabilityError("synthetic capability approval is forbidden")
    try:
        if intent == "skill_discovery_read_only":
            from .skill_discovery import DiscoveryApproval
            approval = DiscoveryApproval(**value)
            valid = (approval.approved is True and approval.intent == intent
                     and approval.classification == "dangerous" and bool(approval.evidence_reference)
                     and len(approval.evidence_sha256) == 64
                     and all(char in "0123456789abcdef" for char in approval.evidence_sha256))
        elif intent == "project_skill_install":
            from .skill_adoption import ProjectInstallApproval
            approval = ProjectInstallApproval(**value); valid = approval.valid()
        elif intent == "project_skill_use":
            from .skill_use_authorization import ProjectUseApproval
            approval = ProjectUseApproval(**value); valid = approval.valid()
        else:
            raise OperationalCapabilityError("unknown capability approval intent")
    except (TypeError, ValueError) as exc:
        raise OperationalCapabilityError("capability approval contract is malformed") from exc
    bindings = (getattr(approval, "project_id", "") == project_id,
                getattr(approval, "gate_id", "") == gate_id,
                getattr(approval, "lv_id", "") == lv_id,
                getattr(approval, "canonical_plan_sha256", "") == canonical_plan_sha256,
                not candidate_id or getattr(approval, "candidate_id", "") == candidate_id)
    if not valid or not all(bindings):
        raise OperationalCapabilityError("capability approval is inactive or binding mismatched")
    return approval


class OperationalCapabilityError(ValueError):
    pass


class InjectedCrash(RuntimeError):
    """Test-only control-flow marker; never converted into business BLOCKED."""
    pass


_GAP_STAGES = (
    "DISCOVERY_APPROVAL", "DISCOVERY", "RESOLUTION", "EVALUATION",
    "SUPPLY_CHAIN_REVIEW", "ADOPTION", "INSTALL_AUTHORIZATION", "INSTALL",
    "ATTESTATION", "USE_AUTHORIZATION", "USED_ASSETS",
)

# These stages are intentionally separate from the compatibility callback
# adapter above.  A discovered result is never allowed to flow directly to
# evaluation: the raw candidate and immutable provenance are independently
# sealed first.
_CONCRETE_STAGES = (
    "DISCOVERY_APPROVAL", "DISCOVERY", "RAW_CANDIDATE", "CONTENT_RESOLUTION",
    "IMMUTABLE_PROVENANCE_VERIFIED", "EVALUATION", "SUPPLY_CHAIN_REVIEW",
    "ADOPTION", "INSTALL_AUTHORIZATION", "INSTALL", "ATTESTATION",
    "USE_AUTHORIZATION", "USED_ASSETS",
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class DryRunExecutionContext:
    project_id: str
    gate_id: str
    lv_id: str
    canonical_plan_sha256: str
    fixture_root: str
    dry_run: bool = True
    network_allowed: bool = False
    repository_fetch_allowed: bool = False
    live_install_allowed: bool = False
    skill_execution_allowed: bool = False

    def validate(self, requirement: CapabilityRequirement) -> None:
        if not self.dry_run or any((self.network_allowed, self.repository_fetch_allowed,
                                    self.live_install_allowed, self.skill_execution_allowed)):
            raise OperationalCapabilityError("production side effects are forbidden")
        if not self.fixture_root or not self.project_id:
            raise OperationalCapabilityError("dry-run fixture/project identity is missing")
        if (requirement.gate_id, requirement.lv_id) != (self.gate_id, self.lv_id):
            raise OperationalCapabilityError("capability requirement Gate/LV mismatch")
        if len(self.canonical_plan_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.canonical_plan_sha256):
            raise OperationalCapabilityError("canonical plan SHA is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    asset_id: str
    skill_id: str
    installed_target: str
    artifact_digest: str
    attestation_evidence_reference: str
    use_authorization_evidence_reference: str
    capability_requirement: str
    project_id: str
    gate_id: str
    lv_id: str
    canonical_plan_sha256: str
    source: str
    simulated: bool = True
    execution_allowed_in_dry_run: bool = False


StageOperation = Callable[[Mapping[str, Any]], Mapping[str, Any]]
EvidenceVerifier = Callable[[Mapping[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class FixtureApprovalBundle:
    """Explicit, independently sealed approvals for the dry-run boundaries.

    The adapter intentionally does not manufacture approvals from a boolean or
    from FULL_PLAN.  Callers must provide the evidence produced by the
    corresponding approval contract; a missing member therefore short-circuits
    at that boundary.
    """

    discovery: object | None = None
    install: object | None = None
    use: object | None = None


@dataclass(frozen=True, slots=True)
class FixtureModuleAdapters:
    """Typed dependency-injection boundary for real lifecycle modules.

    Each callable is expected to invoke the named production module and return
    its sealed evidence payload.  This keeps all external effects behind an
    explicit fixture adapter while preventing the production path from falling
    back to the historical fixed-payload callback helper.
    """

    discovery: StageOperation
    resolution: StageOperation
    evaluation: StageOperation
    supply_chain_review: StageOperation
    adoption: StageOperation
    install: StageOperation
    attestation: StageOperation
    use_authorization: StageOperation
    used_assets: StageOperation
    verifiers: Mapping[str, EvidenceVerifier] = field(default_factory=dict)

    def as_operations(self, approvals: FixtureApprovalBundle = FixtureApprovalBundle()) -> "DryRunOperations":
        def approval(stage: str) -> StageOperation:
            def run(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
                value = getattr(approvals, {"DISCOVERY_APPROVAL": "discovery",
                                            "INSTALL_AUTHORIZATION": "install",
                                            "USE_AUTHORIZATION": "use"}[stage])
                if value is None:
                    return {"ok": False, "approval_missing": True, "stage": stage}
                valid = getattr(value, "valid", None)
                if not callable(valid) or not bool(valid()):
                    return {"ok": False, "approval_invalid": True, "stage": stage}
                sealed = dataclasses.asdict(value) if dataclasses.is_dataclass(value) else {"approval_digest": str(getattr(value, "approval_digest", ""))}
                return {"ok": True, "approval": sealed, "approval_digest":
                        str(getattr(value, "approval_digest", "")), "stage": stage}
            return run

        operations: dict[str, StageOperation] = {
            "DISCOVERY_APPROVAL": approval("DISCOVERY_APPROVAL"),
            "DISCOVERY": self.discovery,
            "RESOLUTION": self.resolution,
            "EVALUATION": self.evaluation,
            "SUPPLY_CHAIN_REVIEW": self.supply_chain_review,
            "ADOPTION": self.adoption,
            "INSTALL_AUTHORIZATION": approval("INSTALL_AUTHORIZATION"),
            "INSTALL": self.install,
            "ATTESTATION": self.attestation,
            "USE_AUTHORIZATION": approval("USE_AUTHORIZATION"),
            "USED_ASSETS": self.used_assets,
        }
        # A module-backed adapter must provide every verifier.  In particular,
        # accepting ``{"ok": True}`` here would turn unsigned fixture output
        # into production-looking evidence and bypass the lifecycle contracts.
        verifiers = dict(self.verifiers)
        if set(verifiers) != set(_GAP_STAGES):
            raise OperationalCapabilityError(
                "module-backed adapters require explicit sealed-evidence verifiers")
        return DryRunOperations(operations, verifiers)


@dataclass(frozen=True, slots=True)
class DryRunOperations:
    operations: Mapping[str, StageOperation]
    verifiers: Mapping[str, EvidenceVerifier]

    def validate(self) -> None:
        if set(self.operations) != set(_GAP_STAGES) or set(self.verifiers) != set(_GAP_STAGES):
            raise OperationalCapabilityError("complete dry-run operation/verifier set is required")


@dataclass(frozen=True, slots=True)
class OperationalCapabilityResult:
    status: str
    route: str
    worker_prerequisites_satisfied: bool
    runtime_selection: RuntimeSelection | None
    stage_records: Mapping[str, Mapping[str, Any]]
    blocked_stage: str = ""
    blocked_reason: str = ""
    gate_passed: bool = False

    def ledger_projection(self) -> dict[str, Any]:
        selection = asdict(self.runtime_selection) if self.runtime_selection else {}
        refs = {stage: "sha256:" + str(record.get("stage_digest", ""))
                for stage, record in self.stage_records.items()}
        discovered = str(self.stage_records.get("DISCOVERY", {}).get("payload", {}).get("candidate_id", ""))
        evaluated = str(self.stage_records.get("EVALUATION", {}).get("payload", {}).get("candidate_id", discovered))
        return {
            "capability_requirements": [selection.get("capability_requirement", "")] if selection else [],
            "existing_capability_decision": selection.get("asset_id", "") if self.route == "EXISTING" else "",
            "capability_gaps": [] if self.route == "EXISTING" else ([selection.get("capability_requirement", "")] if selection else []),
            "discovery_required": self.route == "GAP",
            "discovery_status": "SKIPPED_EXISTING" if self.route == "EXISTING" else ("COMPLETED" if self.status == "READY_FOR_WORKER" else "BLOCKED"),
            "discovered_candidates": [discovered] if discovered else [],
            "evaluated_candidates": [evaluated] if evaluated else [],
            "selected_candidate": evaluated,
            "discovery_evidence_references": [refs["DISCOVERY"]] if "DISCOVERY" in refs else [],
            "evaluation_evidence_references": [refs["EVALUATION"]] if "EVALUATION" in refs else [],
            "resolution_evidence_references": [refs["RESOLUTION"]] if "RESOLUTION" in refs else [],
            "adoption_decisions": [refs["ADOPTION"]] if "ADOPTION" in refs else [],
            "supply_chain_evidence_reference": refs.get("SUPPLY_CHAIN_REVIEW", ""),
            "install_required": self.route == "GAP",
            "install_authorized": "INSTALL_AUTHORIZATION" in refs,
            "install_scope": "project" if self.route == "GAP" else "",
            "install_plan_evidence_reference": refs.get("INSTALL_AUTHORIZATION", ""),
            "installation_evidence_references": [refs["INSTALL"]] if "INSTALL" in refs else [],
            "installed_candidates": [selection.get("asset_id", "")] if self.route == "GAP" and selection else [],
            "attestation_evidence_references": [selection.get("attestation_evidence_reference", "")] if self.route == "GAP" and selection else [],
            "use_authorization_evidence_references": [selection.get("use_authorization_evidence_reference", "")] if self.route == "GAP" and selection else [],
            "candidate_use_authorized": self.route == "GAP" and self.worker_prerequisites_satisfied,
            "used_assets": [selection.get("asset_id", "")] if selection else [],
            "runtime_selections": [_digest(selection)] if selection else [],
        }


def run_module_backed_fixture_dry_run(
    *, context: DryRunExecutionContext, requirement: CapabilityRequirement,
    adapters: FixtureModuleAdapters, approvals: FixtureApprovalBundle = FixtureApprovalBundle(),
    project_assets: Sequence[AssetManifest] = (), global_assets: Sequence[AssetManifest] = (),
    agent_registry: Mapping[str, object] = {},
    checkpoint: MutableMapping[str, Mapping[str, Any]] | None = None,
) -> OperationalCapabilityResult:
    """Run the capability boundary with production modules behind fixtures.

    This is the only supported integration entry point for Phase 4A dry-runs.
    ``FixtureModuleAdapters`` must call the existing discovery, resolver,
    evaluator, adoption, installer, attestation, and use-authorization
    modules.  No network or live project is reachable through this function.
    """
    if not isinstance(adapters, FixtureModuleAdapters):
        raise OperationalCapabilityError("module-backed fixture adapters are required")
    result = run_operational_capability_dry_run(
        context=context, requirement=requirement, project_assets=project_assets,
        global_assets=global_assets, agent_registry=agent_registry,
        operations=adapters.as_operations(approvals), checkpoint=checkpoint,
    )
    if result.route == "GAP" and result.status == "READY_FOR_WORKER":
        required = ("DISCOVERY", "RESOLUTION", "EVALUATION", "SUPPLY_CHAIN_REVIEW",
                    "ADOPTION", "INSTALL", "ATTESTATION", "USE_AUTHORIZATION", "USED_ASSETS")
        if any(stage not in result.stage_records for stage in required):
            return OperationalCapabilityResult("BLOCKED", "GAP", False, None,
                                               result.stage_records, "RAW_CANDIDATE",
                                               "module-backed lifecycle evidence is incomplete")
    return result


def _record(stage: str, context: DryRunExecutionContext, requirement: CapabilityRequirement,
            previous_digest: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = {
        "schema_version": "orchestration.operational-capability-stage.v1",
        "stage": stage, "project_id": context.project_id, "gate_id": context.gate_id,
        "lv_id": context.lv_id, "canonical_plan_sha256": context.canonical_plan_sha256,
        "capability_requirement": requirement.capability_id,
        "previous_stage_digest": previous_digest, "payload": dict(payload),
        "payload_digest": _digest(payload), "dry_run": True, "gate_passed": False,
    }
    return {**unsigned, "stage_digest": _digest(unsigned)}


def _valid_record(record: Mapping[str, Any], *, stage: str,
                  context: DryRunExecutionContext, requirement: CapabilityRequirement,
                  previous_digest: str, verifier: EvidenceVerifier) -> bool:
    if set(record) != {"schema_version", "stage", "project_id", "gate_id", "lv_id",
                       "canonical_plan_sha256", "capability_requirement", "previous_stage_digest",
                       "payload", "payload_digest", "dry_run", "gate_passed", "stage_digest"}:
        return False
    unsigned = {key: value for key, value in record.items() if key != "stage_digest"}
    payload = record.get("payload")
    return bool(
        record.get("schema_version") == "orchestration.operational-capability-stage.v1"
        and record.get("stage") == stage and record.get("project_id") == context.project_id
        and record.get("gate_id") == context.gate_id and record.get("lv_id") == context.lv_id
        and record.get("canonical_plan_sha256") == context.canonical_plan_sha256
        and record.get("capability_requirement") == requirement.capability_id
        and record.get("previous_stage_digest") == previous_digest
        and record.get("dry_run") is True and record.get("gate_passed") is False
        and isinstance(payload, Mapping) and record.get("payload_digest") == _digest(payload)
        and record.get("stage_digest") == _digest(unsigned) and verifier(payload)
    )


def _existing_source(asset: str, requirement: CapabilityRequirement,
                     project_assets: Sequence[AssetManifest], global_assets: Sequence[AssetManifest],
                     agent_registry: Mapping[str, object]) -> str:
    project_ids = {item.asset_id for item in project_assets}
    global_ids = {item.asset_id for item in global_assets}
    if asset in project_ids:
        return "PROJECT"
    if asset in global_ids:
        return "GLOBAL"
    if asset == requirement.capability_id and asset in agent_registry:
        return "AGENT"
    raise OperationalCapabilityError("existing capability source is ambiguous")


def run_operational_capability_dry_run(
    *, context: DryRunExecutionContext, requirement: CapabilityRequirement,
    project_assets: Sequence[AssetManifest] = (), global_assets: Sequence[AssetManifest] = (),
    agent_registry: Mapping[str, object] = {}, operations: DryRunOperations | None = None,
    checkpoint: MutableMapping[str, Mapping[str, Any]] | None = None,
) -> OperationalCapabilityResult:
    """Resolve one capability to a simulated RuntimeSelection, never execute it."""
    context.validate(requirement)
    gate_lvs = {context.gate_id: (context.lv_id,)}
    inventory = inventory_capabilities(
        project_id=context.project_id, canonical_plan_sha256=context.canonical_plan_sha256,
        gate_lvs=gate_lvs, requirements=(requirement,), project_assets=project_assets,
        global_assets=global_assets, agent_registry=agent_registry, phase="GATE_TIME",
    )
    key = f"{context.gate_id}/{context.lv_id}/{requirement.capability_id}"
    existing = inventory.existing_assets.get(key, "")
    if existing:
        source = _existing_source(existing, requirement, project_assets, global_assets, agent_registry)
        selection = RuntimeSelection(
            asset_id=existing, skill_id=existing, installed_target="", artifact_digest="",
            attestation_evidence_reference=inventory.evidence_reference,
            use_authorization_evidence_reference="existing-capability-exact-match",
            capability_requirement=requirement.capability_id, project_id=context.project_id,
            gate_id=context.gate_id, lv_id=context.lv_id,
            canonical_plan_sha256=context.canonical_plan_sha256, source=source,
        )
        return OperationalCapabilityResult("READY_FOR_WORKER", "EXISTING", True, selection, {}, gate_passed=False)

    if operations is None:
        return OperationalCapabilityResult("BLOCKED", "GAP", False, None, {},
                                           "DISCOVERY_APPROVAL", "dry-run operations are missing")
    operations.validate()
    durable = checkpoint if checkpoint is not None else {}
    records: dict[str, Mapping[str, Any]] = {}
    previous = str(inventory.evidence.get("evidence_digest", ""))
    inputs: dict[str, Any] = {"context": asdict(context), "requirement": asdict(requirement),
                              "inventory_evidence": dict(inventory.evidence)}
    for stage in _GAP_STAGES:
        prior = durable.get(stage)
        if prior is not None:
            if not _valid_record(prior, stage=stage, context=context, requirement=requirement,
                                 previous_digest=previous, verifier=operations.verifiers[stage]):
                return OperationalCapabilityResult("BLOCKED", "GAP", False, None, records,
                                                   stage, "stale or malformed sealed evidence")
            record = prior
        else:
            payload = operations.operations[stage]({**inputs, "prior_stage_records": dict(records)})
            if not isinstance(payload, Mapping) or not operations.verifiers[stage](payload):
                return OperationalCapabilityResult("BLOCKED", "GAP", False, None, records,
                                                   stage, "stage evidence validation failed")
            record = _record(stage, context, requirement, previous, payload)
            durable[stage] = record
        records[stage] = record
        previous = str(record["stage_digest"])
        inputs[stage.lower()] = dict(record["payload"])

    use = records["USE_AUTHORIZATION"]["payload"]
    used = records["USED_ASSETS"]["payload"]
    asset = str(used.get("stable_asset_identifier", ""))
    if (not asset.startswith("installed-skill:sha256:")
            or asset != use.get("stable_asset_identifier")
            or use.get("candidate_use_authorized") is not True
            or used.get("gate_passed") is not False):
        return OperationalCapabilityResult("BLOCKED", "GAP", False, None, records,
                                           "RUNTIME_SELECTION", "used asset/use authorization binding mismatch")
    attestation = records["ATTESTATION"]["payload"]
    install = records["INSTALL"]["payload"]
    selection = RuntimeSelection(
        asset_id=asset, skill_id=str(use.get("candidate_id", "")),
        installed_target=str(use.get("target", "")),
        artifact_digest=str(install.get("artifact_digest", "")),
        attestation_evidence_reference="sha256:" + str(attestation.get("attestation_digest", "")),
        use_authorization_evidence_reference="sha256:" + str(use.get("authorization_digest", "")),
        capability_requirement=requirement.capability_id, project_id=context.project_id,
        gate_id=context.gate_id, lv_id=context.lv_id,
        canonical_plan_sha256=context.canonical_plan_sha256, source="INSTALLED_PROJECT_SKILL",
    )
    return OperationalCapabilityResult("READY_FOR_WORKER", "GAP", True, selection, records, gate_passed=False)


def run_concrete_module_fixture_dry_run(
    *, context: DryRunExecutionContext, requirement: CapabilityRequirement,
    discovery_approval: object, discovery_transport: DiscoveryTransportContract,
    resolution_transport: ResolutionTransportContract, http_executor: Callable[..., object],
    install_approval: object | None = None, use_approval: object | None = None,
    install_approval_factory: Callable[[Any, Any, Any], object] | None = None,
    use_approval_factory: Callable[[Any], object] | None = None,
    fixture_repository_root: str, project_root: str,
    candidate_metadata: Mapping[str, Any], permissions: Sequence[str] = (),
    owned_files: Sequence[str] = (), timestamp: str = "2026-09-01T00:00:00Z",
    project_assets: Sequence[AssetManifest] = (), global_assets: Sequence[AssetManifest] = (),
    agent_registry: Mapping[str, object] = {}, ledger: MutableMapping[str, Any] | None = None,
    checkpoint_sink: Callable[[Mapping[str, Any]], None] | None = None,
    verified_checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
) -> OperationalCapabilityResult:
    """Execute the real discovery-to-use modules against fixture boundaries.

    This is deliberately a concrete entry point: lifecycle stages are not
    callbacks and no caller-provided stage payload is accepted.  Network
    transport is supplied only as the module's HTTP boundary and is expected
    to be a fixture executor.  Installation is constrained by the installer
    itself to the canonical project-local target.
    """
    context.validate(requirement)
    inventory = inventory_capabilities(
        project_id=context.project_id, canonical_plan_sha256=context.canonical_plan_sha256,
        gate_lvs={context.gate_id: (context.lv_id,)}, requirements=(requirement,),
        project_assets=project_assets, global_assets=global_assets,
        agent_registry=agent_registry, phase="GATE_TIME",
    )
    key = f"{context.gate_id}/{context.lv_id}/{requirement.capability_id}"
    existing = inventory.existing_assets.get(key, "")
    if existing:
        source = _existing_source(existing, requirement, project_assets, global_assets, agent_registry)
        selection = RuntimeSelection(
            asset_id=existing, skill_id=existing, installed_target="", artifact_digest="",
            attestation_evidence_reference=inventory.evidence_reference,
            use_authorization_evidence_reference="existing-capability-exact-match",
            capability_requirement=requirement.capability_id, project_id=context.project_id,
            gate_id=context.gate_id, lv_id=context.lv_id,
            canonical_plan_sha256=context.canonical_plan_sha256, source=source,
        )
        return OperationalCapabilityResult("READY_FOR_WORKER", "EXISTING", True, selection, {}, gate_passed=False)
    if not inventory.gaps:
        return OperationalCapabilityResult("BLOCKED", "GAP", False, None, {}, "INVENTORY", "inventory is not authoritative")

    # A persisted production checkpoint is the source of truth on restart.
    # When the complete concrete chain is present, rebuild the sealed result
    # without invoking any lifecycle module (discovery/resolver/evaluator or
    # installer/use transition).  Partial chains are intentionally rejected
    # until their typed continuation boundary is available.
    if verified_checkpoints:
        canonical_to_concrete = {
            "DISCOVERY_COMPLETED": "DISCOVERY", "RAW_CANDIDATE": "RAW_CANDIDATE",
            "CONTENT_RESOLVED": "CONTENT_RESOLUTION",
            "IMMUTABLE_PROVENANCE_VERIFIED": "IMMUTABLE_PROVENANCE_VERIFIED",
            "EVALUATED": "EVALUATION", "ADOPTION_DECIDED": "ADOPTION",
            "INSTALL_AUTHORIZED": "INSTALL_AUTHORIZATION", "INSTALL_COMPLETED": "INSTALL",
            "ATTESTED": "ATTESTATION", "USE_AUTHORIZED": "USE_AUTHORIZATION",
            "USED_ASSET_BOUND": "USED_ASSETS",
        }
        restored: dict[str, Mapping[str, Any]] = {}
        for canonical, concrete in canonical_to_concrete.items():
            checkpoint = verified_checkpoints.get(canonical)
            record = checkpoint.get("stage_record") if isinstance(checkpoint, Mapping) else None
            if isinstance(record, Mapping):
                restored[concrete] = dict(record)
        if restored:
            if len(restored) != len(canonical_to_concrete):
                return OperationalCapabilityResult("BLOCKED", "GAP", False, None, restored,
                                                   "RESUME", "partial capability checkpoint continuation is unsupported")
            for stage, record in restored.items():
                payload = record.get("payload")
                if (record.get("stage") != stage or record.get("project_id") != context.project_id
                        or record.get("gate_id") != context.gate_id or record.get("lv_id") != context.lv_id
                        or record.get("canonical_plan_sha256") != context.canonical_plan_sha256
                        or not isinstance(payload, Mapping) or record.get("stage_digest") != _digest(
                            {key: value for key, value in record.items() if key != "stage_digest"})):
                    return OperationalCapabilityResult("BLOCKED", "GAP", False, None, restored,
                                                       "RESUME", "persisted capability stage evidence is invalid")
            use = restored["USE_AUTHORIZATION"]["payload"]
            install = restored["INSTALL"]["payload"]
            attestation = restored["ATTESTATION"]["payload"]
            asset = str(use.get("stable_asset_identifier", ""))
            if (not asset.startswith("installed-skill:sha256:") or use.get("candidate_use_authorized") is not True
                    or restored["USED_ASSETS"]["payload"].get("gate_passed") is not False):
                return OperationalCapabilityResult("BLOCKED", "GAP", False, None, restored,
                                                   "RESUME", "persisted use binding is invalid")
            selection = RuntimeSelection(
                asset_id=asset, skill_id=str(use.get("candidate_id", "")),
                installed_target=str(use.get("target", "")),
                artifact_digest=str(install.get("installed_content_digest", "")),
                attestation_evidence_reference="sha256:" + str(attestation.get("attestation_digest", "")),
                use_authorization_evidence_reference="sha256:" + str(use.get("authorization_digest", "")),
                capability_requirement=requirement.capability_id, project_id=context.project_id,
                gate_id=context.gate_id, lv_id=context.lv_id,
                canonical_plan_sha256=context.canonical_plan_sha256, source="INSTALLED_PROJECT_SKILL",
            )
            return OperationalCapabilityResult("READY_FOR_WORKER", "GAP", True, selection, restored, gate_passed=False)

    records: dict[str, Mapping[str, Any]] = {}
    previous = str(inventory.evidence.get("evidence_digest", ""))
    if checkpoint_sink is not None:
        checkpoint_sink({"stage": "INVENTORY_CHECKED", "stage_digest": previous,
                         "capability_requirement": requirement.capability_id,
                         "payload": dict(inventory.evidence)})

    def seal(stage: str, payload: Mapping[str, Any]) -> None:
        nonlocal previous
        if not isinstance(payload, Mapping):
            raise OperationalCapabilityError(f"{stage} returned malformed evidence")
        record = _record(stage, context, requirement, previous, payload)
        records[stage] = record
        previous = str(record["stage_digest"])
        if checkpoint_sink is not None:
            checkpoint_sink(record)

    try:
        # Approval objects are validated by the actual discovery module.
        if discovery_approval is None:
            raise OperationalCapabilityError("DISCOVERY_APPROVAL: missing approval")
        seal("DISCOVERY_APPROVAL", asdict(discovery_approval) if dataclasses.is_dataclass(discovery_approval) else {})
        request = DiscoveryRequest(
            query=requirement.capability_id, requirement=requirement,
            project_root=str(project_root), project_id=context.project_id,
            gate_id=context.gate_id, lv_id=context.lv_id, approval=discovery_approval,
            result_limit=1, runtime=None, timestamp=timestamp,
            canonical_plan_sha256=context.canonical_plan_sha256, transport=discovery_transport,
        )
        discovered: DiscoveryAdapterResult = run_http_read_only_discovery(
            request, http_executor=http_executor, transport_registry={discovery_transport.contract_sha256: discovery_transport},
        )
        if not discovered.candidates or discovered.status.value != "DISCOVERY_COMPLETED":
            raise OperationalCapabilityError("DISCOVERY: " + (discovered.blocked_reason or "discovery failed"))
        seal("DISCOVERY", discovered.evidence)
        raw = discovered.candidates[0]
        if not isinstance(raw, RawDiscoveredCandidate):
            raise OperationalCapabilityError("RAW_CANDIDATE: discovery did not return raw candidate")
        seal("RAW_CANDIDATE", {**asdict(raw), "discovery_evidence_digest": discovered.evidence.get("evidence_digest", "")})

        intent = CandidateResolutionIntent(
            context.project_id, context.gate_id, context.lv_id, raw.candidate_id,
            "read_only_candidate_content_resolution", "APPROVED",
        )
        resolution = resolve_candidate_content(
            CandidateContentResolutionRequest(
                raw_candidate=raw, source=raw.source, candidate_id=raw.candidate_id,
                project_id=context.project_id, gate_id=context.gate_id, lv_id=context.lv_id,
                intent=intent, transport=resolution_transport, timestamp=timestamp,
            ), fixture_root=fixture_repository_root,
        )
        if resolution.provenance_state != "VERIFIED" or not resolution.evidence:
            raise OperationalCapabilityError("CONTENT_RESOLUTION: " + (resolution.blocked_reason or "resolution failed"))
        seal("CONTENT_RESOLUTION", resolution.evidence)
        if resolution.evidence.get("provenance_state") != "VERIFIED":
            raise OperationalCapabilityError("IMMUTABLE_PROVENANCE_VERIFIED: provenance is not verified")
        seal("IMMUTABLE_PROVENANCE_VERIFIED", {
            "candidate_id": raw.candidate_id, "immutable_revision": resolution.immutable_revision,
            "candidate_path": resolution.candidate_path, "skill_md_digest": resolution.skill_md_digest,
            "resolution_evidence_digest": resolution.evidence.get("evidence_digest", ""),
        })

        evaluation = evaluate_candidate(CandidateEvaluationRequest(
            requirement=requirement, project_id=context.project_id, gate_id=context.gate_id,
            lv_id=context.lv_id, candidate_id=raw.candidate_id, source=raw.source,
            repository=resolution.evidence.get("repository", ""), maintainer=raw.maintainer,
            candidate_metadata=candidate_metadata, skill_md_text=resolution.skill_md_content,
            provenance="sha256:" + str(resolution.evidence.get("evidence_digest", "")),
            content_digest=resolution.skill_md_digest, permissions=tuple(permissions),
            owned_files=tuple(owned_files), timestamp=timestamp,
            resolution_evidence=resolution.evidence,
        ), manifests=project_assets, agent_registry=agent_registry)
        if evaluation.evaluation_state.value != "SAFE_FOR_CONSIDERATION":
            raise OperationalCapabilityError("EVALUATION: candidate is not safe")
        seal("EVALUATION", evaluation.evidence)

        review = seal_supply_chain_review(
            candidate_id=raw.candidate_id, source=raw.source,
            repository=resolution.evidence["repository"], maintainer=raw.maintainer,
            provider=resolution.evidence.get("provider", "fixture"),
            immutable_revision=resolution.immutable_revision, candidate_path=resolution.candidate_path,
            skill_md_digest=resolution.skill_md_digest,
            resolver_evidence_digest=resolution.evidence["evidence_digest"],
            license=str(candidate_metadata.get("license", "")),
            package_install_required=bool(candidate_metadata.get("package_install_required", False)),
            shell_execution=bool(candidate_metadata.get("shell", False)), network_required=False,
            secret_required=bool(candidate_metadata.get("secret", False)), file_write_scope=tuple(owned_files),
            install_scope="project", external_service=False, paid_service=False, deployment=False,
            destructive_action=False, requested_permissions=tuple(permissions), owned_file_scope=tuple(owned_files),
            provenance_state="VERIFIED", evaluator_evidence_digest=evaluation.evidence["evidence_digest"],
            review_state="COMPLETE",
        )
        install_plan = seal_install_plan(
            candidate_id=raw.candidate_id, target_project=context.project_id, target_scope="project",
            proposed_install_location=f".agents/skills/{raw.candidate_id.rsplit('@', 1)[-1].replace('/', '-')}",
            expected_source=raw.source, expected_revision=resolution.immutable_revision,
            expected_files=("SKILL.md",), required_permissions=tuple(permissions),
            required_package_runtime=(), network_required=False, operation_type="PROJECT_FILE_MATERIALIZATION",
            rollback_expectation="remove owned files", evaluation_evidence_reference=evaluation.evidence_reference,
            supply_chain_evidence_reference=f"sha256:{review.review_digest}",
            approval_requirement="SEPARATE_PROJECT_INSTALL_APPROVAL", install_method_state="VERIFIED_FIXTURE_METHOD",
        )
        seal("SUPPLY_CHAIN_REVIEW", {**asdict(review), "review_digest": review.review_digest})
        if install_approval is None and install_approval_factory is not None:
            install_approval = install_approval_factory(evaluation, review, install_plan)
        decision = decide_adoption(
            project_id=context.project_id, canonical_plan_sha256=context.canonical_plan_sha256,
            gate_lvs={context.gate_id: (context.lv_id,)}, requirement=requirement, evaluation=evaluation,
            candidate_risk=evaluation.risk, install_scope="project", project_assets=project_assets,
            global_assets=global_assets, agent_registry=agent_registry, review=review,
            approval=install_approval, install_plan=install_plan,
        )
        if not decision.install_authorized:
            raise OperationalCapabilityError("ADOPTION: " + (decision.blocked_reason or "install authorization required"))
        seal("ADOPTION", asdict(decision))
        if install_approval is None or not getattr(install_approval, "valid", lambda: False)():
            raise OperationalCapabilityError("INSTALL_AUTHORIZATION: separate project approval is required")
        seal("INSTALL_AUTHORIZATION", asdict(install_approval))
        if checkpoint_sink is not None:
            checkpoint_sink({"stage": "EFFECT_INTENT", "effect_id": _digest({
                "project": context.project_id, "gate": context.gate_id, "lv": context.lv_id,
                "plan": context.canonical_plan_sha256, "requirement": requirement.capability_id,
                "stage": "INSTALL", "target": str(project_root),
            }), "effect_stage": "INSTALL", "target": str(project_root),
                             "stage_digest": _digest({"stage": "EFFECT_INTENT", "target": str(project_root)})})
        install = install_project_skill(SkillInstallRequest(
            decision=decision, evaluation=evaluation, resolution=resolution, review=review,
            approval=install_approval, install_plan=install_plan, project_id=context.project_id,
            gate_id=context.gate_id, lv_id=context.lv_id, canonical_plan_sha256=context.canonical_plan_sha256,
            project_root=project_root, target_skill_root=f"{project_root}/.agents/skills", timestamp=timestamp,
        ))
        if install.install_status not in {"INSTALL_COMPLETED", "IDENTICAL"}:
            raise OperationalCapabilityError("INSTALL: " + (install.blocked_reason or "installation failed"))
        seal("INSTALL", asdict(install))
        if checkpoint_sink is not None:
            checkpoint_sink({"stage": "EFFECT_RECEIPT", "effect_id": _digest({
                "project": context.project_id, "gate": context.gate_id, "lv": context.lv_id,
                "plan": context.canonical_plan_sha256, "requirement": requirement.capability_id,
                "stage": "INSTALL", "target": str(project_root),
            }), "effect_stage": "INSTALL", "target": str(project_root),
                             "receipt": asdict(install), "stage_digest": _digest(asdict(install))})
        attestation = attest_installed_artifact(
            SkillInstallRequest(decision=decision, evaluation=evaluation, resolution=resolution, review=review,
                approval=install_approval, install_plan=install_plan, project_id=context.project_id,
                gate_id=context.gate_id, lv_id=context.lv_id, canonical_plan_sha256=context.canonical_plan_sha256,
                project_root=project_root, target_skill_root=f"{project_root}/.agents/skills", timestamp=timestamp),
            install, timestamp=timestamp)
        if not attestation.evidence:
            raise OperationalCapabilityError("ATTESTATION: " + attestation.blocked_reason)
        seal("ATTESTATION", attestation.evidence)
        if use_approval is None and use_approval_factory is not None:
            use_approval = use_approval_factory(attestation)
        authorization = authorize_candidate_use(
            SkillInstallRequest(decision=decision, evaluation=evaluation, resolution=resolution, review=review,
                approval=install_approval, install_plan=install_plan, project_id=context.project_id,
                gate_id=context.gate_id, lv_id=context.lv_id, canonical_plan_sha256=context.canonical_plan_sha256,
                project_root=project_root, target_skill_root=f"{project_root}/.agents/skills", timestamp=timestamp),
            install, attestation, use_approval, timestamp=timestamp)
        if not authorization.candidate_use_authorized:
            raise OperationalCapabilityError("USE_AUTHORIZATION: " + authorization.blocked_reason)
        seal("USE_AUTHORIZATION", authorization.authorization_evidence)
        target_ledger = ledger if ledger is not None else {"used_assets": [], "use_authorized_candidates": [], "use_authorization_evidence_references": [], "gate_passed": False}
        used = transition_used_asset(target_ledger, SkillInstallRequest(decision=decision, evaluation=evaluation, resolution=resolution, review=review,
            approval=install_approval, install_plan=install_plan, project_id=context.project_id, gate_id=context.gate_id,
            lv_id=context.lv_id, canonical_plan_sha256=context.canonical_plan_sha256, project_root=project_root,
            target_skill_root=f"{project_root}/.agents/skills", timestamp=timestamp), install, authorization, timestamp=timestamp)
        seal("USED_ASSETS", used)
    except OperationalCapabilityError as exc:
        stage = str(exc).split(":", 1)[0] if ":" in str(exc) else (next((s for s in _CONCRETE_STAGES if s not in records), "UNKNOWN"))
        return OperationalCapabilityResult("BLOCKED", "GAP", False, None, records, stage, str(exc), gate_passed=False)
    use = records["USE_AUTHORIZATION"]["payload"]
    install = records["INSTALL"]["payload"]
    attestation = records["ATTESTATION"]["payload"]
    selection = RuntimeSelection(
        asset_id=str(use["stable_asset_identifier"]), skill_id=str(use["candidate_id"]),
        installed_target=str(use["target"]), artifact_digest=str(install["installed_content_digest"]),
        attestation_evidence_reference="sha256:" + str(attestation["attestation_digest"]),
        use_authorization_evidence_reference="sha256:" + str(use["authorization_digest"]),
        capability_requirement=requirement.capability_id, project_id=context.project_id,
        gate_id=context.gate_id, lv_id=context.lv_id, canonical_plan_sha256=context.canonical_plan_sha256,
        source="INSTALLED_PROJECT_SKILL",
    )
    return OperationalCapabilityResult("READY_FOR_WORKER", "GAP", True, selection, records, gate_passed=False)


def run_canonical_capability_prerequisite(
    *, plan: object, lv_id: str, sources: CanonicalCapabilityRuntimeSources | None,
    verified_checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
) -> CanonicalCapabilityPrerequisiteResult:
    """Resolve one canonical requirement immediately before WORKER."""
    derivation = derive_capability_requirements(plan, lv_id)
    if derivation.status == "NO_CAPABILITY_REQUIREMENT":
        return CanonicalCapabilityPrerequisiteResult(
            "NO_CAPABILITY_REQUIREMENT", True, None, derivation, gate_passed=False)
    if derivation.status != "REQUIRED":
        status = "ESCALATION_REQUIRED" if derivation.status == "ESCALATION_REQUIRED" else "CAPABILITY_BLOCKED"
        return CanonicalCapabilityPrerequisiteResult(
            status, False, None, derivation, blocked_reason=derivation.blocked_reason, gate_passed=False)
    lv = next(item for item in getattr(plan, "lvs", ()) if getattr(item, "lv_id", None) == lv_id)
    envelope = derivation.envelopes[0]
    if not envelope.valid(project_id=getattr(plan, "project_id", ""), gate_id=getattr(lv, "gate_id", ""),
                          lv_id=lv_id, canonical_plan_sha256=getattr(plan, "canonical_plan_sha256", ""),
                          owned_files=getattr(lv, "owned_files", ()), execution=getattr(lv, "execution", "")):
        return CanonicalCapabilityPrerequisiteResult(
            "CAPABILITY_BLOCKED", False, None, derivation,
            blocked_reason="canonical requirement envelope drift", gate_passed=False)
    if not isinstance(sources, CanonicalCapabilityRuntimeSources):
        return CanonicalCapabilityPrerequisiteResult(
            "CAPABILITY_BLOCKED", False, None, derivation,
            blocked_reason="production capability sources are missing", gate_passed=False)
    checkpoints = verified_checkpoints if verified_checkpoints is not None else sources.verified_checkpoints
    if checkpoints is not None:
        if not isinstance(checkpoints, Mapping):
            return CanonicalCapabilityPrerequisiteResult(
                "CAPABILITY_BLOCKED", False, None, derivation,
                blocked_reason="verified capability checkpoints are malformed", gate_passed=False)
        for stage, record in checkpoints.items():
            if not isinstance(stage, str) or not isinstance(record, Mapping):
                return CanonicalCapabilityPrerequisiteResult(
                    "CAPABILITY_BLOCKED", False, None, derivation,
                    blocked_reason="verified capability checkpoint record is malformed", gate_passed=False)
    try:
        inventory_sources = production_inventory_sources(
            isolation=sources.isolation, project_manifest_evidence=sources.project_manifest_evidence,
            global_manifest_evidence=sources.global_manifest_evidence)
    except OperationalCapabilityError as exc:
        return CanonicalCapabilityPrerequisiteResult(
            "CAPABILITY_BLOCKED", False, None, derivation, blocked_reason=str(exc), gate_passed=False)
    requirement = envelope.requirement(getattr(lv, "owned_files", ()))
    context = DryRunExecutionContext(
        getattr(plan, "project_id", ""), getattr(lv, "gate_id", ""), lv_id,
        getattr(plan, "canonical_plan_sha256", ""), getattr(plan, "project_root", ""))
    existing = run_operational_capability_dry_run(
        context=context, requirement=requirement, project_assets=inventory_sources.project_assets,
        global_assets=inventory_sources.global_assets, agent_registry=inventory_sources.agent_registry)
    if existing.route == "EXISTING" and existing.status == "READY_FOR_WORKER":
        selection = existing.runtime_selection
        assert selection is not None
        provider = ("project-isolation-asset-manifest" if selection.source == "PROJECT"
                    else "runtime.agents.AGENT_REGISTRY")
        decision = ExistingCapabilityDecision(
            envelope.requirement_digest, selection.asset_id, selection.source, provider,
            str(selection.attestation_evidence_reference).removeprefix("sha256:"),
            envelope.project_id, envelope.gate_id, envelope.lv_id, envelope.canonical_plan_sha256)
        decision = dataclasses.replace(decision, decision_digest=decision.expected_digest())
        if not decision.valid():
            return CanonicalCapabilityPrerequisiteResult(
                "CAPABILITY_BLOCKED", False, None, derivation, blocked_reason="existing decision seal failed")
        return CanonicalCapabilityPrerequisiteResult(
            "EXISTING_CAPABILITY_READY", True, selection, derivation, existing, decision, gate_passed=False)
    approval_values = dict(project_id=envelope.project_id, gate_id=envelope.gate_id, lv_id=envelope.lv_id,
                           canonical_plan_sha256=envelope.canonical_plan_sha256)
    try:
        if sources.discovery_approval is None:
            raise OperationalCapabilityError("skill_discovery_read_only approval is missing")
        discovery_approval = load_capability_approval(
            sources.isolation, sources.discovery_approval.relative, intent="skill_discovery_read_only",
            evidence_digest=sources.discovery_approval.evidence_digest, **approval_values)
    except OperationalCapabilityError as exc:
        return CanonicalCapabilityPrerequisiteResult(
            "CAPABILITY_BLOCKED", False, None, derivation, blocked_reason=str(exc), gate_passed=False)
    def install_factory(evaluation: Any, review: Any, plan_artifact: Any) -> object:
        if sources.install_approval is None:
            return None
        return load_capability_approval(
            sources.isolation, sources.install_approval.relative, intent="project_skill_install",
            evidence_digest=sources.install_approval.evidence_digest,
            candidate_id=str(evaluation.evidence.get("candidate_id", "")), **approval_values)
    def use_factory(attestation: Any) -> object:
        if sources.use_approval is None:
            return None
        candidate = ""
        if sources.install_approval is not None:
            install = load_capability_approval(
                sources.isolation, sources.install_approval.relative, intent="project_skill_install",
                evidence_digest=sources.install_approval.evidence_digest, **approval_values)
            candidate = str(getattr(install, "candidate_id", ""))
        return load_capability_approval(
            sources.isolation, sources.use_approval.relative, intent="project_skill_use",
            evidence_digest=sources.use_approval.evidence_digest, candidate_id=candidate, **approval_values)
    if (sources.discovery_transport is None or sources.resolution_transport is None
            or sources.http_executor is None or not sources.fixture_repository_root):
        return CanonicalCapabilityPrerequisiteResult(
            "CAPABILITY_BLOCKED", False, None, derivation,
            blocked_reason="concrete capability boundary is incomplete", gate_passed=False)
    result = run_concrete_module_fixture_dry_run(
        context=context, requirement=requirement, discovery_approval=discovery_approval,
        discovery_transport=sources.discovery_transport, resolution_transport=sources.resolution_transport,
        http_executor=sources.http_executor, install_approval_factory=install_factory,
        use_approval_factory=use_factory, fixture_repository_root=sources.fixture_repository_root,
        project_root=getattr(plan, "project_root", ""), candidate_metadata=sources.candidate_metadata,
        permissions=requirement.required_permissions, owned_files=requirement.owned_files,
        timestamp=sources.timestamp, project_assets=inventory_sources.project_assets,
        global_assets=inventory_sources.global_assets, agent_registry=inventory_sources.agent_registry,
        ledger=sources.ledger, checkpoint_sink=sources.checkpoint_sink,
        verified_checkpoints=checkpoints)
    if result.status != "READY_FOR_WORKER":
        return CanonicalCapabilityPrerequisiteResult(
            "CAPABILITY_BLOCKED", False, None, derivation, result,
            blocked_reason=result.blocked_reason, gate_passed=False)
    return CanonicalCapabilityPrerequisiteResult(
        "DISCOVERED_CAPABILITY_READY", True, result.runtime_selection, derivation, result, gate_passed=False)
