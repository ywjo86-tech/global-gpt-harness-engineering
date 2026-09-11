from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlparse

from .lv_execution_package import canonical_json_bytes
from .schemas import DiscoveryStatus
from .skill_discovery import RawDiscoveredCandidate


RESOLUTION_CONTRACT = "orchestration.candidate-content-resolution.v1"
MAX_SKILL_MD_BYTES = 1_048_576
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMMUTABLE_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REPOSITORY_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.I)


@dataclass(frozen=True, slots=True)
class CandidateResolutionIntent:
    project_id: str
    gate_id: str
    lv_id: str
    candidate_id: str
    intent: str
    status: str

    def valid(self) -> bool:
        return (
            self.intent == "read_only_candidate_content_resolution"
            and self.status == "APPROVED"
            and all((self.project_id, self.gate_id, self.lv_id, self.candidate_id))
        )


@dataclass(frozen=True, slots=True)
class ResolutionTransportContract:
    transport: str
    discovery_source: str
    provider: str
    owner: str
    repository: str
    source_url: str
    immutable_revision: str
    candidate_path: str
    source_evidence_reference: str
    source_evidence_digest: str
    expected_skill_md_digest: str = ""
    private_repository: bool = False
    authentication_required: bool = False
    paid_service_required: bool = False


@dataclass(frozen=True, slots=True)
class CandidateContentResolutionRequest:
    raw_candidate: RawDiscoveredCandidate
    source: str
    candidate_id: str
    project_id: str
    gate_id: str
    lv_id: str
    intent: CandidateResolutionIntent
    transport: ResolutionTransportContract
    timestamp: str


@dataclass(frozen=True, slots=True)
class CandidateContentResolutionResult:
    status: DiscoveryStatus
    provenance_state: str
    repository_identity: Mapping[str, str]
    immutable_revision: str
    candidate_path: str
    skill_md_content: str
    skill_md_digest: str
    source_metadata: Mapping[str, Any]
    evidence: Mapping[str, Any]
    evidence_reference: str
    blocked_reason: str
    escalation_reason: str
    install_authorized: bool = False
    candidate_use_authorized: bool = False
    gate_passed: bool = False

    def ledger_projection(self) -> dict[str, Any]:
        return {
            "candidate_resolution_evidence_reference": self.evidence_reference,
            "resolved_candidates": [self.evidence.get("candidate_id")] if self.provenance_state == "VERIFIED" else [],
            "install_authorized": False,
            "candidate_use_authorized": False,
        }


ContentReader = Callable[[Path], bytes]


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("candidate path is empty or unsafe")
    decoded = value
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if decoded != value:
        raise ValueError("encoded candidate path is forbidden")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.as_posix() != value or ".." in pure.parts or value in {".", ""}:
        raise ValueError("candidate path must be repository-relative")
    return value


def _repository_identity(contract: ResolutionTransportContract) -> dict[str, str]:
    if not all(isinstance(value, str) and value for value in (
        contract.owner, contract.repository, contract.source_url, contract.provider
    )):
        raise ValueError("repository UNKNOWN")
    if "UNKNOWN" in {contract.owner.upper(), contract.repository.upper(), contract.provider.upper()}:
        raise ValueError("repository UNKNOWN")
    if not _REPOSITORY_PART.fullmatch(contract.owner) or not _REPOSITORY_PART.fullmatch(contract.repository):
        raise ValueError("repository identity is invalid")
    parsed = urlparse(contract.source_url)
    if parsed.scheme not in {"https", "file"} or not parsed.netloc and parsed.scheme != "file":
        raise ValueError("repository source URL is invalid")
    if contract.provider.lower() == "github":
        path_parts = tuple(part for part in parsed.path.removesuffix(".git").split("/") if part)
        if parsed.netloc.lower() != "github.com" or path_parts != (contract.owner, contract.repository):
            raise ValueError("source/repository mismatch")
    return {
        "owner": contract.owner,
        "repository": contract.repository,
        "source_url": contract.source_url,
        "provider": contract.provider,
    }


def _validate_local_file(root: Path, candidate_path: str) -> Path:
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or root != root.resolve():
        raise ValueError("fixture repository root is unsafe")
    target = root.joinpath(*PurePosixPath(candidate_path).parts, "SKILL.md")
    cursor = root
    for part in target.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("candidate path symlink escape")
    if not target.is_file():
        raise ValueError("SKILL.md missing")
    if root not in target.resolve().parents:
        raise ValueError("candidate path repository root escape")
    return target


def verify_resolution_evidence(evidence: Mapping[str, Any]) -> bool:
    try:
        unsigned = dict(evidence)
        digest = unsigned.pop("evidence_digest")
        return (
            unsigned.get("schema_version") == RESOLUTION_CONTRACT
            and bool(_SHA256.fullmatch(str(digest)))
            and digest == hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
        )
    except Exception:
        return False


def _redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else item for key, item in value.items()}


def resolve_candidate_content(
    request: CandidateContentResolutionRequest,
    *,
    fixture_root: str | Path | None = None,
    content_reader: ContentReader | None = None,
    network_executor: Callable[..., object] | None = None,
) -> CandidateContentResolutionResult:
    del network_executor  # Network resolution is intentionally outside the Phase 3D boundary.
    blocked = ""
    escalated = ""
    identity: dict[str, str] = {}
    evidence: dict[str, Any] = {}
    candidate_path = ""
    revision = ""
    content = ""
    content_digest = ""
    source_metadata: dict[str, Any] = {}
    try:
        candidate = request.raw_candidate
        contract = request.transport
        if not isinstance(candidate, RawDiscoveredCandidate):
            raise ValueError("raw candidate is invalid")
        if not request.intent.valid() or any((
            request.intent.project_id != request.project_id,
            request.intent.gate_id != request.gate_id,
            request.intent.lv_id != request.lv_id,
            request.intent.candidate_id != request.candidate_id,
        )):
            raise ValueError("resolution intent binding mismatch")
        if candidate.candidate_id != request.candidate_id or candidate.skill_id != request.candidate_id:
            raise ValueError("candidate id binding mismatch")
        if not _SHA256.fullmatch(candidate.raw_result_digest) or not request.timestamp:
            raise ValueError("raw candidate or timestamp evidence is invalid")
        if candidate.source != request.source or contract.discovery_source != request.source:
            raise ValueError("source binding mismatch")
        if contract.private_repository or contract.authentication_required or contract.paid_service_required:
            reasons = []
            if contract.private_repository:
                reasons.append("private repository")
            if contract.authentication_required:
                reasons.append("authenticated fetch requirement")
            if contract.paid_service_required:
                reasons.append("external paid service")
            escalated = ", ".join(reasons)
            raise PermissionError(escalated)
        identity = _repository_identity(contract)
        revision = contract.immutable_revision
        if not _IMMUTABLE_REVISION.fullmatch(revision) or revision in {"main", "master"}:
            raise ValueError("immutable revision UNKNOWN or mutable")
        candidate_path = _safe_relative_path(contract.candidate_path)
        if not _SHA256.fullmatch(contract.source_evidence_digest) or not contract.source_evidence_reference:
            raise ValueError("transport/source evidence is invalid")
        source_binding = {
            "provider": contract.provider,
            "owner": contract.owner,
            "repository": contract.repository,
            "source_url": contract.source_url,
            "immutable_revision": revision,
            "candidate_path": candidate_path,
            "source_evidence_reference": contract.source_evidence_reference,
        }
        if contract.source_evidence_digest != hashlib.sha256(canonical_json_bytes(source_binding)).hexdigest():
            raise ValueError("repository/revision/path source evidence binding mismatch")
        if contract.transport != "LOCAL_FIXTURE":
            raise ValueError("network resolution requires separate approval and implementation")
        if fixture_root is None:
            raise ValueError("fixture repository root is required")
        target = _validate_local_file(Path(fixture_root), candidate_path)
        raw = (content_reader or Path.read_bytes)(target)
        if not raw or len(raw) > MAX_SKILL_MD_BYTES:
            raise ValueError("SKILL.md is empty or exceeds size limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SKILL.md encoding must be UTF-8") from exc
        if not content.strip():
            raise ValueError("SKILL.md is empty")
        content_digest = hashlib.sha256(raw).hexdigest()
        if contract.expected_skill_md_digest and contract.expected_skill_md_digest != content_digest:
            raise ValueError("SKILL.md digest mismatch")
        source_metadata = _redact_mapping({
            "transport": contract.transport,
            "source_url": contract.source_url,
            "source_evidence_reference": contract.source_evidence_reference,
            "source_evidence_digest": contract.source_evidence_digest,
        })
        evidence = {
            "schema_version": RESOLUTION_CONTRACT,
            "candidate_id": request.candidate_id,
            "source": request.source,
            "repository": f"{contract.owner}/{contract.repository}",
            "owner": contract.owner,
            "provider": contract.provider,
            "source_url": contract.source_url,
            "immutable_revision": revision,
            "candidate_path": candidate_path,
            "skill_md_relative_path": f"{candidate_path}/SKILL.md",
            "skill_md_digest": content_digest,
            "source_evidence_reference": contract.source_evidence_reference,
            "source_evidence_digest": contract.source_evidence_digest,
            "project_id": request.project_id,
            "gate_id": request.gate_id,
            "lv_id": request.lv_id,
            "timestamp": request.timestamp,
            "provenance_state": "VERIFIED",
            "install_authorized": False,
            "candidate_use_authorized": False,
            "gate_passed": False,
        }
        evidence["evidence_digest"] = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
        if not verify_resolution_evidence(evidence):
            raise ValueError("resolver evidence digest failed")
        return CandidateContentResolutionResult(
            DiscoveryStatus.DISCOVERY_COMPLETED, "VERIFIED", identity, revision, candidate_path,
            content, content_digest, source_metadata, evidence, f"sha256:{evidence['evidence_digest']}", "", "",
        )
    except PermissionError:
        status = DiscoveryStatus.ESCALATION_REQUIRED
    except Exception as exc:
        status = DiscoveryStatus.BLOCKED
        blocked = str(exc) or "candidate content resolution failed"
    return CandidateContentResolutionResult(
        status, "PENDING_PROVENANCE" if status == DiscoveryStatus.BLOCKED else "ESCALATION_REQUIRED",
        identity, revision, candidate_path, "", "", source_metadata, evidence, "", blocked, escalated,
    )
