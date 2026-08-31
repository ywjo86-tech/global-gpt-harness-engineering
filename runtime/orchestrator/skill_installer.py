from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import unquote

from .candidate_content_resolver import CandidateContentResolutionResult, verify_resolution_evidence
from .lv_execution_package import canonical_json_bytes
from .schemas import CandidateAdoptionState
from .skill_adoption import (CandidateAdoptionDecision, InstallPlanArtifact,
                             ProjectInstallApproval, SupplyChainReview)
from .skill_candidate_evaluator import CandidateEvaluationResult, verify_evaluation_evidence


INSTALLATION_CONTRACT = "orchestration.project-skill-installation.v1"
MANIFEST_NAME = ".codex-install-manifest.json"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class SkillInstallRequest:
    decision: CandidateAdoptionDecision
    evaluation: CandidateEvaluationResult
    resolution: CandidateContentResolutionResult
    review: SupplyChainReview
    approval: ProjectInstallApproval
    install_plan: InstallPlanArtifact
    project_id: str
    gate_id: str
    lv_id: str
    canonical_plan_sha256: str
    project_root: str | Path
    target_skill_root: str | Path
    timestamp: str
    source_mode: int = 0o600


@dataclass(frozen=True, slots=True)
class SkillInstallResult:
    install_attempted: bool
    install_status: str
    target_location: str
    installed_file_manifest: Mapping[str, Any]
    installed_content_digest: str
    rollback_evidence: Mapping[str, Any]
    blocked_reason: str
    escalation_reason: str
    installation_evidence_digest: str
    candidate_use_authorized: bool = False
    used_assets_changed: bool = False
    gate_passed: bool = False


InstallHook = Callable[[str, Path], None]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError("unsafe relative install path")
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if decoded != value:
        raise ValueError("encoded traversal is forbidden")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts or "." in path.parts:
        raise ValueError("unsafe relative install path")
    return path


def _has_symlink(path: Path, root: Path) -> bool:
    cursor = root
    if root.is_symlink():
        return True
    for part in path.relative_to(root).parts:
        cursor /= part
        if cursor.is_symlink():
            return True
    return False


def _aggregate(files: Mapping[str, str]) -> str:
    # Phase 3E v1 resolves exactly one immutable artifact, so its aggregate is
    # deliberately the same digest bound by the resolver and both verifiers.
    if set(files) == {"SKILL.md"}:
        return str(files["SKILL.md"])
    return _digest(canonical_json_bytes(dict(sorted(files.items()))))


def _manifest_unsigned(request: SkillInstallRequest, target: str, file_digests: Mapping[str, str]) -> dict[str, Any]:
    resolution = request.resolution.evidence
    value = {
        "schema_version": INSTALLATION_CONTRACT,
        "candidate_id": request.decision.candidate_id,
        "repository": resolution.get("repository", ""),
        "immutable_revision": request.resolution.immutable_revision,
        "installed_target": target,
        "file_list": sorted(file_digests),
        "per_file_digest": dict(sorted(file_digests.items())),
        "aggregate_digest": _aggregate(file_digests),
        "skill_md_digest": file_digests.get("SKILL.md", ""),
        "permissions_metadata": {"SKILL.md": oct(request.source_mode & 0o777)},
        "installation_timestamp": request.timestamp,
        "project_id": request.project_id,
        "gate_id": request.gate_id,
        "lv_id": request.lv_id,
        "canonical_plan_sha256": request.canonical_plan_sha256,
        "install_plan_digest": request.install_plan.plan_digest,
        "approval_evidence_ref": request.approval.evidence_reference,
        "approval_digest": request.approval.approval_digest,
        "resolver_evidence_digest": resolution.get("evidence_digest", ""),
        "evaluation_evidence_digest": request.evaluation.evidence.get("evidence_digest", ""),
        "supply_chain_review_digest": request.review.review_digest,
        "candidate_use_authorized": False,
        "used_assets_changed": False,
        "gate_passed": False,
    }
    return value


def seal_installed_manifest(request: SkillInstallRequest, target: str, file_digests: Mapping[str, str]) -> dict[str, Any]:
    value = _manifest_unsigned(request, target, file_digests)
    value["installation_evidence_digest"] = _digest(canonical_json_bytes(value))
    return value


def verify_installed_manifest(manifest: Mapping[str, Any], destination: str | Path | None = None) -> bool:
    try:
        unsigned = dict(manifest)
        evidence_digest = unsigned.pop("installation_evidence_digest")
        if (unsigned.get("schema_version") != INSTALLATION_CONTRACT
                or not _SHA256.fullmatch(str(evidence_digest))
                or evidence_digest != _digest(canonical_json_bytes(unsigned))
                or unsigned.get("candidate_use_authorized") is not False
                or unsigned.get("used_assets_changed") is not False
                or unsigned.get("gate_passed") is not False):
            return False
        per_file = unsigned.get("per_file_digest")
        if not isinstance(per_file, Mapping) or set(per_file) != {"SKILL.md"}:
            return False
        permissions = unsigned.get("permissions_metadata")
        if (unsigned.get("file_list") != ["SKILL.md"]
                or unsigned.get("skill_md_digest") != per_file["SKILL.md"]
                or unsigned.get("aggregate_digest") != _aggregate(per_file)
                or not isinstance(permissions, Mapping)
                or set(permissions) != {"SKILL.md"}):
            return False
        expected_mode = int(str(permissions["SKILL.md"]), 8)
        if (expected_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWOTH
                            | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                or expected_mode & ~(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)):
            return False
        if destination is not None:
            root = Path(destination)
            skill = root / "SKILL.md"
            if (not root.is_dir() or root.is_symlink() or not skill.is_file() or skill.is_symlink()
                    or _digest(skill.read_bytes()) != per_file["SKILL.md"]
                    or stat.S_IMODE(skill.stat().st_mode) != expected_mode):
                return False
        return True
    except Exception:
        return False


def _result(*, attempted: bool = False, status: str = "BLOCKED", target: str = "",
            manifest: Mapping[str, Any] = {}, rollback: Mapping[str, Any] = {}, blocked: str = "",
            escalation: str = "") -> SkillInstallResult:
    return SkillInstallResult(attempted, status, target, manifest,
                              str(manifest.get("aggregate_digest", "")), rollback, blocked,
                              escalation, str(manifest.get("installation_evidence_digest", "")))


def _preflight(request: SkillInstallRequest) -> None:
    d, e, r, review, approval, plan = (request.decision, request.evaluation, request.resolution,
                                       request.review, request.approval, request.install_plan)
    if (d.adoption_state != CandidateAdoptionState.INSTALL_AUTHORIZED or not d.install_authorized
            or d.candidate_use_authorized or d.install_scope != "project"):
        raise ValueError("INSTALL_AUTHORIZED decision is required")
    if not verify_resolution_evidence(r.evidence) or r.provenance_state != "VERIFIED":
        raise ValueError("resolver provenance mismatch")
    if not verify_evaluation_evidence(e.evidence):
        raise ValueError("evaluation evidence mismatch")
    if not review.valid() or not approval.valid() or not plan.valid():
        raise ValueError("review, approval, or install plan digest mismatch")
    resolution_digest = str(r.evidence.get("evidence_digest", ""))
    evaluation_digest = str(e.evidence.get("evidence_digest", ""))
    expected = (
        d.candidate_id == r.evidence.get("candidate_id") == review.candidate_id == approval.candidate_id == plan.candidate_id,
        request.project_id == r.evidence.get("project_id") == approval.project_id == plan.target_project,
        request.gate_id == r.evidence.get("gate_id") == approval.gate_id == d.capability_requirement.gate_id,
        request.lv_id == r.evidence.get("lv_id") == approval.lv_id == d.capability_requirement.lv_id,
        request.canonical_plan_sha256 == approval.canonical_plan_sha256,
        evaluation_digest == review.evaluator_evidence_digest == approval.evaluation_digest,
        resolution_digest == review.resolver_evidence_digest,
        review.review_digest == approval.supply_chain_review_digest,
        d.evaluation_evidence_reference == e.evidence_reference,
        d.supply_chain_review_reference == "sha256:" + review.review_digest,
        d.install_plan_evidence_reference == "sha256:" + plan.plan_digest,
        d.approval_evidence_reference == approval.evidence_reference,
        plan.evaluation_evidence_reference == e.evidence_reference,
        plan.supply_chain_evidence_reference == "sha256:" + review.review_digest,
        plan.target_scope == approval.install_scope == review.install_scope == "project",
        plan.expected_revision == r.immutable_revision == review.immutable_revision,
        plan.expected_source == review.source,
        r.skill_md_digest == r.evidence.get("skill_md_digest") == review.skill_md_digest,
        tuple(plan.expected_files) == ("SKILL.md",),
        not plan.network_required and not plan.required_package_runtime,
        approval.status == "ACTIVE" and approval.intent == "project_skill_install",
    )
    if not all(expected):
        raise ValueError("installation authorization binding drift")
    if not r.skill_md_content or _digest(r.skill_md_content.encode("utf-8")) != r.skill_md_digest:
        raise ValueError("resolved SKILL.md content digest mismatch")
    mode = request.source_mode
    if (not isinstance(mode, int)
            or mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWOTH
                       | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        raise ValueError("unsafe source permission")
    if mode & ~(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH):
        raise ValueError("unsafe source permission")


def install_project_skill(request: SkillInstallRequest, *, hook: InstallHook | None = None) -> SkillInstallResult:
    target_text = request.install_plan.proposed_install_location
    attempted = False
    promoted = False
    stage: Path | None = None
    destination: Path | None = None
    try:
        project = Path(request.project_root)
        skill_root = Path(request.target_skill_root)
        # Home/shared/global-like scopes are escalations, even before ordinary path validation.
        if request.install_plan.target_scope != "project" or target_text.startswith(("~/", "/")):
            return _result(status="ESCALATION_REQUIRED", escalation="non-project or shared/global skill target")
        _preflight(request)
        relative = _safe_relative(target_text)
        if (not project.is_absolute() or not project.is_dir() or project.is_symlink()
                or project.resolve() != project or project.name != request.project_id):
            raise ValueError("target project identity is unverified")
        canonical = project / ".agents" / "skills"
        if skill_root != canonical or not skill_root.is_absolute() or not skill_root.is_dir():
            raise ValueError("INSTALL_TARGET_UNVERIFIED")
        if skill_root.is_symlink() or skill_root.resolve() != skill_root or _has_symlink(skill_root, project):
            raise ValueError("target skill root symlink is forbidden")
        if relative.parts[:2] != (".agents", "skills") or len(relative.parts) != 3:
            raise ValueError("install plan target is not canonical project-local skill path")
        name = relative.parts[2]
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("unsafe skill destination name")
        destination = skill_root / name
        if destination.parent != skill_root or _has_symlink(destination, project):
            raise ValueError("destination symlink escape")
        expected = request.resolution.skill_md_digest
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise ValueError("existing destination INVALID")
            entries = {item.name for item in destination.iterdir()}
            manifest_path = destination / MANIFEST_NAME
            skill_path = destination / "SKILL.md"
            if entries != {"SKILL.md", MANIFEST_NAME} or skill_path.is_symlink() or manifest_path.is_symlink():
                raise ValueError("existing destination INVALID")
            if _digest(skill_path.read_bytes()) != expected:
                raise ValueError("existing destination DIFFERENT; overwrite forbidden")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not verify_installed_manifest(manifest, destination):
                raise ValueError("existing destination INVALID")
            return _result(status="IDENTICAL", target=target_text, manifest=manifest)
        attempted = True
        stage = Path(tempfile.mkdtemp(prefix=".skill-install-", dir=skill_root))
        os.chmod(stage, 0o700)
        if hook: hook("before_stage_write", stage)
        skill_path = stage / "SKILL.md"
        fd = os.open(skill_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, request.source_mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(request.resolution.skill_md_content.encode("utf-8"))
            handle.flush(); os.fsync(handle.fileno())
        os.chmod(skill_path, request.source_mode)
        if hook: hook("after_stage_write", stage)
        staged_digest = _digest(skill_path.read_bytes())
        if staged_digest != expected:
            raise ValueError("resolved/staged digest mismatch")
        manifest = seal_installed_manifest(request, target_text, {"SKILL.md": staged_digest})
        manifest_path = stage / MANIFEST_NAME
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        os.chmod(manifest_path, 0o600)
        if not verify_installed_manifest(manifest, stage):
            raise ValueError("staged installed manifest verification failed")
        if hook: hook("before_promote", stage)
        os.replace(stage, destination)
        promoted = True; stage = None
        if hook: hook("after_promote", destination)
        installed_manifest = json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
        installed_digest = _digest((destination / "SKILL.md").read_bytes())
        if installed_digest != staged_digest or installed_digest != expected:
            raise ValueError("staged/installed digest mismatch")
        if installed_manifest.get("skill_md_digest") != expected or not verify_installed_manifest(installed_manifest, destination):
            raise ValueError("installed SKILL.md or manifest digest mismatch")
        return _result(attempted=True, status="INSTALL_COMPLETED", target=target_text, manifest=installed_manifest,
                       rollback={"attempted": False, "status": "NOT_REQUIRED"})
    except Exception as exc:
        rollback = {"attempted": bool(stage or promoted), "status": "NOT_REQUIRED"}
        if stage is not None or promoted:
            try:
                if hook: hook("before_rollback", destination if promoted and destination else stage)  # type: ignore[arg-type]
                if promoted and destination is not None:
                    shutil.rmtree(destination)
                if stage is not None:
                    shutil.rmtree(stage)
                rollback = {"attempted": True, "status": "COMPLETE"}
            except Exception as rollback_exc:
                rollback = {"attempted": True, "status": "FAILED", "reason": str(rollback_exc)}
                return _result(attempted=attempted, status="ESCALATION_REQUIRED", target=target_text,
                               rollback=rollback, blocked=str(exc), escalation="rollback failed")
        return _result(attempted=attempted, status="BLOCKED", target=target_text,
                       rollback=rollback, blocked=str(exc))
