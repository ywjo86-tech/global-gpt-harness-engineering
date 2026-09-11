from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .approval_gate import DANGEROUS, classify_discovery_intent
from .capability_inventory import inventory_capabilities
from .lv_execution_package import canonical_json_bytes
from .project_isolation import AssetManifest
from .schemas import CandidateAdoptionState, CandidateEvaluationState, CandidateRisk, CapabilityRequirement
from .skill_candidate_evaluator import CandidateEvaluationResult, verify_evaluation_evidence

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMMUTABLE_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
INSTALL_METHOD_UNVERIFIED = "INSTALL_METHOD_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class SupplyChainReview:
    candidate_id: str
    source: str
    repository: str
    maintainer: str
    provider: str
    immutable_revision: str
    candidate_path: str
    skill_md_digest: str
    resolver_evidence_digest: str
    license: str
    package_install_required: bool
    shell_execution: bool
    network_required: bool
    secret_required: bool
    file_write_scope: tuple[str, ...]
    install_scope: str
    external_service: bool
    paid_service: bool
    deployment: bool
    destructive_action: bool
    requested_permissions: tuple[str, ...]
    owned_file_scope: tuple[str, ...]
    provenance_state: str
    evaluator_evidence_digest: str
    review_state: str
    review_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("review_digest")
        return value

    def expected_digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.unsigned())).hexdigest()

    def valid(self) -> bool:
        return (
            self.review_state == "COMPLETE" and self.install_scope in {"project", "global"}
            and all((self.candidate_id, self.source, self.repository, self.maintainer,
                     self.provider, self.candidate_path, self.license))
            and bool(_IMMUTABLE_REVISION.fullmatch(self.immutable_revision))
            and bool(_SHA256.fullmatch(self.skill_md_digest))
            and bool(_SHA256.fullmatch(self.resolver_evidence_digest))
            and self.provenance_state == "VERIFIED"
            and bool(_SHA256.fullmatch(self.evaluator_evidence_digest))
            and self.review_digest == self.expected_digest()
        )


def seal_supply_chain_review(**values: Any) -> SupplyChainReview:
    review = SupplyChainReview(**values)
    return SupplyChainReview(**review.unsigned(), review_digest=review.expected_digest())


@dataclass(frozen=True, slots=True)
class ProjectInstallApproval:
    project_id: str
    gate_id: str
    lv_id: str
    intent: str
    candidate_id: str
    evaluation_digest: str
    supply_chain_review_digest: str
    install_scope: str
    canonical_plan_sha256: str
    status: str
    evidence_reference: str
    approval_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self); value.pop("approval_digest")
        return value

    def expected_digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.unsigned())).hexdigest()

    def valid(self) -> bool:
        return (self.status == "ACTIVE" and self.intent == "project_skill_install"
                and self.install_scope == "project" and bool(self.evidence_reference)
                and all(_SHA256.fullmatch(value) for value in (
                    self.evaluation_digest, self.supply_chain_review_digest,
                    self.canonical_plan_sha256, self.approval_digest))
                and self.approval_digest == self.expected_digest())


def seal_project_install_approval(**values: Any) -> ProjectInstallApproval:
    approval = ProjectInstallApproval(**values)
    return ProjectInstallApproval(**approval.unsigned(), approval_digest=approval.expected_digest())


@dataclass(frozen=True, slots=True)
class InstallPlanArtifact:
    candidate_id: str
    target_project: str
    target_scope: str
    proposed_install_location: str
    expected_source: str
    expected_revision: str
    expected_files: tuple[str, ...]
    required_permissions: tuple[str, ...]
    required_package_runtime: tuple[str, ...]
    network_required: bool
    operation_type: str
    rollback_expectation: str
    evaluation_evidence_reference: str
    supply_chain_evidence_reference: str
    approval_requirement: str
    install_method_state: str
    plan_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self); value.pop("plan_digest")
        return value

    def expected_digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.unsigned())).hexdigest()

    def valid(self) -> bool:
        return bool(_SHA256.fullmatch(self.plan_digest)) and self.plan_digest == self.expected_digest()


def seal_install_plan(**values: Any) -> InstallPlanArtifact:
    plan = InstallPlanArtifact(**values)
    return InstallPlanArtifact(**plan.unsigned(), plan_digest=plan.expected_digest())


@dataclass(frozen=True, slots=True)
class CandidateAdoptionDecision:
    capability_requirement: CapabilityRequirement
    candidate_id: str
    evaluation_evidence_reference: str
    evaluation_state: str
    duplicate_result: str
    adoption_state: CandidateAdoptionState
    install_required: bool
    install_scope: str
    install_authorized: bool
    candidate_use_authorized: bool
    blocked_reason: str
    escalation_reason: str
    approval_evidence_reference: str
    supply_chain_review_reference: str
    install_plan_evidence_reference: str
    decision_digest: str

    def ledger_projection(self) -> dict[str, Any]:
        return {
            "adoption_decisions": [self.decision_digest], "install_required": self.install_required,
            "install_authorized": self.install_authorized, "install_scope": self.install_scope,
            "install_plan_evidence_reference": self.install_plan_evidence_reference,
            "supply_chain_evidence_reference": self.supply_chain_review_reference,
            "candidate_use_authorized": False,
        }


def decide_adoption(
    *, project_id: str, canonical_plan_sha256: str, gate_lvs: Mapping[str, Sequence[str]],
    requirement: CapabilityRequirement, evaluation: CandidateEvaluationResult,
    candidate_risk: CandidateRisk, install_scope: str,
    project_assets: Sequence[AssetManifest] = (), global_assets: Sequence[AssetManifest] = (),
    agent_registry: Mapping[str, object] = {}, review: SupplyChainReview | None = None,
    approval: ProjectInstallApproval | None = None, install_plan: InstallPlanArtifact | None = None,
) -> CandidateAdoptionDecision:
    blocked = ""; escalated = ""; state = CandidateAdoptionState.BLOCKED
    candidate_id = str(evaluation.evidence.get("candidate_id", ""))
    evidence_digest = str(evaluation.evidence.get("evidence_digest", ""))
    inventory = inventory_capabilities(
        project_id=project_id, canonical_plan_sha256=canonical_plan_sha256,
        gate_lvs=gate_lvs, requirements=(requirement,), project_assets=project_assets,
        global_assets=global_assets, agent_registry=agent_registry, phase="GATE_TIME")
    duplicate = "EXACT_DUPLICATE" if not inventory.gaps else "VERIFIED_GAP"
    install_required = duplicate == "VERIFIED_GAP"
    if not inventory.authoritative:
        blocked = "existing capability revalidation failed"
    elif duplicate == "EXACT_DUPLICATE":
        state = CandidateAdoptionState.SAFE_FOR_CONSIDERATION
    elif evaluation.evaluation_state != CandidateEvaluationState.SAFE_FOR_CONSIDERATION:
        blocked = "candidate is not SAFE_FOR_CONSIDERATION"
    elif not evaluation.evidence_reference or not verify_evaluation_evidence(evaluation.evidence):
        blocked = "evaluation evidence is missing or has drifted"
    elif (evaluation.evidence.get("evaluation_state") != evaluation.evaluation_state.value
          or evaluation.evidence.get("capability_requirement") != requirement.capability_id
          or evaluation.evidence.get("project_id") != project_id
          or evaluation.evidence.get("gate_id") != requirement.gate_id
          or evaluation.evidence.get("lv_id") != requirement.lv_id):
        blocked = "candidate/evaluation evidence binding mismatch"
    elif install_scope == "global" or candidate_risk.global_change:
        state = CandidateAdoptionState.ESCALATION_REQUIRED; escalated = "Global install/change"
    elif candidate_risk.secret or candidate_risk.destructive_action or candidate_risk.deployment or candidate_risk.paid_service:
        state = CandidateAdoptionState.ESCALATION_REQUIRED; escalated = "candidate requires dangerous capability"
    elif review is None or review.review_state != "COMPLETE":
        state = CandidateAdoptionState.PENDING_SUPPLY_CHAIN_REVIEW; blocked = "supply-chain review is incomplete"
    elif (not review.valid() or review.candidate_id != candidate_id
          or review.evaluator_evidence_digest != evidence_digest
          or review.skill_md_digest != evaluation.evidence.get("skill_md_digest")
          or review.provider != evaluation.evidence.get("provider")
          or review.repository != evaluation.evidence.get("repository")
          or review.immutable_revision != evaluation.evidence.get("immutable_revision")
          or review.candidate_path != evaluation.evidence.get("candidate_path")
          or review.resolver_evidence_digest != evaluation.evidence.get("resolver_evidence_digest")):
        blocked = "supply-chain review provenance or binding mismatch"
    elif review.secret_required or review.destructive_action or review.deployment or review.paid_service:
        state = CandidateAdoptionState.ESCALATION_REQUIRED; escalated = "supply-chain review requires escalation"
    elif review.install_scope != "project" or set(requirement.required_permissions) - set(review.requested_permissions):
        blocked = "permission or project scope mismatch"
    elif set(requirement.owned_files) - set(review.owned_file_scope):
        blocked = "owned-file mismatch"
    elif install_plan is None or not install_plan.valid():
        blocked = "install plan is missing or has drifted"
    elif (install_plan.candidate_id != candidate_id or install_plan.target_project != project_id
          or install_plan.target_scope != install_scope
          or install_plan.expected_source != review.source
          or install_plan.expected_revision != review.immutable_revision
          or set(requirement.required_permissions) - set(install_plan.required_permissions)):
        blocked = "install plan binding mismatch"
    elif install_plan.install_method_state == INSTALL_METHOD_UNVERIFIED:
        blocked = "install method is unverified"
    elif review.package_install_required or classify_discovery_intent("project_skill_install").classification == DANGEROUS:
        state = CandidateAdoptionState.ESCALATION_REQUIRED; escalated = "Dangerous package operation requires escalation"
    elif approval is None:
        state = CandidateAdoptionState.APPROVAL_REQUIRED; blocked = "separate project install approval is required"
    elif not approval.valid() or any((approval.project_id != project_id, approval.gate_id != requirement.gate_id,
             approval.lv_id != requirement.lv_id, approval.candidate_id != candidate_id,
             approval.evaluation_digest != evidence_digest, approval.supply_chain_review_digest != review.review_digest,
             approval.canonical_plan_sha256 != canonical_plan_sha256)):
        blocked = "project install approval binding mismatch"
    else:
        state = CandidateAdoptionState.INSTALL_AUTHORIZED
    install_authorized = state == CandidateAdoptionState.INSTALL_AUTHORIZED
    payload = {
        "capability_requirement": requirement.capability_id, "candidate_id": candidate_id,
        "evaluation_evidence_reference": evaluation.evidence_reference,
        "evaluation_state": evaluation.evaluation_state.value, "duplicate_result": duplicate,
        "adoption_state": state.value, "install_required": install_required, "install_scope": install_scope,
        "install_authorized": install_authorized, "candidate_use_authorized": False,
        "blocked_reason": blocked, "escalation_reason": escalated,
        "approval_evidence_reference": approval.evidence_reference if approval else "",
        "supply_chain_review_reference": f"sha256:{review.review_digest}" if review else "",
        "install_plan_evidence_reference": f"sha256:{install_plan.plan_digest}" if install_plan else "",
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return CandidateAdoptionDecision(requirement, candidate_id, evaluation.evidence_reference,
        evaluation.evaluation_state.value, duplicate, state, install_required, install_scope,
        install_authorized, False, blocked, escalated, payload["approval_evidence_reference"],
        payload["supply_chain_review_reference"], payload["install_plan_evidence_reference"], digest)
