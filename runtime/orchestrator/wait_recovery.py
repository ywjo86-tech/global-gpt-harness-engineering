"""Typed Full Plan wait classification and evidence-bound recovery evaluation.

This module never selects a provider, executes an effect, or advances a Gate.
It only classifies waits and evaluates whether canonical owners may reopen them.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json
from .provider_router import (
    ProviderEligibilitySnapshotV1,
    route_request,
    router_request_from_mapping,
)

PROVIDER_WAIT_EVIDENCE_SCHEMA = "orchestration.provider-wait-recovery-evidence.v1"
PROVIDER_WAIT_POINTER_SCHEMA = "orchestration.provider-wait-recovery-pointer.v1"


class WaitRecoveryError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 180 or "/" in text or "\\" in text or ".." in text:
        raise WaitRecoveryError(f"unsafe {label}")
    return text


@dataclass(frozen=True, slots=True)
class WaitRecoveryAssessment:
    state: str
    reason: str
    owner: str
    auto_recoverable: bool


@dataclass(frozen=True, slots=True)
class ProviderWaitRecoveryDecision:
    resume_allowed: bool
    reason: str
    router_request_sha256: str
    fresh_router_request_sha256: str
    output_contract_sha256: str
    validation_contract_sha256: str
    risk_contract_sha256: str
    router_decision: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ResourceWaitRecoveryDecision:
    resume_allowed: bool
    reason: str
    state_sha256: str
    epoch: int


_RULES = {
    ("WAITING_RESOURCE", "OPERATOR_DISPATCH_ACK_PENDING"): ("DCC_OR_OPERATOR", True),
    ("WAITING_RESOURCE", "OPERATOR_TASK_RECEIPT_PENDING"): ("DCC_OR_OPERATOR", True),
    ("WAITING_RESOURCE", "CONTINUATION_RECOVERY_PENDING"): ("DCC_RECONCILER", True),
    ("WAITING_RESOURCE", "LOW_RESOURCE_BACKPRESSURE"): ("RESOURCE_RECOVERY", True),
    ("WAITING_RESOURCE", "RUNTIME_MIGRATION_QUIESCED"): ("RUNTIME_MIGRATION", False),
    ("WAITING_PROVIDER", "PROVIDER_UNAVAILABLE"): ("PROVIDER_RECOVERY", True),
    ("WAITING_PROVIDER", "PROVIDER_RECOVERY_PENDING"): ("PROVIDER_RECOVERY", True),
}


def classify_wait_recovery(value: Mapping[str, Any]) -> WaitRecoveryAssessment:
    state = str(value.get("state") or "")
    reason = str(value.get("wait_reason") or value.get("last_error") or "")
    if state == "WAITING_APPROVAL":
        return WaitRecoveryAssessment(state, reason, "USER_DECISION", False)
    rule = _RULES.get((state, reason))
    if rule is None:
        raise WaitRecoveryError("unknown or incompatible wait reason")
    return WaitRecoveryAssessment(state, reason, rule[0], rule[1])


def build_provider_wait_recovery_evidence(
    *, project_id: str, gate_run_id: str, gate_id: str, lv_id: str, lv_run_id: str,
    project_root: str | Path, source_head: str,
    router_request: Mapping[str, Any], router_decision: Mapping[str, Any],
    output_contract: Mapping[str, Any], validation_contract: Mapping[str, Any],
    risk_contract: Mapping[str, Any],
) -> dict[str, Any]:
    request = router_request_from_mapping(router_request)
    canonical_decision = route_request(request).to_dict()
    if dict(router_decision) != canonical_decision:
        raise WaitRecoveryError("provider wait Router decision is not canonical")
    if len(str(source_head)) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in str(source_head)):
        raise WaitRecoveryError("provider wait source HEAD is invalid")
    payload: dict[str, Any] = {
        "schema_version": PROVIDER_WAIT_EVIDENCE_SCHEMA,
        "project_id": _safe_id(project_id, "project ID"),
        "gate_run_id": _safe_id(gate_run_id, "Gate run ID"),
        "gate_id": _safe_id(gate_id, "Gate ID"),
        "lv_id": _safe_id(lv_id, "LV ID"),
        "lv_run_id": _safe_id(lv_run_id, "LV run ID"),
        "project_root": str(Path(project_root).expanduser().absolute()),
        "source_head": str(source_head),
        "router_request": dict(router_request),
        "router_request_sha256": request.request_digest,
        "router_decision": dict(router_decision),
        "router_decision_sha256": str(canonical_decision["decision_digest"]),
        "required_capabilities": list(request.required_capabilities),
        "output_contract": dict(output_contract),
        "output_contract_sha256": _digest(output_contract),
        "validation_contract": dict(validation_contract),
        "validation_contract_sha256": _digest(validation_contract),
        "risk_contract": dict(risk_contract),
        "risk_contract_sha256": _digest(risk_contract),
        "created_at": _now(),
        "control_authority": "NONE",
    }
    payload["evidence_sha256"] = _digest(payload)
    return payload


def _provider_wait_base(state_root: str | Path, project_id: str, gate_run_id: str) -> Path:
    return (Path(state_root).resolve() / "_workspace" / "provider-wait"
            / _safe_id(project_id, "project ID") / _safe_id(gate_run_id, "Gate run ID"))


def record_provider_wait_recovery_evidence(
    state_root: str | Path, **kwargs: Any,
) -> dict[str, Any]:
    evidence = build_provider_wait_recovery_evidence(**kwargs)
    base = _provider_wait_base(state_root, evidence["project_id"], evidence["gate_run_id"])
    if base.is_symlink():
        raise WaitRecoveryError("provider wait evidence root is unsafe")
    path = base / f"{evidence['lv_id']}.json"
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise WaitRecoveryError("provider wait evidence path is unsafe")
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != evidence:
            left = {k: v for k, v in existing.items() if k not in {"created_at", "evidence_sha256"}}
            right = {k: v for k, v in evidence.items() if k not in {"created_at", "evidence_sha256"}}
            if left != right:
                raise WaitRecoveryError("conflicting provider wait evidence already exists")
            evidence = existing
    else:
        base.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, evidence)
    pointer = {
        "schema_version": PROVIDER_WAIT_POINTER_SCHEMA,
        "project_id": evidence["project_id"], "gate_run_id": evidence["gate_run_id"],
        "lv_id": evidence["lv_id"], "evidence_file": path.name,
        "evidence_sha256": evidence["evidence_sha256"], "updated_at": _now(),
        "control_authority": "NONE",
    }
    pointer["pointer_sha256"] = _digest(pointer)
    atomic_write_json(base / "active.json", pointer)
    return evidence


def _validate_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(evidence)
    if value.get("schema_version") != PROVIDER_WAIT_EVIDENCE_SCHEMA:
        raise WaitRecoveryError("provider wait evidence schema mismatch")
    expected = str(value.get("evidence_sha256") or "")
    unsigned = {k: v for k, v in value.items() if k != "evidence_sha256"}
    if expected != _digest(unsigned):
        raise WaitRecoveryError("provider wait evidence digest mismatch")
    request = router_request_from_mapping(value.get("router_request") or {})
    if request.request_digest != value.get("router_request_sha256"):
        raise WaitRecoveryError("provider wait Router request binding mismatch")
    if route_request(request).to_dict() != value.get("router_decision"):
        raise WaitRecoveryError("provider wait Router decision binding mismatch")
    for name in ("output_contract", "validation_contract", "risk_contract"):
        if _digest(value.get(name) or {}) != value.get(f"{name}_sha256"):
            raise WaitRecoveryError(f"provider wait {name} binding mismatch")
    return value


def load_active_provider_wait_recovery_evidence(
    state_root: str | Path, *, project_id: str, gate_run_id: str,
) -> dict[str, Any] | None:
    base = _provider_wait_base(state_root, project_id, gate_run_id)
    pointer_path = base / "active.json"
    if not pointer_path.exists():
        return None
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise WaitRecoveryError("provider wait pointer is unsafe")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if not isinstance(pointer, dict) or pointer.get("schema_version") != PROVIDER_WAIT_POINTER_SCHEMA:
        raise WaitRecoveryError("provider wait pointer schema mismatch")
    expected = str(pointer.get("pointer_sha256") or "")
    unsigned = {k: v for k, v in pointer.items() if k != "pointer_sha256"}
    if expected != _digest(unsigned):
        raise WaitRecoveryError("provider wait pointer digest mismatch")
    name = str(pointer.get("evidence_file") or "")
    if not name or Path(name).name != name:
        raise WaitRecoveryError("provider wait pointer path is invalid")
    path = base / name
    if path.is_symlink() or not path.is_file():
        raise WaitRecoveryError("provider wait evidence is missing or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    validated = _validate_evidence(value)
    if validated["evidence_sha256"] != pointer.get("evidence_sha256"):
        raise WaitRecoveryError("provider wait pointer/evidence mismatch")
    return validated


def evaluate_provider_wait_recovery(
    evidence: Mapping[str, Any], *, fresh_snapshot: ProviderEligibilitySnapshotV1,
    current_head: str,
) -> ProviderWaitRecoveryDecision:
    value = _validate_evidence(evidence)
    original = router_request_from_mapping(value["router_request"])
    if str(current_head) != str(value["source_head"]):
        return ProviderWaitRecoveryDecision(
            False, "SOURCE_HEAD_DRIFT", original.request_digest, "",
            str(value["output_contract_sha256"]), str(value["validation_contract_sha256"]),
            str(value["risk_contract_sha256"]), {},
        )
    fresh = replace(
        original,
        eligibility_snapshot=fresh_snapshot,
        eligibility_snapshot_ref=fresh_snapshot.snapshot_id,
        eligibility_snapshot_digest=fresh_snapshot.snapshot_digest,
    )
    decision = route_request(fresh)
    return ProviderWaitRecoveryDecision(
        bool(decision.eligible),
        "PROVIDER_RECOVERED" if decision.eligible else "PROVIDER_STILL_UNAVAILABLE",
        original.request_digest, fresh.request_digest,
        str(value["output_contract_sha256"]), str(value["validation_contract_sha256"]),
        str(value["risk_contract_sha256"]), decision.to_dict(),
    )


def evaluate_resource_wait_recovery(
    state: Mapping[str, Any], *, resources_ok: bool,
    expected_state_sha256: str, expected_epoch: int,
) -> ResourceWaitRecoveryDecision:
    assessment = classify_wait_recovery(state)
    if assessment.owner != "RESOURCE_RECOVERY":
        return ResourceWaitRecoveryDecision(False, "NOT_RESOURCE_RECOVERY", str(state.get("state_sha256") or ""), int(state.get("epoch", 0)))
    state_sha = str(state.get("state_sha256") or "")
    epoch = int(state.get("epoch", 0))
    if state_sha != str(expected_state_sha256) or epoch != int(expected_epoch):
        return ResourceWaitRecoveryDecision(False, "STATE_CAS_MISMATCH", state_sha, epoch)
    if not resources_ok:
        return ResourceWaitRecoveryDecision(False, "RESOURCE_STILL_CONSTRAINED", state_sha, epoch)
    return ResourceWaitRecoveryDecision(True, "RESOURCE_RECOVERED", state_sha, epoch)
