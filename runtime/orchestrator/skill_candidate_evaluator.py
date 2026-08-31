from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .lv_execution_package import canonical_json_bytes
from .project_isolation import AssetManifest, ProjectIsolation, route_assets
from .schemas import CandidateEvaluationState, CandidateRisk, CapabilityRequirement, DiscoveryStatus


EVALUATOR_CONTRACT = "orchestration.skill-candidate-evaluator.v1"
EVALUATOR_VERSION = "1.0"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.I)
_SECRET_VALUE = re.compile(r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)\s*[:=]\s*\S+")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_CONTENT_RISK_PATTERNS = {
    "network": re.compile(r"(?i)https?://|\bcurl\b|\bwget\b"),
    "shell": re.compile(r"(?i)```(?:bash|sh|shell)|\bsubprocess\b|\bshell\s*=\s*true"),
    "package_install": re.compile(r"(?i)\b(?:npm|pip|apt|get|brew)\s+install\b|\bnpx\b"),
    "secret": re.compile(r"(?i)\b(?:api[_ -]?key|auth(?:orization)? header|password|secret|access token|bearer token)\b"),
    "file_write": re.compile(r"(?i)\b(?:write|edit|modify|create)\s+(?:a |the )?(?:file|files|directory|repository)\b"),
    "external_service": re.compile(r"(?i)\bexternal service\b|https?://"),
    "paid_service": re.compile(r"(?i)\b(?:paid service|billing|purchase|subscription)\b"),
    "deployment": re.compile(r"(?i)\bdeploy(?:ment|s|ed|ing)?\b"),
    "global_change": re.compile(r"(?i)\bglobal(?:ly)?\s+(?:install|change|modify)|(?:^|\s)-g(?:\s|$)"),
    "destructive_action": re.compile(r"(?i)\brm\s+-rf\b|\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f)|\bdelete\s+(?:all|repository|directory)\b"),
}


@dataclass(frozen=True, slots=True)
class CandidateEvaluationRequest:
    requirement: CapabilityRequirement
    project_id: str
    gate_id: str
    lv_id: str
    candidate_id: str
    source: str
    repository: str
    maintainer: str
    candidate_metadata: Mapping[str, Any]
    skill_md_text: str
    provenance: str
    content_digest: str
    permissions: tuple[str, ...]
    owned_files: tuple[str, ...]
    timestamp: str


@dataclass(frozen=True, slots=True)
class CandidateEvaluationResult:
    status: DiscoveryStatus
    evaluation_state: CandidateEvaluationState
    completed_states: tuple[CandidateEvaluationState, ...]
    risk: CandidateRisk
    risk_flags: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    escalation_reasons: tuple[str, ...]
    duplicate_status: str
    execution_allowed: bool
    candidate_use_authorized: bool
    evidence: Mapping[str, Any]
    evidence_reference: str

    def handoff_projection(self) -> dict[str, Any]:
        candidate_id = str(self.evidence.get("candidate_id", ""))
        evaluated = [candidate_id] if self.evaluation_state in {
            CandidateEvaluationState.POLICY_EVALUATED,
            CandidateEvaluationState.SAFE_FOR_CONSIDERATION,
        } else []
        return {
            "discovery_evidence_references": [self.evidence_reference] if self.evidence_reference else [],
            "discovered_candidates": [candidate_id] if candidate_id else [],
            "evaluated_candidates": evaluated,
            "selected_candidate": "",
            "candidate_use_authorized": False,
            "selection_rationale": "evaluation only; selection, approval, installation, use, and Gate PASS remain separate",
        }

    def ledger_projection(self) -> dict[str, Any]:
        return self.handoff_projection()


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value))
    return value


def exact_capability_duplicate(
    requirement: CapabilityRequirement,
    manifests: Sequence[AssetManifest],
    agent_registry: Mapping[str, object],
) -> str:
    """Return an exact-contract duplicate decision; never use substring/fuzzy matching."""
    try:
        if requirement.capability_id in agent_registry:
            return "EXACT_DUPLICATE"
        routed = route_assets(
            manifests,
            capabilities={requirement.capability_id},
            permissions=set(requirement.required_permissions),
            owned_files=requirement.owned_files,
        )
        return "EXACT_DUPLICATE" if routed["selected"] else "NO_EXACT_DUPLICATE"
    except Exception:
        return "UNKNOWN"


def verify_evaluation_evidence(evidence: Mapping[str, Any]) -> bool:
    try:
        unsigned = dict(evidence)
        digest = unsigned.pop("evidence_digest")
        return bool(_SHA256.fullmatch(str(digest))) and digest == hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    except Exception:
        return False


def _bool_or_unknown(metadata: Mapping[str, Any], key: str) -> bool | None:
    value = metadata.get(key)
    return value if isinstance(value, bool) else None


def evaluate_candidate(
    request: CandidateEvaluationRequest,
    *,
    manifests: Sequence[AssetManifest] = (),
    agent_registry: Mapping[str, object] = {},
    isolation: ProjectIsolation | None = None,
) -> CandidateEvaluationResult:
    completed: list[CandidateEvaluationState] = []
    blocked: list[str] = []
    escalated: list[str] = []
    risk = CandidateRisk()
    duplicate = "UNKNOWN"
    state = CandidateEvaluationState.UNASSESSED
    evidence: dict[str, Any] = {}
    reference = ""
    try:
        if not isinstance(request.requirement, CapabilityRequirement):
            raise ValueError("malformed evaluator input")
        if request.requirement.gate_id != request.gate_id or request.requirement.lv_id != request.lv_id:
            blocked.append("project/Gate/LV binding mismatch")
        for label, value in (("candidate id", request.candidate_id), ("source", request.source),
                             ("repository", request.repository), ("maintainer", request.maintainer),
                             ("provenance", request.provenance),
                             ("project id", request.project_id), ("timestamp", request.timestamp)):
            if not isinstance(value, str) or not value.strip():
                blocked.append(f"{label} is unknown")
        if not isinstance(request.candidate_metadata, Mapping):
            blocked.append("malformed candidate metadata")
        if blocked:
            state = CandidateEvaluationState.BLOCKED
        else:
            completed.append(CandidateEvaluationState.METADATA_VALIDATED)
            state = CandidateEvaluationState.METADATA_VALIDATED

        actual_digest = hashlib.sha256(request.skill_md_text.encode("utf-8")).hexdigest() if isinstance(request.skill_md_text, str) else ""
        if not request.skill_md_text.strip() if isinstance(request.skill_md_text, str) else True:
            blocked.append("SKILL.md validation failed")
        if not _SHA256.fullmatch(request.content_digest) or actual_digest != request.content_digest:
            blocked.append("SKILL.md digest mismatch")
        provenance_payload = {
            "candidate_id": request.candidate_id, "source": request.source,
            "repository": request.repository, "maintainer": request.maintainer,
            "content_digest": request.content_digest, "provenance": request.provenance,
        }
        expected_provenance_digest = hashlib.sha256(canonical_json_bytes(provenance_payload)).hexdigest()
        if request.candidate_metadata.get("provenance_digest") != expected_provenance_digest:
            blocked.append("provenance binding mismatch")
        if not blocked:
            completed.append(CandidateEvaluationState.CONTENT_VALIDATED)
            state = CandidateEvaluationState.CONTENT_VALIDATED

        metadata = request.candidate_metadata
        flag_names = {
            "network": "network", "shell": "shell", "package_install": "package_install",
            "secret": "secret", "file_write": "file_write", "external_service": "external_service",
            "paid_service": "paid_service", "deployment": "deployment", "global_change": "global_change",
            "destructive_action": "destructive_action",
        }
        values = {field: _bool_or_unknown(metadata, key) for field, key in flag_names.items()}
        detected = {field: bool(pattern.search(request.skill_md_text)) for field, pattern in _CONTENT_RISK_PATTERNS.items()}
        for field, present in detected.items():
            if present and values[field] is not True:
                blocked.append(f"SKILL.md risk metadata mismatch: {field}")
            if present:
                values[field] = True
        risk = CandidateRisk(**{field: value is True for field, value in values.items()})
        permissions = metadata.get("permissions")
        owned_files = metadata.get("owned_files")
        if not isinstance(permissions, (list, tuple)) or set(request.requirement.required_permissions) - set(permissions):
            blocked.append("permission mismatch")
        if not isinstance(owned_files, (list, tuple)) or set(request.requirement.owned_files) - set(owned_files):
            blocked.append("owned-file mismatch")
        if tuple(request.permissions) != tuple(permissions or ()):
            blocked.append("permission metadata mismatch")
        if tuple(request.owned_files) != tuple(owned_files or ()):
            blocked.append("owned-file metadata mismatch")
        if metadata.get("skill_md_exists") is not True:
            blocked.append("SKILL.md validation failed")
        if metadata.get("license") is None:
            blocked.append("license metadata is UNKNOWN")
        if metadata.get("project_applicable") is not True:
            blocked.append("project applicability is UNKNOWN or incompatible")
        if metadata.get("global_install_required") is True:
            escalated.append("Global installation")
        elif metadata.get("global_install_required") is not False:
            blocked.append("global installation requirement is UNKNOWN")
        unknown_flags = [name for name, value in values.items() if value is None]
        if unknown_flags:
            blocked.append("risk metadata is UNKNOWN: " + ",".join(sorted(unknown_flags)))
        if risk.secret:
            blocked.append("Secret/API key requirement")
        if risk.destructive_action:
            blocked.append("destructive action")
        if metadata.get("external_write_scope_known") is False:
            escalated.append("external write scope cannot be established")
        if metadata.get("credential_required") is True:
            escalated.append("credential requirement")
        for active, reason in ((risk.package_install, "package installation"), (risk.global_change, "Global change"),
                               (risk.deployment, "deployment"), (risk.paid_service, "paid service")):
            if active:
                escalated.append(reason)
        duplicate = exact_capability_duplicate(request.requirement, manifests, agent_registry)
        if duplicate == "UNKNOWN":
            blocked.append("existing capability duplicate status is UNKNOWN")
        if not blocked and not escalated:
            completed.append(CandidateEvaluationState.POLICY_EVALUATED)
            completed.append(CandidateEvaluationState.SAFE_FOR_CONSIDERATION)
            state = CandidateEvaluationState.SAFE_FOR_CONSIDERATION
        elif blocked:
            state = CandidateEvaluationState.BLOCKED
        else:
            completed.append(CandidateEvaluationState.POLICY_EVALUATED)
            state = CandidateEvaluationState.ESCALATION_REQUIRED

        status = DiscoveryStatus.BLOCKED if blocked else (DiscoveryStatus.ESCALATION_REQUIRED if escalated else DiscoveryStatus.CANDIDATE_EVALUATED)
        risk_flags = tuple(key for key, value in asdict(risk).items() if value)
        evidence = _redact({
            "schema_version": "orchestration.skill-candidate-evaluation.evidence.v1",
            "project_id": request.project_id, "gate_id": request.gate_id, "lv_id": request.lv_id,
            "capability_requirement": request.requirement.capability_id,
            "candidate_id": request.candidate_id, "source": request.source,
            "repository": request.repository, "skill_md_digest": request.content_digest,
            "evaluation_state": state.value, "completed_states": [item.value for item in completed],
            "risk_flags": list(risk_flags), "blocked_reasons": blocked,
            "escalation_reasons": escalated, "duplicate_status": duplicate,
            "evaluator_contract": EVALUATOR_CONTRACT, "evaluator_version": EVALUATOR_VERSION,
            "timestamp": request.timestamp, "execution_allowed": False,
            "candidate_use_authorized": False,
        })
        evidence["evidence_digest"] = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
        if not verify_evaluation_evidence(evidence):
            raise ValueError("evaluation evidence digest failed")
        if isolation is None:
            reference = f"sha256:{evidence['evidence_digest']}"
        else:
            relative = f"skill-candidate-evaluation/{evidence['evidence_digest']}.json"
            isolation.write_exclusive("artifact", relative, canonical_json_bytes(evidence))
            reference = f"artifact/{relative}"
        return CandidateEvaluationResult(status, state, tuple(completed), risk, risk_flags, tuple(blocked), tuple(escalated), duplicate, False, False, evidence, reference)
    except Exception:
        state = CandidateEvaluationState.BLOCKED
        blocked = ["malformed evaluator input or evidence generation failed"]
        evidence = {
            "schema_version": "orchestration.skill-candidate-evaluation.evidence.v1",
            "project_id": _redact(getattr(request, "project_id", "")), "gate_id": _redact(getattr(request, "gate_id", "")),
            "lv_id": _redact(getattr(request, "lv_id", "")), "capability_requirement": "",
            "candidate_id": _redact(getattr(request, "candidate_id", "")), "source": "", "repository": "",
            "skill_md_digest": "", "evaluation_state": state.value, "completed_states": [], "risk_flags": [],
            "blocked_reasons": blocked, "escalation_reasons": [], "duplicate_status": "UNKNOWN",
            "evaluator_contract": EVALUATOR_CONTRACT, "evaluator_version": EVALUATOR_VERSION,
            "timestamp": _redact(getattr(request, "timestamp", "")), "execution_allowed": False,
            "candidate_use_authorized": False,
        }
        evidence["evidence_digest"] = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
        return CandidateEvaluationResult(DiscoveryStatus.BLOCKED, state, (), CandidateRisk(), (), tuple(blocked), (), "UNKNOWN", False, False, evidence, "")
