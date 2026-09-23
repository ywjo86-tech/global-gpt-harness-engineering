"""Pure validation for activating already-approved Full Plan work."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .gate_orchestrator import GateOrchestrationError, load_requirement_evidence
from .project_onboarding import OnboardingRegistry, ProjectOnboardingError
from .runtime_release import RuntimeReleaseManifest

REQUEST_SCHEMA = "orchestration.approved-work-activation-request.v1"
_BINDING_SCHEMA = "orchestration.approved-work-binding.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_REQUEST_FIELDS = {
    "schema_version", "activation_request_id", "project_alias",
    "approved_plan_path", "approved_plan_sha256", "approved_spec_path",
    "approved_spec_sha256", "requirement_artifact_path",
    "requirement_artifact_sha256", "approval_ref", "expected_branch",
    "expected_head", "task_ids", "runtime_release_digest",
}


class ApprovedWorkBindingError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise ApprovedWorkBindingError(f"APPROVED_BINDING_REQUIRED: invalid {label}")
    return text


def _digest(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise ApprovedWorkBindingError(f"APPROVED_BINDING_REQUIRED: invalid {label}")
    return text


def _git(root: Path, *args: str, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=20,
    )
    if result.returncode != 0 and not allow_nonzero:
        raise ApprovedWorkBindingError("SOURCE_BINDING_MISMATCH: Git verification failed")
    return result


def _relative_committed_file(root: Path, raw: object, label: str) -> tuple[Path, str]:
    text = str(raw or "")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts or "\\" in text:
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: unsafe {label}")
    target = root / relative
    if target.is_symlink() or not target.is_file():
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: {label}")
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: {label}") from exc
    tracked = _git(root, "ls-files", "--error-unmatch", "--", relative.as_posix(), allow_nonzero=True)
    clean = _git(root, "diff", "--quiet", "HEAD", "--", relative.as_posix(), allow_nonzero=True)
    staged = _git(root, "diff", "--cached", "--quiet", "HEAD", "--", relative.as_posix(), allow_nonzero=True)
    if tracked.returncode != 0 or clean.returncode != 0 or staged.returncode != 0:
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: {label}")
    return resolved, relative.as_posix()


def _approved_task_ids(plan: Path) -> tuple[str, ...]:
    pattern = re.compile(r"^#{1,6}\s+Task\s+([A-Za-z0-9._:-]+)\s*:", re.MULTILINE)
    tasks = tuple(pattern.findall(plan.read_text(encoding="utf-8")))
    if not tasks or len(tasks) != len(set(tasks)):
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: approved task headings are invalid")
    return tasks


@dataclass(frozen=True, slots=True)
class ApprovedWorkActivationRequestV1:
    schema_version: str
    activation_request_id: str
    project_alias: str
    approved_plan_path: str
    approved_plan_sha256: str
    approved_spec_path: str
    approved_spec_sha256: str
    requirement_artifact_path: str
    requirement_artifact_sha256: str
    approval_ref: str
    expected_branch: str
    expected_head: str
    task_ids: tuple[str, ...]
    runtime_release_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != REQUEST_SCHEMA:
            raise ApprovedWorkBindingError("REQUEST_SCHEMA_MISMATCH")
        _safe_id(self.activation_request_id, "activation request ID")
        _safe_id(self.project_alias, "project alias")
        _digest(self.approved_plan_sha256, "approved plan digest")
        _digest(self.approved_spec_sha256, "approved spec digest")
        _digest(self.requirement_artifact_sha256, "requirement artifact digest")
        _digest(self.runtime_release_digest, "runtime release digest")
        if not str(self.approval_ref or "").strip() or any(ord(ch) < 32 for ch in self.approval_ref):
            raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: approval reference")
        _safe_id(self.expected_branch, "expected branch")
        if not _HEAD.fullmatch(str(self.expected_head or "")):
            raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: invalid expected HEAD")
        if not self.task_ids or len(self.task_ids) != len(set(self.task_ids)):
            raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: task IDs")
        for task_id in self.task_ids:
            _safe_id(task_id, "Task ID")
        for raw, label in (
            (self.approved_plan_path, "approved plan path"),
            (self.approved_spec_path, "approved spec path"),
            (self.requirement_artifact_path, "requirement artifact path"),
        ):
            path = Path(str(raw or ""))
            if not str(raw or "") or path.is_absolute() or ".." in path.parts or "\\" in str(raw):
                raise ApprovedWorkBindingError(f"APPROVED_BINDING_REQUIRED: unsafe {label}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ApprovedWorkActivationRequestV1":
        if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
            raise ApprovedWorkBindingError("REQUEST_FIELDS_MISMATCH")
        tasks = value.get("task_ids")
        if not isinstance(tasks, list) or not all(isinstance(item, str) for item in tasks):
            raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: task IDs")
        return cls(
            schema_version=str(value["schema_version"]), activation_request_id=str(value["activation_request_id"]),
            project_alias=str(value["project_alias"]), approved_plan_path=str(value["approved_plan_path"]),
            approved_plan_sha256=str(value["approved_plan_sha256"]), approved_spec_path=str(value["approved_spec_path"]),
            approved_spec_sha256=str(value["approved_spec_sha256"]),
            requirement_artifact_path=str(value["requirement_artifact_path"]),
            requirement_artifact_sha256=str(value["requirement_artifact_sha256"]),
            approval_ref=str(value["approval_ref"]), expected_branch=str(value["expected_branch"]),
            expected_head=str(value["expected_head"]), task_ids=tuple(tasks),
            runtime_release_digest=str(value["runtime_release_digest"]),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_ids"] = list(self.task_ids)
        return value

    @property
    def request_digest(self) -> str:
        return _sha(self.to_dict())


@dataclass(frozen=True, slots=True)
class ApprovedWorkBindingV1:
    schema_version: str
    activation_request_id: str
    request_digest: str
    project_alias: str
    project_id: str
    project_root: str
    approved_plan_path: str
    approved_plan_sha256: str
    approved_spec_path: str
    approved_spec_sha256: str
    requirement_artifact_path: str
    requirement_artifact_sha256: str
    approval_ref: str
    expected_branch: str
    expected_head: str
    task_ids: tuple[str, ...]
    runtime_release_digest: str
    runtime_code_root: str

    def __post_init__(self) -> None:
        if self.schema_version != _BINDING_SCHEMA:
            raise ApprovedWorkBindingError("approved work binding schema mismatch")
        for value, label in (
            (self.activation_request_id, "activation request ID"),
            (self.project_alias, "project alias"), (self.project_id, "project ID"),
        ):
            _safe_id(value, label)
        for value, label in (
            (self.request_digest, "request digest"),
            (self.approved_plan_sha256, "approved plan digest"),
            (self.approved_spec_sha256, "approved spec digest"),
            (self.requirement_artifact_sha256, "requirement artifact digest"),
            (self.runtime_release_digest, "runtime release digest"),
        ):
            _digest(value, label)
        if not _HEAD.fullmatch(self.expected_head):
            raise ApprovedWorkBindingError("invalid expected HEAD")
        if not self.task_ids or len(self.task_ids) != len(set(self.task_ids)):
            raise ApprovedWorkBindingError("invalid bound task IDs")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_ids"] = list(self.task_ids)
        return value

    @property
    def binding_digest(self) -> str:
        return _sha(self.to_dict())


def _resolve_registered_project(registry: OnboardingRegistry, alias: str) -> tuple[dict[str, Any], Path]:
    try:
        entries = registry.entries()
    except ProjectOnboardingError as exc:
        if "canonical plan SHA drift" in str(exc):
            raise ApprovedWorkBindingError("COMMITTED_EVIDENCE_REQUIRED: approved plan") from exc
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: registry invalid") from exc
    entry = next((item for item in entries if item.get("alias") == alias), None)
    if entry is None:
        raise ApprovedWorkBindingError("PROJECT_NOT_REGISTERED")
    try:
        root = Path(str(entry["project_root"]))
        report = registry.inspect(root, alias)
    except (KeyError, OSError, ValueError, ProjectOnboardingError) as exc:
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: project binding invalid") from exc
    if report.get("status") != "COMPATIBLE" or report.get("entry") != entry:
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: project binding invalid")
    try:
        canonical = root.resolve(strict=True)
    except OSError as exc:
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: project root unavailable") from exc
    if canonical != root or root.is_symlink():
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: project root unsafe")
    return entry, canonical


def validate_approved_work_binding(
    request: ApprovedWorkActivationRequestV1 | Mapping[str, Any], *,
    registry: OnboardingRegistry, runtime_release: RuntimeReleaseManifest,
) -> ApprovedWorkBindingV1:
    req = request if isinstance(request, ApprovedWorkActivationRequestV1) else ApprovedWorkActivationRequestV1.from_mapping(request)
    entry, root = _resolve_registered_project(registry, req.project_alias)
    if str(entry.get("canonical_plan") or "") != req.approved_plan_path:
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: approved plan is not canonical")

    branch = _git(root, "branch", "--show-current").stdout.strip()
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    if branch != req.expected_branch or head != req.expected_head:
        raise ApprovedWorkBindingError("SOURCE_BINDING_MISMATCH")

    plan, plan_relative = _relative_committed_file(root, req.approved_plan_path, "approved plan")
    spec, spec_relative = _relative_committed_file(root, req.approved_spec_path, "approved spec")
    try:
        requirement, requirement_relative = _relative_committed_file(
            root, req.requirement_artifact_path, "requirement artifact",
        )
    except ApprovedWorkBindingError as exc:
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: requirement artifact") from exc
    plan_sha = _file_sha(plan)
    spec_sha = _file_sha(spec)
    requirement_sha = _file_sha(requirement)
    if plan_sha != req.approved_plan_sha256 or spec_sha != req.approved_spec_sha256:
        raise ApprovedWorkBindingError("EVIDENCE_DIGEST_MISMATCH")
    if requirement_sha != req.requirement_artifact_sha256:
        raise ApprovedWorkBindingError("EVIDENCE_DIGEST_MISMATCH")

    try:
        load_requirement_evidence(requirement, requirements_sha256=plan_sha)
    except (GateOrchestrationError, OSError, ValueError) as exc:
        raise ApprovedWorkBindingError("APPROVED_BINDING_REQUIRED: requirement artifact invalid") from exc

    approved_tasks = set(_approved_task_ids(plan))
    if any(task_id not in approved_tasks for task_id in req.task_ids):
        raise ApprovedWorkBindingError("TASK_NOT_APPROVED")

    if req.runtime_release_digest != str(runtime_release.manifest_sha256 or ""):
        raise ApprovedWorkBindingError("RUNTIME_RELEASE_MISMATCH")
    runtime_root = Path(str(runtime_release.release_path or "")).expanduser().absolute()
    try:
        runtime_canonical = runtime_root.resolve(strict=True)
    except OSError as exc:
        raise ApprovedWorkBindingError("RUNTIME_RELEASE_MISMATCH") from exc
    if runtime_root.is_symlink() or not runtime_root.is_dir() or runtime_canonical != runtime_root:
        raise ApprovedWorkBindingError("RUNTIME_RELEASE_MISMATCH")

    return ApprovedWorkBindingV1(
        schema_version=_BINDING_SCHEMA,
        activation_request_id=req.activation_request_id,
        request_digest=req.request_digest,
        project_alias=req.project_alias,
        project_id=str(entry["project_id"]),
        project_root=str(root),
        approved_plan_path=plan_relative,
        approved_plan_sha256=plan_sha,
        approved_spec_path=spec_relative,
        approved_spec_sha256=spec_sha,
        requirement_artifact_path=requirement_relative,
        requirement_artifact_sha256=requirement_sha,
        approval_ref=req.approval_ref,
        expected_branch=branch,
        expected_head=head,
        task_ids=req.task_ids,
        runtime_release_digest=req.runtime_release_digest,
        runtime_code_root=str(runtime_root),
    )
