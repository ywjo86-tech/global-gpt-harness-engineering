from __future__ import annotations

import copy
from pathlib import Path

from poc.graphify import decision, decision_closure

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "poc" / "graphify" / "config" / "decision_policy.yaml"


def comparative_report() -> dict:
    return {
        "metrics": {
            "graphify": {
                "verified_rate": 1.0,
                "verified_count": 4,
                "average_latency_ms": 12.0,
            },
            "existing_inspection": {
                "verified_rate": 0.75,
                "verified_count": 3,
                "average_latency_ms": 8.0,
            },
        },
        "rows": [],
    }


def _decision_evidence() -> dict:
    return {
        "fallback_pass": True,
        "backend_independence": True,
        "phase_boundary": True,
        "current_repository_boundary": True,
        "memory_independence": True,
        "source_precedence": True,
        "context_assembly_boundary": True,
        "reserved_phase_isolation": True,
        "core_regression_pass": True,
        "evidence_refs": ["fixture://graphify/evidence"],
    }


def independent_review() -> dict:
    return {
        "review_status": "PASS",
        "core_regression_status": "PASS",
        "waivers_used": False,
    }


def reserved_phase_isolation() -> dict:
    return {"verified": True}


def open_decision() -> dict:
    return decision.evaluate_decision(
        comparative_report(),
        _decision_evidence(),
        policy_path=POLICY_PATH,
        predecessor_baseline_ref="fixture-baseline",
        source_reverification_ref="fixture-source",
        graphify_version="fixture-version",
    )


def closed_decision_and_closure() -> tuple[dict, dict]:
    open_record = open_decision()
    closure = decision_closure.finalize_decision_closure(
        open_record,
        independent_review(),
        reserved_phase_isolation(),
    )
    if closure["state"] != decision_closure.CLOSED_STATE:
        raise AssertionError(f"invalid Graphify fixture closure: {closure['reasons']}")
    closed_record = copy.deepcopy(open_record)
    closed_record["closure_state"] = decision_closure.CLOSED_STATE
    return closed_record, closure


def gate009() -> dict:
    return {"gate_status": "GO"}


def evidence_index() -> dict[str, str]:
    keys = (
        "decision_record",
        "decision_closure",
        "backend_independence",
        "phase_boundary",
        "current_repository_boundary",
        "memory_independence",
        "source_precedence",
        "context_boundary",
        "reserved_phase_isolation",
        "independent_regression_review",
        "fallback_evidence",
        "comparative_report",
    )
    return {key: f"fixture://graphify/{key}" for key in keys}
