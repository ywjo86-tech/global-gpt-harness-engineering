from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass, field
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
CONCURRENCY_EVIDENCE_CONTRACT = "orchestration.project-skill-install-concurrency.v1"
MANIFEST_NAME = ".codex-install-manifest.json"
LOCK_ROOT_NAME = ".skill-install-locks"
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
    concurrency_evidence: Mapping[str, Any] = field(default_factory=dict)
    concurrency_evidence_digest: str = ""


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
        "concurrency_guard_mode": "project-local-flock+mkdir-claim",
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


def _seal_concurrency_evidence(*, request: SkillInstallRequest, lock_id: str,
                               before: str, after: str, outcome: str,
                               idempotent: bool, collision: bool) -> dict[str, Any]:
    value = {
        "schema_version": CONCURRENCY_EVIDENCE_CONTRACT,
        "project_id": request.project_id,
        "candidate_id": request.decision.candidate_id,
        "target_skill_root_digest": _digest(str(Path(request.target_skill_root)).encode()),
        "destination_digest": _digest(request.install_plan.proposed_install_location.encode()),
        "install_plan_digest": request.install_plan.plan_digest,
        "lock_claim_identifier_digest": lock_id,
        "concurrency_guard_mode": "project-local-flock+mkdir-claim",
        "destination_state_before": before,
        "destination_state_after": after,
        "promotion_outcome": outcome,
        "idempotent": idempotent,
        "concurrent_collision": collision,
        "candidate_use_authorized": False,
        "used_assets_changed": False,
        "gate_passed": False,
    }
    value["evidence_digest"] = _digest(canonical_json_bytes(value))
    return value


def verify_concurrency_evidence(evidence: Mapping[str, Any]) -> bool:
    try:
        unsigned = dict(evidence)
        digest = unsigned.pop("evidence_digest")
        return bool(
            unsigned.get("schema_version") == CONCURRENCY_EVIDENCE_CONTRACT
            and unsigned.get("concurrency_guard_mode") == "project-local-flock+mkdir-claim"
            and unsigned.get("candidate_use_authorized") is False
            and unsigned.get("used_assets_changed") is False
            and unsigned.get("gate_passed") is False
            and _SHA256.fullmatch(str(digest))
            and digest == _digest(canonical_json_bytes(unsigned))
        )
    except Exception:
        return False


def _result(*, attempted: bool = False, status: str = "BLOCKED", target: str = "",
            manifest: Mapping[str, Any] = {}, rollback: Mapping[str, Any] = {}, blocked: str = "",
            escalation: str = "", concurrency: Mapping[str, Any] = {}) -> SkillInstallResult:
    return SkillInstallResult(attempted, status, target, manifest,
                              str(manifest.get("aggregate_digest", "")), rollback, blocked,
                              escalation, str(manifest.get("installation_evidence_digest", "")),
                              False, False, False, concurrency,
                              str(concurrency.get("evidence_digest", "")))


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


def _destination_state(destination: Path, expected: str) -> tuple[str, Mapping[str, Any]]:
    if not destination.exists() and not destination.is_symlink():
        return "ABSENT", {}
    if destination.is_symlink() or not destination.is_dir():
        return "INVALID", {}
    try:
        entries = {item.name for item in destination.iterdir()}
        manifest_path = destination / MANIFEST_NAME
        skill_path = destination / "SKILL.md"
        if (entries != {"SKILL.md", MANIFEST_NAME} or skill_path.is_symlink()
                or manifest_path.is_symlink() or not skill_path.is_file()
                or not manifest_path.is_file()):
            return "INVALID", {}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (_digest(skill_path.read_bytes()) == expected
                and verify_installed_manifest(manifest, destination)):
            return "IDENTICAL", manifest
        return "DIFFERENT", manifest
    except Exception:
        return "INVALID", {}


def _lock_identifier(project: Path, skill_root: Path, destination: Path) -> str:
    return _digest(canonical_json_bytes({
        "project_identity": _digest(str(project).encode()),
        "target_skill_root": _digest(str(skill_root).encode()),
        "destination": destination.name,
    }))


def _acquire_lock(project: Path, skill_root: Path, destination: Path,
                  request: SkillInstallRequest, hook: InstallHook | None) -> tuple[int, str, bool]:
    lock_root = skill_root / LOCK_ROOT_NAME
    try:
        os.mkdir(lock_root, 0o700)
    except FileExistsError:
        pass
    if (lock_root.is_symlink() or not lock_root.is_dir() or lock_root.parent != skill_root
            or _has_symlink(lock_root, project)):
        raise ValueError("installer lock root is unsafe")
    lock_id = _lock_identifier(project, skill_root, destination)
    if not _SHA256.fullmatch(lock_id):
        raise ValueError("installer lock identifier is unsafe")
    lock_path = lock_root / (lock_id + ".lock")
    if lock_path.parent != lock_root:
        raise ValueError("installer lock path traversal")
    if hook:
        hook("before_lock_acquire", lock_path)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("installer lock file is unsafe")
        collision = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            collision = True
            fcntl.flock(fd, fcntl.LOCK_EX)
        metadata = canonical_json_bytes({
            "lock_claim_identifier_digest": lock_id,
            "project_id": request.project_id,
            "candidate_id": request.decision.candidate_id,
            "destination_digest": _digest(request.install_plan.proposed_install_location.encode()),
            "install_plan_digest": request.install_plan.plan_digest,
        })
        os.ftruncate(fd, 0)
        os.write(fd, metadata)
        os.fsync(fd)
        if hook:
            hook("after_lock_acquire", lock_path)
        return fd, lock_id, collision
    except Exception:
        os.close(fd)
        raise


def _release_lock(fd: int) -> None:
    error: Exception | None = None
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception as exc:
        error = exc
    try:
        os.close(fd)
    except Exception as exc:
        error = error or exc
    if error:
        raise error


def _owned_destination(destination: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None or destination.is_symlink():
        return False
    try:
        current = destination.stat(follow_symlinks=False)
        return stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == identity
    except FileNotFoundError:
        return False


def install_project_skill(request: SkillInstallRequest, *, hook: InstallHook | None = None) -> SkillInstallResult:
    target_text = request.install_plan.proposed_install_location
    attempted = False
    claimed = False
    stage: Path | None = None
    destination: Path | None = None
    destination_identity: tuple[int, int] | None = None
    lock_fd: int | None = None
    lock_id = ""
    collision = False
    before_state = "UNVERIFIED"
    outcome = "NOT_ATTEMPTED"
    result: SkillInstallResult | None = None
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
        before_state, _ = _destination_state(destination, expected)
        lock_fd, lock_id, collision = _acquire_lock(project, skill_root, destination, request, hook)
        # Authorization and destination state are both revalidated after serialization.
        _preflight(request)
        locked_state, existing_manifest = _destination_state(destination, expected)
        if locked_state == "IDENTICAL":
            outcome = "IDEMPOTENT_NOOP"
            concurrency = _seal_concurrency_evidence(request=request, lock_id=lock_id,
                before=before_state, after=locked_state, outcome=outcome,
                idempotent=True, collision=collision)
            result = _result(status="IDENTICAL", target=target_text, manifest=existing_manifest,
                             concurrency=concurrency)
            return result
        if locked_state != "ABSENT":
            raise ValueError(f"existing destination {locked_state}; overwrite forbidden")
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
        staged_state, _ = _destination_state(destination, expected)
        if staged_state != "ABSENT":
            if staged_state == "IDENTICAL":
                outcome = "IDEMPOTENT_NOOP"
                concurrency = _seal_concurrency_evidence(request=request, lock_id=lock_id,
                    before=before_state, after=staged_state, outcome=outcome,
                    idempotent=True, collision=collision)
                shutil.rmtree(stage); stage = None
                result = _result(attempted=True, status="IDENTICAL", target=target_text,
                    manifest=_destination_state(destination, expected)[1],
                    rollback={"attempted": True, "status": "COMPLETE"}, concurrency=concurrency)
                return result
            raise ValueError(f"destination changed during staging: {staged_state}")
        if hook: hook("before_promote", stage)
        promote_state, promote_manifest = _destination_state(destination, expected)
        if promote_state == "IDENTICAL":
            outcome = "IDEMPOTENT_NOOP"
            concurrency = _seal_concurrency_evidence(request=request, lock_id=lock_id,
                before=before_state, after=promote_state, outcome=outcome,
                idempotent=True, collision=collision)
            shutil.rmtree(stage); stage = None
            result = _result(attempted=True, status="IDENTICAL", target=target_text,
                manifest=promote_manifest, rollback={"attempted": True, "status": "COMPLETE"},
                concurrency=concurrency)
            return result
        if promote_state != "ABSENT":
            raise ValueError(f"destination changed before promotion: {promote_state}")
        os.mkdir(destination, 0o700)
        claimed = True
        claimed_stat = destination.stat(follow_symlinks=False)
        destination_identity = (claimed_stat.st_dev, claimed_stat.st_ino)
        if hook: hook("after_destination_claim", destination)
        if not _owned_destination(destination, destination_identity):
            raise ValueError("destination claim ownership changed")
        os.link(stage / "SKILL.md", destination / "SKILL.md", follow_symlinks=False)
        (stage / "SKILL.md").unlink()
        if not _owned_destination(destination, destination_identity):
            raise ValueError("destination claim ownership changed")
        # Manifest is promoted last; until then the destination is never a valid install.
        os.link(stage / MANIFEST_NAME, destination / MANIFEST_NAME, follow_symlinks=False)
        (stage / MANIFEST_NAME).unlink()
        stage.rmdir(); stage = None
        if hook: hook("after_promote", destination)
        if not _owned_destination(destination, destination_identity):
            raise ValueError("destination ownership changed after promotion")
        installed_manifest = json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
        installed_digest = _digest((destination / "SKILL.md").read_bytes())
        if installed_digest != staged_digest or installed_digest != expected:
            raise ValueError("staged/installed digest mismatch")
        if installed_manifest.get("skill_md_digest") != expected or not verify_installed_manifest(installed_manifest, destination):
            raise ValueError("installed SKILL.md or manifest digest mismatch")
        outcome = "PROMOTED"
        concurrency = _seal_concurrency_evidence(request=request, lock_id=lock_id,
            before=before_state, after="IDENTICAL", outcome=outcome,
            idempotent=False, collision=collision)
        result = _result(attempted=True, status="INSTALL_COMPLETED", target=target_text,
            manifest=installed_manifest, rollback={"attempted": False, "status": "NOT_REQUIRED"},
            concurrency=concurrency)
        return result
    except Exception as exc:
        rollback = {"attempted": bool(stage or claimed), "status": "NOT_REQUIRED"}
        if stage is not None or claimed:
            try:
                if hook: hook("before_rollback", destination if claimed and destination else stage)  # type: ignore[arg-type]
                if claimed and destination is not None and _owned_destination(destination, destination_identity):
                    shutil.rmtree(destination)
                if stage is not None:
                    shutil.rmtree(stage)
                rollback = {"attempted": True, "status": "COMPLETE"}
            except Exception as rollback_exc:
                rollback = {"attempted": True, "status": "FAILED", "reason": str(rollback_exc)}
                result = _result(attempted=attempted, status="ESCALATION_REQUIRED", target=target_text,
                                 rollback=rollback, blocked=str(exc), escalation="rollback failed")
                return result
        concurrency: Mapping[str, Any] = {}
        if lock_id and destination is not None:
            after_state, _ = _destination_state(destination, request.resolution.skill_md_digest)
            concurrency = _seal_concurrency_evidence(request=request, lock_id=lock_id,
                before=before_state, after=after_state, outcome="BLOCKED",
                idempotent=False, collision=collision)
        result = _result(attempted=attempted, status="BLOCKED", target=target_text,
                         rollback=rollback, blocked=str(exc), concurrency=concurrency)
        return result
    finally:
        if lock_fd is not None:
            try:
                if hook: hook("before_lock_release", destination or Path(request.target_skill_root))
                _release_lock(lock_fd)
            except Exception as exc:
                # A caller must never treat success as durable when guard release is uncertain.
                result = _result(attempted=attempted, status="ESCALATION_REQUIRED", target=target_text,
                    manifest=result.installed_file_manifest if result else {},
                    rollback={"attempted": False, "status": "FAILED", "reason": str(exc)},
                    blocked="installer lock cleanup failed", escalation="lock cleanup failed",
                    concurrency=result.concurrency_evidence if result else {})
                return result
