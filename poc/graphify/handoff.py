from __future__ import annotations

from typing import Any

from .decision_closure import CLOSED_STATE, NEXT_MASTER_PHASE

FORBIDDEN_DEPENDENCIES = ["Memory Adapter", "Obsidian", "Notion"]
FORBIDDEN_PHASE_IMPLEMENTATIONS = [
    "PHASE_3_EXECUTION_BACKEND_CONTRACT_IMPLEMENTATION",
    "PHASE_4_FULL_MCP_IMPLEMENTATION",
    "PHASE_5_AI_OFFICE_IMPLEMENTATION",
    "PHASE_6_PROJECT_CONTINUITY_MEMORY_IMPLEMENTATION",
    "PHASE_7_PROVIDER_RUNTIME_EXPANSION",
    "PHASE_8_INSTRUCTION_GOVERNANCE_RUNTIME",
]


def build_phase3_handoff(
    decision_record: dict[str, Any],
    closure_record: dict[str, Any],
    *,
    evidence_index: dict[str, str],
    comparative_metrics: dict[str, Any],
) -> dict[str, Any]:
    if decision_record.get("closure_state") != CLOSED_STATE:
        raise ValueError("decision is not closed")
    if closure_record.get("state") != CLOSED_STATE:
        raise ValueError("closure record is not closed")
    if decision_record.get("decision_digest") != closure_record.get("decision_digest"):
        raise ValueError("decision digest changed during closure")
    decision = str(decision_record.get("decision", ""))
    recommended = "graphify_optional_sidecar" if decision in {"GO", "CONDITIONAL_GO"} else "existing_inspection_only"
    graphify_metrics = comparative_metrics.get("graphify", {})
    baseline_metrics = comparative_metrics.get("existing_inspection", {})
    return {
        "record_type": "Phase3HandoffPackage",
        "decision_record_ref": evidence_index.get("decision_record", ""),
        "graphify_decision_closure_ref": evidence_index.get("decision_closure", ""),
        "decision": decision,
        "decision_digest": decision_record.get("decision_digest"),
        "recommended_repository_intelligence_provider": recommended,
        "fallback_provider": "existing_inspection",
        "mandatory_canonical_verification_rule": (
            "Material Graphify claims must be revalidated against the current repository "
            "and matching source_ref before authority-bearing use."
        ),
        "backend_independence_result_ref": evidence_index.get("backend_independence", ""),
        "memory_independence_result_ref": evidence_index.get("memory_independence", ""),
        "source_precedence_result_ref": evidence_index.get("source_precedence", ""),
        "context_assembly_boundary_result_ref": evidence_index.get("context_boundary", ""),
        "reserved_phase_isolation_ref": evidence_index.get("reserved_phase_isolation", ""),
        "forbidden_dependencies": list(FORBIDDEN_DEPENDENCIES),
        "source_of_truth_precedence": (
            "Current Repository > Approved Baseline > lower-priority memory/view assertions"
        ),
        "permitted_use_cases": [
            "repository structure investigation",
            "symbol/reference/path/neighbor investigation",
            "dependency and change-impact investigation",
            "freshness/confidence-assisted investigation",
        ],
        "restrictions": [
            "Graphify is not governance, approval, completion, release, or execution authority.",
            "Graphify must remain optional; Existing Inspection fallback is mandatory.",
            "No direct Memory Adapter, Obsidian, or Notion dependency.",
            "No Memory Capture/Retrieval/Merge/Injection or Context Assembly ownership.",
            "No Execution Backend, Full MCP, AI Office, Jarvis, PHASE 6, PHASE 7, or PHASE 8 implementation in this handoff.",
            "PoC transport remains local-only; shared HTTP is not approved.",
        ],
        "production_policy_prerequisites": [
            "GATE-005 must decide commit|ignore|local-only before production graph artifact adoption.",
            "Exact Graphify version changes require requalification.",
            "Production adoption requires a fresh canonical/source-revision check.",
        ],
        "production_adoption_allowed": False,
        "current_artifact_policy": "LOCAL_ONLY_POC",
        "unresolved_limitations": [
            f"Graphify average scenario latency observed: {graphify_metrics.get('average_latency_ms')} ms.",
            f"Existing Inspection average scenario latency observed: {baseline_metrics.get('average_latency_ms')} ms.",
            "Initial PoC is code-only; documents, papers, images, and external semantic backends were excluded.",
            "Graph output is disposable and must be refreshed when repository/source revision changes.",
        ],
        "evidence_index": dict(evidence_index),
        "master_phase_order_assertion": (
            "FULL_PLAN_STABLE -> GRAPHIFY_DECISION_CLOSED -> "
            "PHASE_3_EXECUTION_BACKEND_CONTRACT_FINALIZATION"
        ),
        "next_master_phase": NEXT_MASTER_PHASE,
        "graphify_authority_statement": "Graphify is a non-authoritative optional Repository Intelligence sidecar.",
        "no_future_phase_implementation_statement": (
            "This package contains no implementation of PHASE 3, 4, 5, 6, 7, or 8."
        ),
        "forbidden_phase_implementations": list(FORBIDDEN_PHASE_IMPLEMENTATIONS),
    }


def evaluate_gate006(
    handoff: dict[str, Any], gate009: dict[str, Any]
) -> dict[str, Any]:
    reasons: list[str] = []
    if gate009.get("gate_status") != "GO":
        reasons.append("gate009_not_go")
    if handoff.get("next_master_phase") != NEXT_MASTER_PHASE:
        reasons.append("next_master_phase_mismatch")
    if handoff.get("fallback_provider") != "existing_inspection":
        reasons.append("fallback_provider_missing")
    if handoff.get("production_adoption_allowed") is not False:
        reasons.append("production_policy_bypass")
    if set(handoff.get("forbidden_dependencies", [])) != set(FORBIDDEN_DEPENDENCIES):
        reasons.append("forbidden_dependency_boundary_incomplete")

    evidence = handoff.get("evidence_index") or {}
    required_evidence = {
        "decision_record", "decision_closure", "backend_independence",
        "phase_boundary", "current_repository_boundary", "memory_independence",
        "source_precedence", "context_boundary", "reserved_phase_isolation",
        "independent_regression_review", "fallback_evidence", "comparative_report",
    }
    missing = sorted(key for key in required_evidence if not evidence.get(key))
    if missing:
        reasons.append("missing_evidence:" + ",".join(missing))
    if "non-authoritative" not in str(handoff.get("graphify_authority_statement", "")):
        reasons.append("graphify_non_authority_statement_missing")
    if "no implementation of PHASE 3, 4, 5, 6, 7, or 8" not in str(
        handoff.get("no_future_phase_implementation_statement", "")
    ):
        reasons.append("future_phase_nonimplementation_statement_missing")

    return {
        "record_type": "GraphifyGateRecord",
        "gate_id": "GATE-006",
        "gate_status": "GO" if not reasons else "NO_GO",
        "next_master_phase": handoff.get("next_master_phase"),
        "phase3_handoff_ready": not reasons,
        "production_adoption_allowed": handoff.get("production_adoption_allowed"),
        "bypass_used": False,
        "reasons": reasons,
    }
