from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ALLOWED_DECISIONS = {"GO", "CONDITIONAL_GO", "NO_GO"}
CLOSED_STATE = "GRAPHIFY_DECISION_CLOSED"
NEXT_MASTER_PHASE = "PHASE_3_EXECUTION_BACKEND_CONTRACT_FINALIZATION"


def _decision_digest(record: dict[str, Any]) -> str:
    payload = {
        "decision": record.get("decision"),
        "policy_digest": record.get("policy_digest"),
        "comparative_metric_summary": record.get("comparative_metric_summary"),
        "safety_gate_results": record.get("safety_gate_results"),
        "conditions": record.get("conditions"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finalize_decision_closure(
    decision_record: dict[str, Any],
    independent_review: dict[str, Any],
    reserved_phase_isolation: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    decision = str(decision_record.get("decision", ""))
    if decision not in ALLOWED_DECISIONS:
        reasons.append("decision_outcome_invalid_or_ambiguous")
    if decision_record.get("decision_finalized") is not True:
        reasons.append("decision_not_finalized")
    if decision_record.get("closure_state") not in {None, ""}:
        reasons.append("decision_already_closed_or_mutated")
    if decision_record.get("next_master_phase") != NEXT_MASTER_PHASE:
        reasons.append("next_master_phase_mismatch")

    observed_digest = str(decision_record.get("decision_digest", ""))
    recomputed_digest = _decision_digest(decision_record)
    if not observed_digest or observed_digest != recomputed_digest:
        reasons.append("decision_digest_mismatch")
    if independent_review.get("review_status") != "PASS":
        reasons.append("independent_review_not_pass")
    if independent_review.get("core_regression_status") != "PASS":
        reasons.append("core_regression_not_pass")
    if independent_review.get("waivers_used") is not False:
        reasons.append("regression_waiver_present")
    if reserved_phase_isolation.get("verified") is not True:
        reasons.append("reserved_phase_isolation_not_verified")
    closed = not reasons
    record = {
        "record_type": "GraphifyDecisionClosureRecord",
        "state": CLOSED_STATE if closed else "CLOSURE_BLOCKED",
        "decision": decision,
        "decision_digest": observed_digest,
        "decision_digest_recomputed": recomputed_digest,
        "decision_outcome_unchanged": bool(closed and observed_digest == recomputed_digest),
        "independent_review_status": independent_review.get("review_status"),
        "core_regression_status": independent_review.get("core_regression_status"),
        "reserved_phase_isolation_verified": reserved_phase_isolation.get("verified") is True,
        "next_master_phase": NEXT_MASTER_PHASE,
        "closure_eligible": closed,
        "reasons": reasons,
    }
    return record


def write_closure_record(path: str | Path, record: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
