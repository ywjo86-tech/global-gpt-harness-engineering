from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .approval_gate import DANGEROUS, classify_discovery_intent
from .lv_execution_package import canonical_json_bytes
from .project_isolation import ProjectIsolation
from .schemas import CapabilityRequirement, DiscoveryLevel, DiscoveryStatus


DISCOVERY_INTENT = "skill_discovery_read_only"
OUTPUT_CONTRACT = "skills.find.json.v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_QUERY_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.I)
_SECRET_VALUE = re.compile(r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)\s*[:=]\s*\S+")
_SECRET_INPUT = re.compile(r"(?i)(?:\bbearer\s+\S+|https?://[^\s/:]+:[^\s/@]+@|\b(?:api[_-]?key|authorization|credential|password|secret|token)\s*[:=])")
_SECRET_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_SECRET_URL = re.compile(r"(?i)(https?://)[^\s/:]+:[^\s/@]+@")
_APPROVAL_FIELDS = {"schema_version", "intent", "classification", "status", "project_id", "gate_id", "lv_id"}


class SkillDiscoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DiscoveryApproval:
    intent: str
    classification: str
    approved: bool
    project_id: str
    gate_id: str
    lv_id: str
    evidence_reference: str
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class DiscoveryRuntime:
    runtime_id: str
    executable_identity: str
    resolved_executable: str
    executable_sha256: str
    version: str
    invocation_argv: tuple[str, ...]
    output_contract: str
    output_contract_verified: bool
    timeout_seconds: float
    result_limit: int
    network_required: bool
    package_auto_install_allowed: bool
    shell_allowed: bool
    environment_allowlist: tuple[str, ...]
    working_directory_policy: str
    contract_sha256: str

    def contract_payload(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "executable_identity": self.executable_identity,
            "resolved_executable": self.resolved_executable,
            "executable_sha256": self.executable_sha256,
            "version": self.version,
            "invocation_argv": list(self.invocation_argv),
            "output_contract": self.output_contract,
            "output_contract_verified": self.output_contract_verified,
            "timeout_seconds": self.timeout_seconds,
            "result_limit": self.result_limit,
            "network_required": self.network_required,
            "package_auto_install_allowed": self.package_auto_install_allowed,
            "shell_allowed": self.shell_allowed,
            "environment_allowlist": list(self.environment_allowlist),
            "working_directory_policy": self.working_directory_policy,
        }

    @property
    def runtime_trusted(self) -> bool:
        return (
            self.output_contract_verified
            and self.output_contract == OUTPUT_CONTRACT
            and self.package_auto_install_allowed is False
            and self.shell_allowed is False
            and self.contract_sha256 == hashlib.sha256(canonical_json_bytes(self.contract_payload())).hexdigest()
        )


@dataclass(frozen=True, slots=True)
class DiscoveredCandidate:
    candidate_id: str
    name: str
    source: str
    repository: str
    maintainer: str
    description: str
    reference: str
    raw_result_digest: str
    evaluation_state: str = "UNASSESSED"


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    query: str
    requirement: CapabilityRequirement
    project_root: str
    project_id: str
    gate_id: str
    lv_id: str
    approval: DiscoveryApproval
    result_limit: int
    runtime: DiscoveryRuntime | None
    timestamp: str


@dataclass(frozen=True, slots=True)
class DiscoveryAdapterResult:
    status: DiscoveryStatus
    execution_attempted: bool
    candidates: tuple[DiscoveredCandidate, ...]
    blocked_reason: str
    evidence: Mapping[str, Any]
    evidence_reference: str

    def handoff_projection(self) -> dict[str, Any]:
        return {
            "discovery_evidence_references": [self.evidence_reference] if self.evidence_reference else [],
            "discovered_candidates": [item.candidate_id for item in self.candidates],
            "evaluated_candidates": [],
            "selected_candidate": "",
            "candidate_use_authorized": False,
            "selection_rationale": "discovery only; candidate evaluation and use remain unauthorized",
        }

    def ledger_projection(self) -> dict[str, Any]:
        return self.handoff_projection()


Executor = Callable[..., subprocess.CompletedProcess[bytes]]


def _safe_text(value: str) -> str:
    value = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    value = _SECRET_BEARER.sub("Bearer [REDACTED]", value)
    return _SECRET_URL.sub(r"\1[REDACTED]@", value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _validate_request(request: DiscoveryRequest) -> Path:
    if not isinstance(request.query, str) or not request.query.strip() or len(request.query) > 512 or _QUERY_CONTROL.search(request.query):
        raise SkillDiscoveryError("query validation failed")
    if _SECRET_INPUT.search(request.query):
        raise SkillDiscoveryError("query contains Secret-like data")
    if not _ID.fullmatch(request.project_id) or not _ID.fullmatch(request.gate_id) or not _ID.fullmatch(request.lv_id):
        raise SkillDiscoveryError("project or Gate/LV identity is invalid")
    if request.requirement.gate_id != request.gate_id or request.requirement.lv_id != request.lv_id:
        raise SkillDiscoveryError("capability requirement binding mismatch")
    if any(_SECRET_KEY.search(permission) for permission in request.requirement.required_permissions):
        raise SkillDiscoveryError("discovery requiring a Secret is forbidden")
    root = Path(request.project_root)
    if not root.is_absolute() or not root.is_dir() or root != root.resolve() or root.name != request.project_id:
        raise SkillDiscoveryError("project identity or scope is unknown")
    if not isinstance(request.result_limit, int) or isinstance(request.result_limit, bool) or not 1 <= request.result_limit <= 50:
        raise SkillDiscoveryError("result limit is invalid")
    if not isinstance(request.timestamp, str) or not request.timestamp or _QUERY_CONTROL.search(request.timestamp):
        raise SkillDiscoveryError("execution timestamp is invalid")
    return root


def _approval_reason(request: DiscoveryRequest, root: Path) -> str:
    approval = request.approval
    assessment = classify_discovery_intent(DISCOVERY_INTENT)
    structurally_valid = (
        assessment.classification == DANGEROUS
        and approval.intent == DISCOVERY_INTENT
        and approval.classification == DANGEROUS
        and approval.approved is True
        and approval.project_id == request.project_id
        and approval.gate_id == request.gate_id
        and approval.lv_id == request.lv_id
        and isinstance(approval.evidence_reference, str)
        and bool(approval.evidence_reference)
        and not Path(approval.evidence_reference).is_absolute()
        and not _SECRET_KEY.search(approval.evidence_reference)
        and bool(_SHA256.fullmatch(approval.evidence_sha256))
    )
    if not structurally_valid:
        return "dangerous discovery approval required or binding mismatch"
    relative = Path(approval.evidence_reference)
    if ".." in relative.parts:
        return "dangerous discovery approval evidence path is unsafe"
    source = root / relative
    try:
        if (not source.is_file() or source.is_symlink() or source != source.resolve() or not source.is_relative_to(root)
                or hashlib.sha256(source.read_bytes()).hexdigest() != approval.evidence_sha256):
            return "dangerous discovery approval evidence is missing or has drifted"
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "dangerous discovery approval evidence is missing or malformed"
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "record_hash"} or not isinstance(envelope.get("payload"), dict):
        return "dangerous discovery approval evidence schema mismatch"
    payload = envelope["payload"]
    expected = {
        "schema_version": "orchestration.skill-discovery.approval.v1", "intent": DISCOVERY_INTENT,
        "classification": DANGEROUS, "status": "ACTIVE", "project_id": request.project_id,
        "gate_id": request.gate_id, "lv_id": request.lv_id,
    }
    if set(payload) != _APPROVAL_FIELDS or payload != expected or envelope["record_hash"] != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        return "dangerous discovery approval evidence binding mismatch"
    return ""


def _runtime_reason(runtime: DiscoveryRuntime | None, registry: Mapping[str, DiscoveryRuntime]) -> str:
    if runtime is None:
        return "discovery executable is unavailable"
    if registry.get(runtime.contract_sha256) != runtime:
        return "discovery runtime is not in the trusted allowlist"
    path = Path(runtime.resolved_executable)
    name = path.name.lower()
    if name in {"npx", "npm", "node"}:
        return "automatic package installation path is forbidden"
    if runtime.package_auto_install_allowed or runtime.shell_allowed:
        return "automatic package installation path is forbidden"
    if (not runtime.runtime_trusted or not runtime.version or runtime.invocation_argv != ("find", "{query}")
            or runtime.working_directory_policy != "verified_project_root"
            or runtime.result_limit < 1 or runtime.timeout_seconds <= 0
            or not runtime.runtime_id or not runtime.executable_identity
            or runtime.executable_identity != path.name
            or any(not _ENV_NAME.fullmatch(name) or _SECRET_KEY.search(name) for name in runtime.environment_allowlist)
            or not _SHA256.fullmatch(runtime.contract_sha256)
            or not _SHA256.fullmatch(runtime.executable_sha256)):
        return "runtime contract is unverified or incompatible"
    if not path.is_absolute() or not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
        return "discovery executable is unavailable or unsafe"
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != runtime.executable_sha256:
            return "runtime executable digest does not match the verified contract"
    except OSError:
        return "discovery executable is unavailable or unsafe"
    return ""


def _candidate(record: object) -> DiscoveredCandidate:
    if not isinstance(record, dict):
        raise SkillDiscoveryError("malformed candidate")
    allowed = {"id", "name", "source", "repository", "maintainer", "description", "reference"}
    if set(record) - allowed or any(_SECRET_KEY.search(str(key)) for key in record):
        raise SkillDiscoveryError("malformed candidate")
    required = ("id", "name", "source", "repository", "description", "reference")
    if any(not isinstance(record.get(key), str) or not record[key].strip() for key in required):
        raise SkillDiscoveryError("malformed candidate")
    maintainer = record.get("maintainer", "")
    if not isinstance(maintainer, str):
        raise SkillDiscoveryError("malformed candidate")
    raw_digest = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    return DiscoveredCandidate(
        candidate_id=_safe_text(record["id"]), name=_safe_text(record["name"]),
        source=_safe_text(record["source"]), repository=_safe_text(record["repository"]),
        maintainer=_safe_text(maintainer), description=_safe_text(record["description"]),
        reference=_safe_text(record["reference"]), raw_result_digest=raw_digest,
    )


def _parse(stdout: bytes, limit: int) -> tuple[DiscoveredCandidate, ...]:
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillDiscoveryError("discovery output parse failed") from exc
    if not isinstance(payload, dict) or set(payload) != {"candidates"} or not isinstance(payload["candidates"], list):
        raise SkillDiscoveryError("discovery output contract mismatch")
    # Validate every record, including records beyond the returned limit. A malformed
    # tail must not be hidden by truncation.
    normalized = tuple(_candidate(item) for item in payload["candidates"])
    return normalized[:limit]


def _evidence(
    request: DiscoveryRequest, *, status: DiscoveryStatus, preflight: str,
    attempted: bool, candidates: Sequence[DiscoveredCandidate], blocked_reason: str,
    executable_resolved: bool, execution_digest: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "orchestration.skill-discovery.evidence.v1",
        "capability_requirement_id": request.requirement.capability_id,
        "project_id": request.project_id,
        "gate_id": request.gate_id,
        "lv_id": request.lv_id,
        "discovery_level": DiscoveryLevel.DISCOVERY.value,
        "discovery_status": status.value,
        "query": _safe_text(request.query),
        "approval_state": {
            "intent": request.approval.intent,
            "classification": request.approval.classification,
            "approved": request.approval.approved,
            "evidence_reference": request.approval.evidence_reference if not _SECRET_KEY.search(request.approval.evidence_reference) else "[REDACTED]",
            "evidence_sha256": request.approval.evidence_sha256,
        },
        "adapter_preflight": preflight,
        "executable_resolution": {
            "resolved": executable_resolved,
            "runtime_id": request.runtime.runtime_id if request.runtime else "",
            "executable_name": Path(request.runtime.resolved_executable).name if request.runtime else "",
            "version": request.runtime.version if request.runtime and executable_resolved else "",
            "output_contract": request.runtime.output_contract if request.runtime and executable_resolved else "",
            "contract_sha256": request.runtime.contract_sha256 if request.runtime and executable_resolved else "",
        },
        "execution_attempted": attempted,
        "execution_digest": execution_digest,
        "candidate_count": len(candidates),
        "normalized_candidate_ids": [item.candidate_id for item in candidates],
        "candidate_evaluation_state": "UNASSESSED",
        "blocked_reason": blocked_reason,
        "timestamp": request.timestamp,
        "used_assets": [],
        "selected_asset": "",
    }
    payload = _redact(payload)
    payload["evidence_digest"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return payload


def _persist(isolation: ProjectIsolation | None, evidence: Mapping[str, Any]) -> str:
    if isolation is None:
        return f"sha256:{evidence['evidence_digest']}"
    data = canonical_json_bytes(evidence)
    digest = evidence.get("evidence_digest")
    unsigned = dict(evidence); unsigned.pop("evidence_digest", None)
    if digest != hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest():
        raise SkillDiscoveryError("evidence digest failed")
    relative = f"skill-discovery/{digest}.json"
    isolation.write_exclusive("artifact", relative, data)
    return f"artifact/{relative}"


def run_read_only_discovery(
    request: DiscoveryRequest, *, executor: Executor = subprocess.run,
    isolation: ProjectIsolation | None = None, timeout: float = 30.0,
    runtime_registry: Mapping[str, DiscoveryRuntime] = {},
) -> DiscoveryAdapterResult:
    attempted = False
    candidates: tuple[DiscoveredCandidate, ...] = ()
    execution_digest = ""
    try:
        root = _validate_request(request)
        blocked_reason = _approval_reason(request, root)
        if not blocked_reason:
            blocked_reason = _runtime_reason(request.runtime, runtime_registry)
        if not blocked_reason and request.runtime is not None and request.result_limit > request.runtime.result_limit:
            blocked_reason = "request result limit exceeds trusted runtime contract"
        if blocked_reason:
            evidence = _evidence(request, status=DiscoveryStatus.BLOCKED, preflight="BLOCKED", attempted=False,
                                 candidates=(), blocked_reason=blocked_reason,
                                 executable_resolved=False, execution_digest="")
            reference = _persist(isolation, evidence)
            return DiscoveryAdapterResult(DiscoveryStatus.BLOCKED, False, (), blocked_reason, evidence, reference)
        assert request.runtime is not None
        argv = [request.runtime.resolved_executable, "find", request.query]
        allowed_env = {name: os.environ[name] for name in request.runtime.environment_allowlist if name in os.environ}
        attempted = True
        completed = executor(argv, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False, timeout=request.runtime.timeout_seconds,
                             env=allowed_env, cwd=str(root))
        stdout = bytes(completed.stdout or b"")
        stderr = bytes(completed.stderr or b"")
        execution_digest = hashlib.sha256(stdout + b"\0" + stderr).hexdigest()
        if int(completed.returncode) != 0:
            raise SkillDiscoveryError("discovery executor failed")
        candidates = _parse(stdout, request.result_limit)
        evidence = _evidence(request, status=DiscoveryStatus.DISCOVERY_COMPLETED, preflight="PASS", attempted=True,
                             candidates=candidates, blocked_reason="", executable_resolved=True,
                             execution_digest=execution_digest)
        reference = _persist(isolation, evidence)
        return DiscoveryAdapterResult(DiscoveryStatus.DISCOVERY_COMPLETED, True, candidates, "", evidence, reference)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, SkillDiscoveryError) else "discovery execution or evidence generation failed"
        evidence = _evidence(request, status=DiscoveryStatus.BLOCKED, preflight="BLOCKED", attempted=attempted,
                             candidates=(), blocked_reason=reason, executable_resolved=False,
                             execution_digest=execution_digest)
        try:
            reference = _persist(isolation, evidence)
        except Exception:
            reference = ""
            reason = "evidence generation or persistence failed"
        return DiscoveryAdapterResult(DiscoveryStatus.BLOCKED, attempted, (), reason, evidence, reference)
