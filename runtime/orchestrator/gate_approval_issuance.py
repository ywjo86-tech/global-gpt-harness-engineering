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
from .project_onboarding import OnboardingRegistry, ProjectOnboardingError, validate_alias_entry
from .recovery_contract import (
    RecoveryError, canonical_recovery_binding, prepare_pre_result_partial_recovery,
)

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


def _canonicalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


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

    def _registered_alias(self, alias: str) -> dict[str, Any]:
        # An unrelated registration may drift independently. Validate the exact
        # requested alias rather than enumerating every registered project.
        target = self.registry.root / f"{alias}.json"
        if target.is_symlink() or not target.is_file():
            raise GateApprovalIssuanceError("PROJECT_NOT_REGISTERED")
        try:
            entry = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(entry, dict) or entry.get("alias") != alias:
                raise GateApprovalIssuanceError("PROJECT_BINDING_INVALID")
            validate_alias_entry(entry)
        except (OSError, UnicodeError, json.JSONDecodeError, ProjectOnboardingError) as exc:
            raise GateApprovalIssuanceError("PROJECT_BINDING_INVALID") from exc
        return entry

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(root), *args],
                                capture_output=True, text=True, check=False, timeout=20)
        if result.returncode:
            raise GateApprovalIssuanceError("SOURCE_BINDING_MISMATCH")
        return result.stdout.rstrip()

    def _safe_state_file(self, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        target = (self.state_root / candidate).resolve()
        if self.state_root not in target.parents or target.is_symlink() or not target.is_file():
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        return target

    @staticmethod
    def _status_paths(status_text: str) -> list[str]:
        paths: list[str] = []
        for line in status_text.splitlines():
            if len(line) < 4 or line[2] != " ":
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_STATUS_INVALID")
            relative = line[3:]
            if (
                not relative
                or " -> " in relative
                or relative.startswith('"')
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
            ):
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_STATUS_INVALID")
            paths.append(relative)
        if len(paths) != len(set(paths)):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_STATUS_INVALID")
        return sorted(paths)

    def _verified_recovery_renewal(
        self, request: GateApprovalIssuanceRequest, *,
        project_root: Path, project_id: str, plan_sha256: str,
        actual_branch: str, actual_head: str, status_text: str,
    ) -> dict[str, Any]:
        if actual_branch != request.expected_branch:
            raise GateApprovalIssuanceError("SOURCE_BINDING_MISMATCH")
        changed = self._status_paths(status_text)
        if not changed:
            raise GateApprovalIssuanceError("SOURCE_BINDING_MISMATCH")

        recovery_root = (
            self.state_root / "_workspace" / "global-gate" / project_id / "recovery"
        )
        if recovery_root.is_symlink() or not recovery_root.is_dir():
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")

        candidates: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(recovery_root.glob("*.json")):
            if path.name.endswith(".checkpoint.json"):
                continue
            if path.is_symlink() or not path.is_file():
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID") from exc
            if not isinstance(raw, dict):
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
            if raw.get("schema_version") != "orchestration.production-recovery.v1":
                continue
            if (
                raw.get("source_binding_kind") == "PRE_RESULT_PARTIAL_SOURCE"
                and raw.get("project_id") == project_id
                and raw.get("gate_id") == request.gate_id
                and raw.get("plan_sha256") == plan_sha256
                and raw.get("branch") == request.expected_branch
                and raw.get("baseline_head") == request.expected_head
                and raw.get("current_head") == actual_head
                and raw.get("rejection_reason_code") == "REJECTED_PRE_RESULT_PARTIAL"
                and raw.get("missing_bindings") == ["worker.result"]
                and raw.get("hard_stop") is True
            ):
                candidates.append((path, raw))
        if len(candidates) != 1:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_AMBIGUOUS")

        record_path, record = candidates[0]
        record_hash = record.get("record_hash")
        if (
            not isinstance(record_hash, str)
            or not _SHA.fullmatch(record_hash)
            or record_hash != _sha({k: v for k, v in record.items() if k != "record_hash"})
        ):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")

        recovery_id = record.get("recovery_id")
        if not isinstance(recovery_id, str) or not recovery_id:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        checkpoint_path = recovery_root / f"{recovery_id}.checkpoint.json"
        if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID") from exc
        if not isinstance(checkpoint, dict):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        checkpoint_sha = checkpoint.get("checkpoint_sha256")
        if (
            not isinstance(checkpoint_sha, str)
            or not _SHA.fullmatch(checkpoint_sha)
            or checkpoint_sha != _sha({
                k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"
            })
            or checkpoint.get("status") != "REJECTED_PRE_RESULT_PARTIAL"
            or checkpoint.get("source_binding_kind") != "PRE_RESULT_PARTIAL_SOURCE"
            or checkpoint.get("hard_stop") is not True
        ):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        try:
            canonical_recovery_binding(record, checkpoint)
        except RecoveryError as exc:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID") from exc

        rejected = record.get("rejected_artifacts")
        if not isinstance(rejected, dict) or len(rejected) != 1:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        source_relative, source_file_sha = next(iter(rejected.items()))
        if (
            not isinstance(source_relative, str)
            or not isinstance(source_file_sha, str)
            or not _SHA.fullmatch(source_file_sha)
        ):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        source_path = self._safe_state_file(source_relative)
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_file_sha:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID") from exc
        if not isinstance(source, dict):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
        source_payload_sha = source.get("source_payload_sha256")
        if (
            source.get("schema_version") != "orchestration.pre-result-partial-source.v1"
            or not isinstance(source_payload_sha, str)
            or not _SHA.fullmatch(source_payload_sha)
            or source_payload_sha != _sha({
                k: v for k, v in source.items() if k != "source_payload_sha256"
            })
            or source.get("project_id") != project_id
            or source.get("gate_id") != request.gate_id
            or source.get("branch") != request.expected_branch
            or source.get("baseline_head") != request.expected_head
            or source.get("current_head") != actual_head
            or source.get("source_head") != actual_head
            or source.get("canonical_plan_sha256") != plan_sha256
            or source.get("approval_event_id") != record.get("approval_event_id")
            or source.get("hard_stop") is not True
        ):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")

        owned_diff = source.get("owned_diff")
        if (
            not isinstance(owned_diff, dict)
            or not owned_diff
            or sorted(owned_diff) != changed
            or any(
                not isinstance(digest, str) or not _SHA.fullmatch(digest)
                for digest in owned_diff.values()
            )
        ):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_DIRTY_SCOPE_MISMATCH")
        for relative, digest in owned_diff.items():
            target = project_root / relative
            if target.is_symlink() or not target.is_file():
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_DIRTY_SCOPE_MISMATCH")
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_DIRTY_SCOPE_MISMATCH")

        source_shas = record.get("source_shas")
        if not isinstance(source_shas, dict):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")

        def artifact(suffix: str) -> Path:
            matches = [
                (relative, digest)
                for relative, digest in source_shas.items()
                if isinstance(relative, str) and relative.endswith(suffix)
            ]
            if len(matches) != 1:
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
            relative, digest = matches[0]
            if not isinstance(digest, str) or not _SHA.fullmatch(digest):
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
            target = self._safe_state_file(relative)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")
            return target

        try:
            verified = prepare_pre_result_partial_recovery(
                self.state_root,
                project_root=project_root,
                package_manifest_path=artifact("/package.manifest.json"),
                preflight_path=artifact("/preflight/preflight.evidence.json"),
                worker_request_path=artifact("/worker.request.json"),
                process_path=artifact("/executor.process.json"),
                approval_event_id=str(record.get("approval_event_id") or ""),
                branch=request.expected_branch,
                baseline_head=request.expected_head,
                seal=False,
            )
        except (RecoveryError, OSError, subprocess.SubprocessError) as exc:
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID") from exc
        if (
            verified.get("verified_only") is not True
            or verified.get("source") != source
            or verified.get("next_attempt") != record.get("recovery_attempt")
        ):
            raise GateApprovalIssuanceError("RECOVERY_RENEWAL_EVIDENCE_INVALID")

        return {
            "schema_version": "orchestration.gate-approval-recovery-renewal.v1",
            "recovery_id": recovery_id,
            "recovery_record_hash": record_hash,
            "recovery_checkpoint_sha256": checkpoint_sha,
            "source_payload_sha256": source_payload_sha,
            "source_file_sha256": source_file_sha,
            "current_head": actual_head,
            "dirty_files": changed,
        }

    def _preflight(self, request: GateApprovalIssuanceRequest) -> tuple[dict[str, Any], str]:
        entry = self._registered_alias(request.project_alias)
        root = Path(str(entry["project_root"])).resolve(strict=True)
        actual_branch = self._git(root, "branch", "--show-current")
        actual_head = self._git(root, "rev-parse", "HEAD")
        status_text = self._git(root, "status", "--porcelain=v1", "-uall")
        if actual_branch != request.expected_branch:
            raise GateApprovalIssuanceError("SOURCE_BINDING_MISMATCH")
        mapping = load_project_mapping(root, mapping_root=self.mapping_root)
        if mapping is None or validate_mapping_sources(mapping):
            raise GateApprovalIssuanceError("MAPPING_INVALID")
        plan = load_gate_plan(root, request.gate_id, mapping_root=self.mapping_root)
        if (plan.project_id != entry["project_id"]
                or plan.canonical_plan_sha256 != mapping.canonical_sha256
                or sha256_file(mapping.canonical_source) != mapping.canonical_sha256):
            raise GateApprovalIssuanceError("PLAN_BINDING_MISMATCH")
        recovery_renewal = None
        if actual_head != request.expected_head or status_text:
            recovery_renewal = self._verified_recovery_renewal(
                request,
                project_root=root,
                project_id=plan.project_id,
                plan_sha256=plan.canonical_plan_sha256,
                actual_branch=actual_branch,
                actual_head=actual_head,
                status_text=status_text,
            )
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
        if recovery_renewal is not None:
            binding["recovery_renewal"] = recovery_renewal
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
                or not isinstance(comment.get("body"), str)
                or _canonicalize_newlines(comment["body"]) != expected):
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
