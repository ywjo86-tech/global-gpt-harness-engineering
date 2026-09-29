"""Bounded, create-once Gate approval evidence issuance.

The issuer accepts a separately approved exact preflight digest.  It cannot
change a project, Gate plan, or an existing approval file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contract_adapter import load_project_mapping, sha256_file, validate_mapping_sources
from .approved_full_plan_activation_contract import GateBindingRefV1
from .approved_full_plan_binding import _validate_gate_requirement_artifacts
from .gate_approval import seal_approval_evidence, validate_approval_evidence
from .gate_orchestrator import load_gate_plan, namespace_root
from .project_onboarding import OnboardingRegistry

SCHEMA = "orchestration.gate-approval-issuance-request.v1"
_FIELDS = {
    "schema_version", "request_id", "project_alias", "gate_id", "expected_branch",
    "expected_head", "requirements_sha256", "approval_id", "approval_ref",
    "issued_at", "expires_at", "mode", "preflight_digest", "owner_approval_comment_id",
    "engine_requirement_evidence", "project_requirement_evidence_by_lv",
}
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class GateApprovalIssuanceError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE.fullmatch(text) or ".." in text:
        raise GateApprovalIssuanceError(f"{label.upper()}_INVALID")
    return text


def _utc(value: object) -> datetime:
    text = str(value or "")
    if not text.endswith("Z"):
        raise GateApprovalIssuanceError("APPROVAL_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise GateApprovalIssuanceError("APPROVAL_TIME_INVALID") from exc
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class GateApprovalIssuanceRequest:
    schema_version: str
    request_id: str
    project_alias: str
    gate_id: str
    expected_branch: str
    expected_head: str
    requirements_sha256: str
    approval_id: str
    approval_ref: str
    issued_at: str
    expires_at: str
    mode: str
    preflight_digest: str | None
    owner_approval_comment_id: int | None
    engine_requirement_evidence: Mapping[str, str] | None
    project_requirement_evidence_by_lv: list[Mapping[str, str]]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "GateApprovalIssuanceRequest":
        if not isinstance(raw, Mapping) or set(raw) != _FIELDS or raw.get("schema_version") != SCHEMA:
            raise GateApprovalIssuanceError("REQUEST_FIELDS_MISMATCH")
        for key in ("request_id", "project_alias", "gate_id", "approval_id", "approval_ref"):
            _safe(raw[key], key)
        branch = str(raw["expected_branch"] or "")
        if not branch or branch == "HEAD" or ".." in branch or branch.startswith("-") or any(
            c in branch for c in " ~^:?*[\\"
        ):
            raise GateApprovalIssuanceError("EXPECTED_BRANCH_INVALID")
        if not _HEAD.fullmatch(str(raw["expected_head"] or "")):
            raise GateApprovalIssuanceError("EXPECTED_HEAD_INVALID")
        if not _SHA.fullmatch(str(raw["requirements_sha256"] or "")):
            raise GateApprovalIssuanceError("REQUIREMENTS_DIGEST_INVALID")
        issued, expires = _utc(raw["issued_at"]), _utc(raw["expires_at"])
        if expires <= issued or (expires - issued).total_seconds() > 86400:
            raise GateApprovalIssuanceError("APPROVAL_WINDOW_INVALID")
        mode = str(raw["mode"] or "")
        digest = raw["preflight_digest"]
        comment_id = raw["owner_approval_comment_id"]
        if mode == "DRY_RUN" and (digest is not None or comment_id is not None):
            raise GateApprovalIssuanceError("DRY_RUN_PREFLIGHT_DIGEST_FORBIDDEN")
        if mode == "ISSUE" and not _SHA.fullmatch(str(digest or "")):
            raise GateApprovalIssuanceError("PREFLIGHT_DIGEST_REQUIRED")
        if mode == "ISSUE" and (type(comment_id) is not int or comment_id <= 0):
            raise GateApprovalIssuanceError("OWNER_APPROVAL_COMMENT_REQUIRED")
        if mode not in {"DRY_RUN", "ISSUE"}:
            raise GateApprovalIssuanceError("MODE_INVALID")
        try:
            GateBindingRefV1.from_mapping({
                "gate_id": raw["gate_id"],
                "approval_evidence": {"path": "approval-placeholder.json", "sha256": "0" * 64},
                "engine_requirement_evidence": raw["engine_requirement_evidence"],
                "project_requirement_evidence_by_lv": raw["project_requirement_evidence_by_lv"],
            })
        except ValueError as exc:
            raise GateApprovalIssuanceError("REQUIREMENT_REFERENCES_INVALID") from exc
        return cls(**{key: raw[key] for key in _FIELDS})

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in sorted(_FIELDS)}

    @property
    def request_digest(self) -> str:
        return _sha(self.to_dict())


class GateApprovalIssuer:
    def __init__(self, *, registry_root: str | Path, mapping_root: str | Path,
                 harness_state_root: str | Path) -> None:
        self.registry = OnboardingRegistry(Path(registry_root).resolve() / "aliases")
        self.mapping_root = Path(mapping_root).resolve()
        self.state_root = Path(harness_state_root).resolve()
        if any(not path.is_dir() or path.is_symlink() for path in
               (self.registry.root, self.mapping_root, self.state_root)):
            raise GateApprovalIssuanceError("AUTHORITY_ROOT_INVALID")

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(root), *args],
                                capture_output=True, text=True, check=False, timeout=20)
        if result.returncode:
            raise GateApprovalIssuanceError("SOURCE_BINDING_MISMATCH")
        return result.stdout.strip()

    def _preflight(self, request: GateApprovalIssuanceRequest) -> tuple[dict[str, Any], str]:
        entries = self.registry.entries()
        entry = next((item for item in entries if item.get("alias") == request.project_alias), None)
        if entry is None:
            raise GateApprovalIssuanceError("PROJECT_NOT_REGISTERED")
        root = Path(str(entry["project_root"])).resolve(strict=True)
        if self.registry.inspect(root, request.project_alias).get("status") != "COMPATIBLE":
            raise GateApprovalIssuanceError("PROJECT_BINDING_INVALID")
        if (self._git(root, "branch", "--show-current") != request.expected_branch
                or self._git(root, "rev-parse", "HEAD") != request.expected_head
                or self._git(root, "status", "--porcelain")):
            raise GateApprovalIssuanceError("SOURCE_BINDING_MISMATCH")
        mapping = load_project_mapping(root, mapping_root=self.mapping_root)
        if mapping is None or validate_mapping_sources(mapping):
            raise GateApprovalIssuanceError("MAPPING_INVALID")
        plan = load_gate_plan(root, request.gate_id, mapping_root=self.mapping_root)
        if (plan.project_id != entry["project_id"]
                or plan.canonical_plan_sha256 != mapping.canonical_sha256
                or sha256_file(mapping.canonical_source) != mapping.canonical_sha256):
            raise GateApprovalIssuanceError("PLAN_BINDING_MISMATCH")
        now = datetime.now(timezone.utc)
        if not (_utc(request.issued_at) <= now < _utc(request.expires_at)):
            raise GateApprovalIssuanceError("APPROVAL_WINDOW_EXPIRED")
        payload = {
            "schema_version": "orchestration.gate-approval.v1",
            "approval_id": request.approval_id, "project_id": plan.project_id,
            "gate_id": request.gate_id, "requirements_sha256": request.requirements_sha256,
            "plan_sha256": plan.canonical_plan_sha256,
            "branch": request.expected_branch, "head": request.expected_head,
            "scope": {
                "lv_order": [lv.lv_id for lv in plan.lvs],
                "owned_files_by_lv": {lv.lv_id: list(lv.owned_files) for lv in plan.lvs},
            },
            "issued_at": request.issued_at, "expires_at": request.expires_at, "status": "ACTIVE",
        }
        sealed = seal_approval_evidence(payload)
        validate_approval_evidence(
            sealed, project_id=plan.project_id, gate_id=request.gate_id,
            requirements_sha256=request.requirements_sha256,
            plan_sha256=plan.canonical_plan_sha256, branch=request.expected_branch,
            head=request.expected_head, lv_order=payload["scope"]["lv_order"],
            owned_files_by_lv=payload["scope"]["owned_files_by_lv"],
        )
        gate_ref = GateBindingRefV1.from_mapping({
            "gate_id": request.gate_id,
            "approval_evidence": {"path": f"{request.request_id}.json", "sha256": _sha(sealed)},
            "engine_requirement_evidence": request.engine_requirement_evidence,
            "project_requirement_evidence_by_lv": request.project_requirement_evidence_by_lv,
        })
        _validate_gate_requirement_artifacts(
            project_root=root, harness_state_root=self.state_root,
            project_id=plan.project_id, plan=plan, gate_ref=gate_ref,
            approval_path=Path(f"{request.request_id}.json"), approval_sha256=_sha(sealed),
            requirements_sha256=request.requirements_sha256,
            project_requirements_required=mapping.task_lv_projection_path is not None,
        )
        binding = {
            "project_alias": request.project_alias, "project_root": str(root),
            "mapping_root": str(self.mapping_root), "source_head": request.expected_head,
            "approval_ref": request.approval_ref, "evidence": sealed,
        }
        return binding, _sha(binding)

    @staticmethod
    def _verify_owner_comment(request: GateApprovalIssuanceRequest, digest: str,
                              comment: Mapping[str, Any], owner_actor_id: str) -> None:
        expected = "OCP_GATE_OWNER_APPROVAL_V1\n" + _canonical({
            "approval_ref": request.approval_ref,
            "preflight_digest": digest,
            "request_id": request.request_id,
        }).decode("utf-8")
        actor = comment.get("user")
        if (comment.get("id") != request.owner_approval_comment_id
                or not isinstance(actor, Mapping)
                or str(actor.get("id")) != owner_actor_id
                or comment.get("performed_via_github_app") is not None
                or comment.get("created_at") != comment.get("updated_at")
                or comment.get("body") != expected):
            raise GateApprovalIssuanceError("EXACT_OWNER_APPROVAL_REQUIRED")

    def execute(self, request: GateApprovalIssuanceRequest, *,
                owner_approval_comment: Mapping[str, Any] | None = None,
                owner_actor_id: str = "") -> dict[str, Any]:
        binding, digest = self._preflight(request)
        if request.mode == "DRY_RUN":
            return {"status": "PREFLIGHT_READY", "mutation_performed": False,
                    "preflight_digest": digest, "approval_payload_sha256": _sha(binding["evidence"])}
        if request.preflight_digest != digest or owner_approval_comment is None:
            raise GateApprovalIssuanceError("EXACT_OWNER_APPROVAL_REQUIRED")
        self._verify_owner_comment(request, digest, owner_approval_comment, owner_actor_id)
        project_id = binding["evidence"]["payload"]["project_id"]
        target_root = namespace_root(self.state_root, project_id, "approval")
        cursor = self.state_root
        for part in target_root.relative_to(self.state_root).parts:
            cursor = cursor / part
            if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
                raise GateApprovalIssuanceError("APPROVAL_NAMESPACE_INVALID")
            cursor.mkdir(exist_ok=True, mode=0o700)
            if cursor.is_symlink() or not cursor.is_dir():
                raise GateApprovalIssuanceError("APPROVAL_NAMESPACE_INVALID")
        relative = f"{request.request_id}.json"
        target = target_root / relative
        encoded = _canonical(binding["evidence"])
        if target.exists() or target.is_symlink():
            if target.is_symlink() or target.read_bytes() != encoded:
                raise GateApprovalIssuanceError("APPROVAL_REPLAY_CONFLICT")
            status = "ALREADY_ISSUED"
        else:
            fd, temporary = tempfile.mkstemp(prefix=".gate-approval-", dir=target_root)
            try:
                with os.fdopen(fd, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, target, follow_symlinks=False)
                except FileExistsError:
                    if target.is_symlink() or target.read_bytes() != encoded:
                        raise GateApprovalIssuanceError("APPROVAL_REPLAY_CONFLICT")
                    status = "ALREADY_ISSUED"
                else:
                    status = "ISSUED"
                dir_fd = os.open(target_root, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                os.unlink(temporary)
        return {"status": status, "mutation_performed": status == "ISSUED",
                "approval_evidence": {"path": relative, "sha256": hashlib.sha256(encoded).hexdigest()},
                "preflight_digest": digest}
