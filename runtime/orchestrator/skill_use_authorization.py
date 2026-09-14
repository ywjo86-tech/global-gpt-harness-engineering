from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .candidate_content_resolver import verify_resolution_evidence
from .lv_execution_package import canonical_json_bytes
from .schemas import CandidateUseState
from .skill_adoption import ProjectInstallApproval
from .skill_candidate_evaluator import verify_evaluation_evidence
from .skill_installer import (MANIFEST_NAME, SkillInstallRequest, SkillInstallResult,
                              verify_installed_manifest)


ATTESTATION_CONTRACT = "orchestration.installed-skill-attestation.v1"
USE_APPROVAL_CONTRACT = "orchestration.project-skill-use-approval.v1"
USE_AUTHORIZATION_CONTRACT = "orchestration.project-skill-use-authorization.v1"
ASSET_BINDING_CONTRACT = "orchestration.authorized-installed-skill-asset.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sealed(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = _digest(canonical_json_bytes(result))
    return result


def _verify_seal(value: Mapping[str, Any], field: str) -> bool:
    try:
        unsigned = dict(value)
        digest = unsigned.pop(field)
        return bool(_SHA256.fullmatch(str(digest)) and digest == _digest(canonical_json_bytes(unsigned)))
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class ProjectUseApproval:
    project_id: str
    gate_id: str
    lv_id: str
    candidate_id: str
    canonical_plan_sha256: str
    install_approval_digest: str
    attestation_digest: str
    status: str
    intent: str
    evidence_reference: str
    approval_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("approval_digest")
        value["schema_version"] = USE_APPROVAL_CONTRACT
        return value

    def expected_digest(self) -> str:
        return _digest(canonical_json_bytes(self.unsigned()))

    def valid(self) -> bool:
        return bool(
            self.status == "ACTIVE"
            and self.intent == "project_skill_use"
            and self.evidence_reference
            and all(_SHA256.fullmatch(value) for value in (
                self.canonical_plan_sha256, self.install_approval_digest,
                self.attestation_digest, self.approval_digest,
            ))
            and self.approval_digest == self.expected_digest()
        )


def seal_project_use_approval(**values: Any) -> ProjectUseApproval:
    approval = ProjectUseApproval(**values)
    return ProjectUseApproval(**{key: value for key, value in asdict(approval).items() if key != "approval_digest"},
                              approval_digest=approval.expected_digest())


@dataclass(frozen=True, slots=True)
class InstalledArtifactAttestation:
    state: CandidateUseState
    evidence: Mapping[str, Any]
    blocked_reason: str = ""
    escalation_reason: str = ""

    @property
    def attestation_digest(self) -> str:
        return str(self.evidence.get("attestation_digest", ""))


@dataclass(frozen=True, slots=True)
class SkillUseAuthorizationResult:
    attested: bool
    use_authorization_status: str
    candidate_use_authorized: bool
    authorization_evidence: Mapping[str, Any]
    authorization_evidence_reference: str
    blocked_reason: str
    escalation_reason: str
    decision_digest: str
    stable_asset_identifier: str = ""
    gate_passed: bool = False


def _blocked(reason: str, *, escalation: bool = False) -> InstalledArtifactAttestation:
    return InstalledArtifactAttestation(
        CandidateUseState.ESCALATION_REQUIRED if escalation else CandidateUseState.BLOCKED,
        {}, "" if escalation else reason, reason if escalation else "")


def _canonical_destination(request: SkillInstallRequest) -> tuple[Path, Path]:
    project = Path(request.project_root)
    skill_root = Path(request.target_skill_root)
    target = request.install_plan.proposed_install_location
    if request.install_plan.target_scope != "project" or target.startswith(("~/", "/")):
        raise PermissionError("Global/shared/non-project target requires escalation")
    if (not project.is_absolute() or not project.is_dir() or project.is_symlink()
            or project.resolve() != project or project.name != request.project_id):
        raise ValueError("project identity mismatch")
    canonical_root = project / ".agents" / "skills"
    if skill_root != canonical_root or not skill_root.is_dir() or skill_root.is_symlink() or skill_root.resolve() != skill_root:
        raise ValueError("canonical Project-local target mismatch")
    parts = Path(target).parts
    if len(parts) != 3 or parts[:2] != (".agents", "skills") or parts[2] in {"", ".", ".."}:
        raise ValueError("canonical Project-local target mismatch")
    destination = skill_root / parts[2]
    if destination.parent != skill_root:
        raise ValueError("path containment mismatch")
    return project, destination


def attest_installed_artifact(request: SkillInstallRequest, install: SkillInstallResult,
                              *, timestamp: str) -> InstalledArtifactAttestation:
    try:
        _, destination = _canonical_destination(request)
    except PermissionError as exc:
        return _blocked(str(exc), escalation=True)
    except Exception as exc:
        return _blocked(str(exc))
    try:
        if install.install_status not in {"INSTALL_COMPLETED", "IDENTICAL"}:
            raise ValueError("INSTALL_COMPLETED evidence is required")
        if not destination.exists() or destination.is_symlink() or not destination.is_dir():
            raise ValueError("installed destination missing or replaced")
        destination_stat = destination.stat(follow_symlinks=False)
        if stat.S_IMODE(destination_stat.st_mode) != 0o700 or destination_stat.st_uid != os.geteuid():
            raise ValueError("installed destination ownership or mode mismatch")
        entries = {item.name for item in destination.iterdir()}
        if entries != {"SKILL.md", MANIFEST_NAME}:
            raise ValueError("unexpected or missing installed file")
        skill_path = destination / "SKILL.md"
        manifest_path = destination / MANIFEST_NAME
        if skill_path.is_symlink() or manifest_path.is_symlink():
            raise ValueError("symlink is forbidden")
        if not skill_path.is_file() or not manifest_path.is_file():
            raise ValueError("installed file missing")
        if (skill_path.stat(follow_symlinks=False).st_uid != os.geteuid()
                or manifest_path.stat(follow_symlinks=False).st_uid != os.geteuid()):
            raise ValueError("installed file ownership mismatch")
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        manifest_digest = _digest(manifest_bytes)
        actual_skill_digest = _digest(skill_path.read_bytes())
        if (not verify_installed_manifest(manifest, destination)
                or not verify_resolution_evidence(request.resolution.evidence)
                or not verify_evaluation_evidence(request.evaluation.evidence)
                or not request.review.valid() or not request.approval.valid()
                or not request.install_plan.valid()):
            raise ValueError("installed or expected evidence seal is invalid")
        per_file = manifest.get("per_file_digest")
        if not isinstance(per_file, dict) or per_file != {"SKILL.md": actual_skill_digest}:
            raise ValueError("actual file digest mismatch")
        if manifest != dict(install.installed_file_manifest):
            raise ValueError("installation evidence drift")
        expected = request.resolution.evidence
        bindings = (
            manifest.get("candidate_id") == request.decision.candidate_id,
            manifest.get("repository") == expected.get("repository"),
            manifest.get("immutable_revision") == request.resolution.immutable_revision,
            manifest.get("installed_target") == request.install_plan.proposed_install_location,
            manifest.get("file_list") == ["SKILL.md"],
            manifest.get("aggregate_digest") == actual_skill_digest,
            manifest.get("skill_md_digest") == actual_skill_digest == request.resolution.skill_md_digest,
            manifest.get("project_id") == request.project_id,
            manifest.get("gate_id") == request.gate_id,
            manifest.get("lv_id") == request.lv_id,
            manifest.get("canonical_plan_sha256") == request.canonical_plan_sha256,
            manifest.get("install_plan_digest") == request.install_plan.plan_digest,
            manifest.get("approval_digest") == request.approval.approval_digest,
            manifest.get("resolver_evidence_digest") == expected.get("evidence_digest"),
            manifest.get("evaluation_evidence_digest") == request.evaluation.evidence.get("evidence_digest"),
            manifest.get("supply_chain_review_digest") == request.review.review_digest,
            manifest.get("installation_evidence_digest") == install.installation_evidence_digest,
        )
        if not all(bindings):
            raise ValueError("candidate/provenance/install evidence binding mismatch")
        permissions = manifest.get("permissions_metadata")
        expected_mode = int(str(permissions["SKILL.md"]), 8) if isinstance(permissions, dict) else -1
        actual_mode = stat.S_IMODE(skill_path.stat(follow_symlinks=False).st_mode)
        if actual_mode != expected_mode or expected_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWOTH | 0o111):
            raise ValueError("unsafe or changed file mode")
        if stat.S_IMODE(manifest_path.stat(follow_symlinks=False).st_mode) != 0o600:
            raise ValueError("installed manifest mode mismatch")
        evidence = _sealed({
            "schema_version": ATTESTATION_CONTRACT,
            "project_id": request.project_id,
            "gate_id": request.gate_id,
            "lv_id": request.lv_id,
            "candidate_id": request.decision.candidate_id,
            "target": request.install_plan.proposed_install_location,
            "repository": manifest["repository"],
            "immutable_revision": manifest["immutable_revision"],
            "installed_manifest_digest": manifest_digest,
            "actual_aggregate_digest": actual_skill_digest,
            "skill_md_digest": actual_skill_digest,
            "installation_evidence_ref": "sha256:" + install.installation_evidence_digest,
            "resolver_evidence_ref": "sha256:" + str(manifest["resolver_evidence_digest"]),
            "evaluation_evidence_ref": "sha256:" + str(manifest["evaluation_evidence_digest"]),
            "supply_chain_review_ref": "sha256:" + str(manifest["supply_chain_review_digest"]),
            "install_plan_digest": request.install_plan.plan_digest,
            "install_approval_digest": request.approval.approval_digest,
            "attestation_state": CandidateUseState.ATTESTED.value,
            "timestamp": timestamp,
        }, "attestation_digest")
        return InstalledArtifactAttestation(CandidateUseState.ATTESTED, evidence)
    except Exception as exc:
        return _blocked(str(exc))


def verify_attestation_evidence(evidence: Mapping[str, Any]) -> bool:
    return bool(evidence.get("schema_version") == ATTESTATION_CONTRACT
                and evidence.get("attestation_state") == CandidateUseState.ATTESTED.value
                and _verify_seal(evidence, "attestation_digest"))


def _same_artifact(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    ignored = {"timestamp", "attestation_digest"}
    return ({key: value for key, value in left.items() if key not in ignored}
            == {key: value for key, value in right.items() if key not in ignored})


def _authorization_result(status: CandidateUseState, *, reason: str = "", escalation: str = "",
                          evidence: Mapping[str, Any] = {}, attested: bool = False) -> SkillUseAuthorizationResult:
    decision = _digest(canonical_json_bytes({"status": status.value, "reason": reason,
                                             "escalation": escalation, "evidence": evidence}))
    authorized = status == CandidateUseState.USE_AUTHORIZED
    stable = str(evidence.get("stable_asset_identifier", "")) if authorized else ""
    return SkillUseAuthorizationResult(attested, status.value, authorized, evidence,
        "sha256:" + str(evidence.get("authorization_digest", "")) if authorized else "",
        reason, escalation, decision, stable, False)


def authorize_candidate_use(request: SkillInstallRequest, install: SkillInstallResult,
                            attestation: InstalledArtifactAttestation,
                            use_approval: ProjectUseApproval | None, *, timestamp: str) -> SkillUseAuthorizationResult:
    if attestation.state != CandidateUseState.ATTESTED or not verify_attestation_evidence(attestation.evidence):
        return _authorization_result(CandidateUseState.BLOCKED, reason="valid installed artifact attestation is required")
    fresh = attest_installed_artifact(request, install, timestamp=timestamp)
    if fresh.state == CandidateUseState.ESCALATION_REQUIRED:
        return _authorization_result(fresh.state, escalation=fresh.escalation_reason)
    if fresh.state != CandidateUseState.ATTESTED:
        return _authorization_result(CandidateUseState.BLOCKED, reason="time-of-use revalidation failed: " + fresh.blocked_reason)
    if not _same_artifact(fresh.evidence, attestation.evidence):
        return _authorization_result(CandidateUseState.BLOCKED, reason="attested artifact drift")
    review = request.review
    if (review.install_scope != "project" or review.secret_required or review.destructive_action
            or review.deployment or review.paid_service or review.network_required
            or set(request.decision.capability_requirement.required_permissions) - set(review.requested_permissions)
            or set(request.decision.capability_requirement.owned_files) - set(review.owned_file_scope)):
        escalation = review.secret_required or review.destructive_action or review.deployment or review.paid_service
        return _authorization_result(CandidateUseState.ESCALATION_REQUIRED if escalation else CandidateUseState.BLOCKED,
            reason="" if escalation else "permissions or owned-file scope mismatch",
            escalation="runtime requirement requires escalation" if escalation else "", attested=True)
    if use_approval is None or not use_approval.valid():
        return _authorization_result(CandidateUseState.BLOCKED,
            reason="separate ACTIVE use approval is required", attested=True)
    approval_binding = (
        use_approval.project_id == request.project_id,
        use_approval.gate_id == request.gate_id,
        use_approval.lv_id == request.lv_id,
        use_approval.candidate_id == request.decision.candidate_id,
        use_approval.canonical_plan_sha256 == request.canonical_plan_sha256,
        use_approval.install_approval_digest == request.approval.approval_digest,
        use_approval.attestation_digest == fresh.attestation_digest,
    )
    if not all(approval_binding):
        return _authorization_result(CandidateUseState.BLOCKED,
            reason="use approval binding mismatch", attested=True)
    stable_payload = {
        "schema_version": ASSET_BINDING_CONTRACT, "project_id": request.project_id,
        "gate_id": request.gate_id, "lv_id": request.lv_id,
        "candidate_id": request.decision.candidate_id,
        "target": request.install_plan.proposed_install_location,
        "attestation_digest": fresh.attestation_digest,
        "use_approval_digest": use_approval.approval_digest,
        "installed_manifest_digest": fresh.evidence["installed_manifest_digest"],
    }
    stable_id = "installed-skill:sha256:" + _digest(canonical_json_bytes(stable_payload))
    evidence = _sealed({
        **stable_payload, "schema_version": USE_AUTHORIZATION_CONTRACT,
        "stable_asset_identifier": stable_id,
        "authorization_status": CandidateUseState.USE_AUTHORIZED.value,
        "candidate_use_authorized": True,
        "ready_for_runtime_selection": True,
        "gate_passed": False,
        "timestamp": timestamp,
    }, "authorization_digest")
    return _authorization_result(CandidateUseState.USE_AUTHORIZED, evidence=evidence, attested=True)


def verify_use_authorization_evidence(evidence: Mapping[str, Any]) -> bool:
    return bool(evidence.get("schema_version") == USE_AUTHORIZATION_CONTRACT
                and evidence.get("authorization_status") == CandidateUseState.USE_AUTHORIZED.value
                and evidence.get("candidate_use_authorized") is True
                and evidence.get("gate_passed") is False
                and _verify_seal(evidence, "authorization_digest"))


def transition_used_asset(ledger: MutableMapping[str, Any], request: SkillInstallRequest,
                          install: SkillInstallResult, authorization: SkillUseAuthorizationResult,
                          *, timestamp: str) -> Mapping[str, Any]:
    if (not authorization.candidate_use_authorized
            or not verify_use_authorization_evidence(authorization.authorization_evidence)):
        raise ValueError("USE_AUTHORIZED evidence is required")
    evidence = authorization.authorization_evidence
    sealed_asset = str(evidence.get("stable_asset_identifier", ""))
    sealed_reference = "sha256:" + str(evidence.get("authorization_digest", ""))
    expected_decision = _authorization_result(
        CandidateUseState.USE_AUTHORIZED, evidence=evidence, attested=True).decision_digest
    if (authorization.stable_asset_identifier != sealed_asset
            or authorization.authorization_evidence_reference != sealed_reference
            or authorization.decision_digest != expected_decision):
        raise ValueError("use authorization result/evidence binding mismatch")
    current = ledger.get("used_assets", [])
    references = ledger.get("use_authorization_evidence_references", [])
    candidates = ledger.get("use_authorized_candidates", [])
    gate_passed = ledger.get("gate_passed", False)
    if any(not isinstance(value, list) for value in (current, references, candidates)):
        raise ValueError("ledger authorization containers are invalid")
    if type(gate_passed) is not bool:
        raise ValueError("ledger Gate state is invalid")
    fresh = attest_installed_artifact(request, install, timestamp=timestamp)
    if (fresh.state != CandidateUseState.ATTESTED
            or evidence.get("candidate_id") != request.decision.candidate_id
            or evidence.get("target") != request.install_plan.proposed_install_location
            or evidence.get("installed_manifest_digest") != fresh.evidence.get("installed_manifest_digest")):
        raise ValueError("authorized installed asset binding is stale or invalid")
    asset = sealed_asset
    ledger["used_assets"] = list(dict.fromkeys([*current, asset]))
    ledger["use_authorization_evidence_references"] = list(dict.fromkeys(
        [*references, sealed_reference]))
    ledger["use_authorized_candidates"] = list(dict.fromkeys(
        [*candidates, request.decision.candidate_id]))
    ledger["gate_passed"] = gate_passed
    return {"state": CandidateUseState.USED_ASSET.value, "stable_asset_identifier": asset,
            "gate_passed": ledger["gate_passed"]}


def validate_authorization_ledger_handoff(ledger: Mapping[str, Any],
                                          handoff: Mapping[str, Any],
                                          authorizations: SkillUseAuthorizationResult
                                          | Sequence[SkillUseAuthorizationResult]) -> None:
    records = ((authorizations,) if isinstance(authorizations, SkillUseAuthorizationResult)
               else tuple(authorizations))
    if not records or any(not record.candidate_use_authorized
                          or not verify_use_authorization_evidence(record.authorization_evidence)
                          for record in records):
        raise ValueError("handoff authorization evidence is invalid")
    fields = ("used_assets", "use_authorized_candidates",
              "use_authorization_evidence_references")
    for field in fields:
        left, right = ledger.get(field), handoff.get(field)
        if (not isinstance(left, list) or not left or len(left) != len(set(left))
                or left != right or any(not isinstance(value, str) or not value for value in left)):
            raise ValueError("ledger/handoff use authorization evidence mismatch")
    if any(not value.startswith("installed-skill:sha256:") for value in ledger["used_assets"]):
        raise ValueError("used_assets contains a non-installed candidate identifier")
    expected_assets = {str(record.authorization_evidence.get("stable_asset_identifier", ""))
                       for record in records}
    expected_candidates = {str(record.authorization_evidence.get("candidate_id", ""))
                           for record in records}
    expected_references = {"sha256:" + str(record.authorization_evidence.get("authorization_digest", ""))
                           for record in records}
    if (set(ledger["used_assets"]) != expected_assets
            or set(ledger["use_authorized_candidates"]) != expected_candidates
            or set(ledger["use_authorization_evidence_references"]) != expected_references):
        raise ValueError("ledger/handoff semantic authorization binding mismatch")
    if ledger.get("gate_passed") != handoff.get("gate_passed"):
        raise ValueError("ledger/handoff Gate state mismatch")
