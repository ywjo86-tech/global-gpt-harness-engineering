from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DECISION_POLICY_VERSION = "DPOL-1"


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evaluate_decision(
    comparative_report: dict[str, Any],
    evidence: dict[str, Any],
    *,
    policy_path: str | Path,
    predecessor_baseline_ref: str,
    source_reverification_ref: str,
    graphify_version: str,
) -> dict[str, Any]:
    metrics = comparative_report.get("metrics", {})
    graphify_metrics = metrics.get("graphify", {})
    baseline_metrics = metrics.get("existing_inspection", {})
    rows = comparative_report.get("rows", [])
    zero_writes = all(
        not bool((row.get("result") or {}).get("write_performed", False)) for row in rows
    )
    hard_checks = {
        "zero_provider_writes": zero_writes,
        "fallback_pass": bool(evidence.get("fallback_pass")),
        "backend_independence": bool(evidence.get("backend_independence")),
        "phase_boundary": bool(evidence.get("phase_boundary")),
        "current_repository_boundary": bool(evidence.get("current_repository_boundary")),
        "memory_independence": bool(evidence.get("memory_independence")),
        "source_precedence": bool(evidence.get("source_precedence")),
        "context_assembly_boundary": bool(evidence.get("context_assembly_boundary")),
        "reserved_phase_isolation": bool(evidence.get("reserved_phase_isolation")),
        "core_regression_pass": bool(evidence.get("core_regression_pass")),
    }
    all_hard_pass = all(hard_checks.values())
    graphify_rate = float(graphify_metrics.get("verified_rate", 0.0))
    graphify_count = int(graphify_metrics.get("verified_count", 0))
    baseline_count = int(baseline_metrics.get("verified_count", 0))
    material_benefit = graphify_rate >= 0.75 and graphify_count > baseline_count

    conditions: list[str] = []
    if not all_hard_pass:
        decision = "NO_GO"
        conditions.append("hard_safety_or_regression_failure")
    elif material_benefit:
        decision = "GO"
    elif graphify_count == baseline_count:
        decision = "CONDITIONAL_GO"
        conditions.append("no_verified-count_advantage_observed")
    else:
        decision = "NO_GO"
        conditions.append("material_benefit_threshold_not_met")

    policy_file = Path(policy_path)
    policy_digest = hashlib.sha256(policy_file.read_bytes()).hexdigest()
    evidence_refs = list(evidence.get("evidence_refs", []))
    record = {
        "record_type": "DecisionRecord",
        "decision": decision,
        "predecessor_stable_baseline_ref": predecessor_baseline_ref,
        "source_reverification_ref": source_reverification_ref,
        "graphify_version_qualified": graphify_version,
        "policy_version": DECISION_POLICY_VERSION,
        "policy_digest": policy_digest,
        "safety_gate_results": hard_checks,
        "comparative_metric_summary": metrics,
        "canonical_verification_summary": {
            "graphify_verified_rate": graphify_rate,
            "graphify_verified_count": graphify_count,
            "baseline_verified_count": baseline_count,
            "material_benefit": material_benefit,
        },
        "backend_independence_result_ref": str(evidence.get("backend_independence_ref", "")),
        "current_repository_intelligence_boundary_ref": str(evidence.get("current_repository_boundary_ref", "")),
        "memory_independence_result_ref": str(evidence.get("memory_independence_ref", "")),
        "source_precedence_result_ref": str(evidence.get("source_precedence_ref", "")),
        "context_assembly_boundary_result_ref": str(evidence.get("context_assembly_boundary_ref", "")),
        "conditions": conditions,
        "fallback_status": "PASS" if hard_checks["fallback_pass"] else "FAIL",
        "evidence_refs": evidence_refs,
        "decision_finalized": True,
        "closure_state": None,
        "next_master_phase": "PHASE_3_EXECUTION_BACKEND_CONTRACT_FINALIZATION",
    }
    record["decision_digest"] = _digest({
        "decision": record["decision"],
        "policy_digest": record["policy_digest"],
        "comparative_metric_summary": record["comparative_metric_summary"],
        "safety_gate_results": record["safety_gate_results"],
        "conditions": record["conditions"],
    })
    return record
