from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

HEX = set("0123456789abcdef")
GATE_ORDER = tuple(f"GATE-{n:03d}" for n in range(1, 7))
OFFICIAL_EXIT_NAMES = (
    "Contract Conformance", "Filesystem", "Shell", "Git", "Test / Build", "Security",
    "Audit", "Failure Handling", "Restore", "Structured Observability Compatibility",
    "Contract-only Handoff Compatibility", "E2E Execution",
)
GATE_POLICIES = {
    "GATE-001": {"prerequisites": (), "prerequisite_evidence": (), "current_evidence": ("EVD-001", "EVD-002", "EVD-003"), "official": ()},
    "GATE-002": {"prerequisites": ("GATE-001",), "prerequisite_evidence": ("EVD-001", "EVD-002", "EVD-003"), "current_evidence": tuple(f"EVD-{n:03d}" for n in range(4, 9)), "official": ("Contract Conformance", "Filesystem", "Shell", "Git", "Test / Build")},
    "GATE-003": {"prerequisites": ("GATE-001", "GATE-002"), "prerequisite_evidence": tuple(f"EVD-{n:03d}" for n in range(1, 9)), "current_evidence": ("EVD-009", "EVD-010", "EVD-011", "EVD-012", "EVD-013", "EVD-016"), "official": ("Security",)},
    "GATE-004": {"prerequisites": ("GATE-001", "GATE-002", "GATE-003"), "prerequisite_evidence": ("EVD-004", "EVD-007", "EVD-011", "EVD-012", "EVD-013", "EVD-016"), "current_evidence": ("EVD-014",), "official": ("Audit", "Failure Handling", "Structured Observability Compatibility", "Contract-only Handoff Compatibility")},
    "GATE-005": {"prerequisites": ("GATE-001", "GATE-002", "GATE-003", "GATE-004"), "prerequisite_evidence": ("EVD-013", "EVD-016"), "current_evidence": ("EVD-015", "EVD-017", "EVD-018", "EVD-021"), "official": OFFICIAL_EXIT_NAMES},
    "GATE-006": {"prerequisites": ("GATE-001", "GATE-002", "GATE-003", "GATE-004", "GATE-005"), "prerequisite_evidence": tuple([f"EVD-{n:03d}" for n in range(1, 19)] + ["EVD-021"]), "current_evidence": ("EVD-019", "EVD-020"), "official": OFFICIAL_EXIT_NAMES},
}


def required_evidence_for_gate(gate_id: str) -> tuple[str, ...]:
    policy = GATE_POLICIES[gate_id]
    return tuple(dict.fromkeys(policy["prerequisite_evidence"] + policy["current_evidence"]))
REQUIRED_FIELDS = {
    "gch.full-mcp.workspace-state.v1": ("schema_version", "head_sha", "approved_target_manifest_sha256", "tracked_diff_sha256", "untracked_owned_manifest_sha256", "unauthorized_change_manifest_sha256", "unauthorized_change_count", "captured_at_utc", "state_digest"),
    "gch.full-mcp.validation-result.v1": ("schema_version", "project_id", "run_id", "attempt", "test_id", "consumer_task_id", "producer_task_id", "test_contract_digest", "profile_id", "profile_digest", "selector_digest", "started_at_utc", "ended_at_utc", "verdict", "exit_status_category", "assertion_summary_digest", "audit_ref", "audit_digest", "source_snapshot", "result_digest"),
    "gch.full-mcp.evidence.v2": ("schema_version", "evidence_id", "project_id", "run_id", "origin_gate_id", "attempt", "requirement_refs", "task_refs", "test_refs", "producer_task_id", "validation_result_refs", "artifact_refs", "verdict", "collected_at_utc", "source_binding", "record_digest"),
    "gch.full-mcp.selection-index.v1": ("schema_version", "project_id", "run_id", "attempt", "index_scope", "workspace_state_ref", "workspace_state_digest", "evidence_entries", "prerequisite_gate_refs", "review_refs", "generated_at_utc", "index_digest"),
    "gch.full-mcp.review.v1": ("schema_version", "project_id", "run_id", "attempt", "gate_id", "review_role", "reviewer_authority", "selection_index_ref", "selection_index_digest", "finding_refs", "finding_counts", "reviewed_at_utc", "record_digest"),
    "gch.full-mcp.gate-decision.v2": ("schema_version", "gate_id", "project_id", "run_id", "attempt", "decision", "required_evidence", "evidence_digests", "prerequisite_gate_states", "official_acceptance_results", "review_ref", "review_digest", "blocker_count", "major_count", "source_binding", "selection_index_ref", "selection_index_digest", "evaluated_at_utc", "record_digest"),
    "gch.full-mcp.official-exit-gates.v1": ("schema_version", "project_id", "run_id", "attempt", "source_gate_ref", "source_gate_digest", "rows", "generated_at_utc", "record_digest"),
    "gch.full-mcp.phase5-handoff.v1": ("schema_version", "project_id", "run_id", "attempt", "execution_contract", "execution_mode", "provider_selection_authority", "approved_plan_ref", "design_ref", "dependency_lock_sha256", "pre_final_index_ref", "pre_final_index_digest", "official_exit_ref", "official_exit_digest", "evd019_ref", "evd019_digest", "prerequisite_gate_refs", "workspace_state_ref", "workspace_state_digest", "handoff_status", "generated_at_utc", "record_digest"),
    "gch.full-mcp.stable-baseline-manifest.v1": ("schema_version", "project_id", "run_id", "attempt", "gate6_ref", "gate6_digest", "gate6_index_ref", "gate6_index_digest", "official_exit_ref", "official_exit_digest", "phase5_handoff_ref", "phase5_handoff_digest", "dependency_lock_sha256", "workspace_state_ref", "workspace_state_digest", "eligibility_status", "declaration_status", "generated_at_utc", "record_digest"),
}
DIGEST_FIELDS = {
    "gch.full-mcp.validation-result.v1": "result_digest",
    "gch.full-mcp.evidence.v2": "record_digest",
    "gch.full-mcp.selection-index.v1": "index_digest",
    "gch.full-mcp.review.v1": "record_digest",
    "gch.full-mcp.gate-decision.v2": "record_digest",
    "gch.full-mcp.official-exit-gates.v1": "record_digest",
    "gch.full-mcp.phase5-handoff.v1": "record_digest",
    "gch.full-mcp.stable-baseline-manifest.v1": "record_digest",
}
class QualificationError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def is_git_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and set(value) <= HEX


def _require(record: Mapping[str, Any], schema: str) -> None:
    missing = [name for name in REQUIRED_FIELDS[schema] if name not in record]
    if missing:
        raise QualificationError(f"missing fields for {schema}: {','.join(missing)}")
    if record.get("schema_version") != schema:
        raise QualificationError(f"schema_version mismatch: expected {schema}")


def seal_digest(record: Mapping[str, Any], digest_field: str) -> dict[str, Any]:
    out = dict(record)
    out.pop(digest_field, None)
    out[digest_field] = canonical_sha256(out)
    return out


def validate_digest(record: Mapping[str, Any], digest_field: str) -> None:
    actual = record.get(digest_field)
    if not is_sha256(actual):
        raise QualificationError(f"invalid {digest_field}")
    body = dict(record)
    body.pop(digest_field, None)
    if canonical_sha256(body) != actual:
        raise QualificationError(f"{digest_field} mismatch")
def workspace_state_digest(record: Mapping[str, Any]) -> str:
    keys = (
        "head_sha", "approved_target_manifest_sha256", "tracked_diff_sha256",
        "untracked_owned_manifest_sha256", "unauthorized_change_manifest_sha256",
        "unauthorized_change_count",
    )
    return canonical_sha256({key: record[key] for key in keys})


def validate_workspace_state(record: Mapping[str, Any]) -> None:
    schema = "gch.full-mcp.workspace-state.v1"
    _require(record, schema)
    for key in ("approved_target_manifest_sha256", "tracked_diff_sha256", "untracked_owned_manifest_sha256", "unauthorized_change_manifest_sha256", "state_digest"):
        if not is_sha256(record[key]):
            raise QualificationError(f"invalid workspace digest: {key}")
    if not is_git_sha(record["head_sha"]):
        raise QualificationError("invalid workspace head_sha")
    if not isinstance(record["unauthorized_change_count"], int) or record["unauthorized_change_count"] < 0:
        raise QualificationError("invalid unauthorized_change_count")
    if workspace_state_digest(record) != record["state_digest"]:
        raise QualificationError("state_digest mismatch")


def source_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    body = {
        "source_set_name": snapshot["source_set_name"],
        "files": snapshot["files"],
        "artifact_inputs": snapshot["artifact_inputs"],
    }
    return canonical_sha256(body)


def validate_source_snapshot(snapshot: Mapping[str, Any]) -> None:
    for key in ("source_set_name", "files", "artifact_inputs", "snapshot_digest"):
        if key not in snapshot:
            raise QualificationError(f"source_snapshot missing {key}")
    paths = [entry.get("path") for entry in snapshot["files"]]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise QualificationError("source_snapshot files must be unique lexicographic paths")
    for entry in snapshot["files"]:
        if set(("path", "sha256", "mode")) - set(entry):
            raise QualificationError("invalid source file entry")
        if not is_sha256(entry["sha256"]):
            raise QualificationError("invalid source file sha256")
    for entry in snapshot["artifact_inputs"]:
        if set(("kind", "relative_path_or_authority_ref", "digest")) - set(entry):
            raise QualificationError("invalid artifact input")
        if not is_sha256(entry["digest"]):
            raise QualificationError("invalid artifact input digest")
    if source_snapshot_digest(snapshot) != snapshot["snapshot_digest"]:
        raise QualificationError("source_snapshot digest mismatch")
def validate_validation_result(record: Mapping[str, Any]) -> None:
    schema = "gch.full-mcp.validation-result.v1"
    _require(record, schema)
    if record["verdict"] not in {"PASS", "FAIL", "BLOCKED"}:
        raise QualificationError("invalid validation verdict")
    if not isinstance(record["attempt"], int) or record["attempt"] < 1:
        raise QualificationError("invalid validation attempt")
    if (record["profile_id"] is None) != (record["profile_digest"] is None):
        raise QualificationError("profile id/digest nullability mismatch")
    for key in ("test_contract_digest", "selector_digest", "assertion_summary_digest", "audit_digest"):
        if not is_sha256(record[key]):
            raise QualificationError(f"invalid validation digest: {key}")
    if record["profile_digest"] is not None and not is_sha256(record["profile_digest"]):
        raise QualificationError("invalid profile_digest")
    validate_source_snapshot(record["source_snapshot"])
    validate_digest(record, "result_digest")


def validation_result_fresh(
    record: Mapping[str, Any],
    current_file_digests: Mapping[str, str],
    current_artifact_digests: Mapping[str, str],
) -> bool:
    validate_validation_result(record)
    snapshot = record["source_snapshot"]
    for entry in snapshot["files"]:
        if current_file_digests.get(entry["path"]) != entry["sha256"]:
            return False
    for entry in snapshot["artifact_inputs"]:
        ref = entry["relative_path_or_authority_ref"]
        if current_artifact_digests.get(ref) != entry["digest"]:
            return False
    return True


def _validate_source_binding(binding: Mapping[str, Any]) -> None:
    required = ("head_sha", "origin_main_sha", "phase3_sealed_sha", "dependency_lock_sha256", "invocation_context_id", "workspace_state_digest")
    missing = [key for key in required if key not in binding]
    if missing:
        raise QualificationError(f"source_binding missing: {','.join(missing)}")
    for key in ("head_sha", "origin_main_sha", "phase3_sealed_sha"):
        if not is_git_sha(binding[key]):
            raise QualificationError(f"invalid source_binding git sha: {key}")
    for key in ("dependency_lock_sha256", "workspace_state_digest"):
        if not is_sha256(binding[key]):
            raise QualificationError(f"invalid source_binding digest: {key}")
    if not isinstance(binding["invocation_context_id"], str) or not binding["invocation_context_id"]:
        raise QualificationError("invalid invocation_context_id")
def validate_evidence(record: Mapping[str, Any]) -> None:
    schema = "gch.full-mcp.evidence.v2"
    _require(record, schema)
    if record["verdict"] not in {"PASS", "FAIL", "BLOCKED"}:
        raise QualificationError("invalid evidence verdict")
    if record["origin_gate_id"] not in GATE_ORDER:
        raise QualificationError("invalid origin_gate_id")
    result_tests = {entry.get("test_id") for entry in record["validation_result_refs"]}
    if not set(record["test_refs"]) <= result_tests:
        raise QualificationError("each test_ref requires designated ValidationResult proof")
    for entry in record["validation_result_refs"]:
        required = {"test_id", "source_attempt", "consumer_task_id", "relative_path", "result_digest"}
        if required - set(entry) or not is_sha256(entry["result_digest"]):
            raise QualificationError("invalid validation_result_ref")
    for entry in record["artifact_refs"]:
        required = {"kind", "source_attempt", "relative_path_or_authority_ref", "digest"}
        if required - set(entry) or not is_sha256(entry["digest"]):
            raise QualificationError("invalid evidence artifact_ref")
    _validate_source_binding(record["source_binding"])
    validate_digest(record, "record_digest")


def evidence_fresh(
    record: Mapping[str, Any],
    validation_results_by_path: Mapping[str, Mapping[str, Any]],
    current_file_digests: Mapping[str, str],
    current_artifact_digests: Mapping[str, str],
) -> bool:
    validate_evidence(record)
    for ref in record["validation_result_refs"]:
        result = validation_results_by_path.get(ref["relative_path"])
        if result is None:
            return False
        if result.get("result_digest") != ref["result_digest"] or result.get("verdict") != "PASS":
            return False
        if result.get("project_id") != record.get("project_id") or result.get("run_id") != record.get("run_id"):
            return False
        if result.get("test_id") != ref["test_id"] or result.get("attempt") != ref["source_attempt"]:
            return False
        if result.get("consumer_task_id") != ref["consumer_task_id"]:
            return False
        if not validation_result_fresh(result, current_file_digests, current_artifact_digests):
            return False
    for ref in record["artifact_refs"]:
        key = ref["relative_path_or_authority_ref"]
        if current_artifact_digests.get(key) != ref["digest"]:
            return False
    return record["verdict"] == "PASS"


def validate_selection_index(record: Mapping[str, Any]) -> None:
    schema = "gch.full-mcp.selection-index.v1"
    _require(record, schema)
    if record["index_scope"] not in set(GATE_ORDER) | {"PREFINAL"}:
        raise QualificationError("invalid index_scope")
    ids = [entry.get("evidence_id") for entry in record["evidence_entries"]]
    if len(ids) != len(set(ids)):
        raise QualificationError("duplicate evidence selection")
    validate_digest(record, "index_digest")
def build_selection_index(
    *, project_id: str, run_id: str, attempt: int, index_scope: str,
    workspace_state_ref: str, workspace_state_digest: str,
    evidence_entries: Sequence[Mapping[str, Any]],
    prerequisite_gate_refs: Sequence[Mapping[str, Any]],
    review_refs: Sequence[Mapping[str, Any]], generated_at_utc: str,
) -> dict[str, Any]:
    record = {
        "schema_version": "gch.full-mcp.selection-index.v1",
        "project_id": project_id, "run_id": run_id, "attempt": attempt,
        "index_scope": index_scope, "workspace_state_ref": workspace_state_ref,
        "workspace_state_digest": workspace_state_digest,
        "evidence_entries": [dict(x) for x in evidence_entries],
        "prerequisite_gate_refs": [dict(x) for x in prerequisite_gate_refs],
        "review_refs": [dict(x) for x in review_refs],
        "generated_at_utc": generated_at_utc,
    }
    record = seal_digest(record, "index_digest")
    validate_selection_index(record)
    return record


def validate_review(record: Mapping[str, Any], findings_by_ref: Mapping[str, Mapping[str, Any]] | None = None) -> None:
    schema = "gch.full-mcp.review.v1"
    _require(record, schema)
    counts = record["finding_counts"]
    if set(counts) != {"blocker", "major", "minor"}:
        raise QualificationError("finding_counts must contain blocker/major/minor")
    if any(not isinstance(v, int) or v < 0 for v in counts.values()):
        raise QualificationError("invalid finding count")
    derived = {"blocker": 0, "major": 0, "minor": 0}
    resolvable = True
    for ref in record["finding_refs"]:
        finding = ref if isinstance(ref, Mapping) else (findings_by_ref or {}).get(str(ref))
        if finding is None or finding.get("severity") not in derived:
            resolvable = False
            break
        derived[finding["severity"]] += 1
    if record["finding_refs"] and not resolvable:
        raise QualificationError("finding_refs cannot be resolved to severities")
    if resolvable and derived != counts:
        raise QualificationError("finding_counts mismatch")
    validate_digest(record, "record_digest")


def validate_gate_decision(
    record: Mapping[str, Any], review: Mapping[str, Any] | None = None,
    index: Mapping[str, Any] | None = None,
) -> None:
    schema = "gch.full-mcp.gate-decision.v2"
    _require(record, schema)
    if record["gate_id"] not in GATE_ORDER or record["decision"] not in {"GO", "CONDITIONAL_GO", "NO_GO"}:
        raise QualificationError("invalid gate decision")
    if record["gate_id"] == "GATE-006" and record["decision"] == "CONDITIONAL_GO":
        raise QualificationError("GATE-006 cannot be CONDITIONAL_GO")
    official = record["official_acceptance_results"]
    if any(name not in OFFICIAL_EXIT_NAMES for name in official):
        raise QualificationError("unknown official acceptance name")
    if any(value not in {"PASS", "FAIL"} for value in official.values()):
        raise QualificationError("invalid official acceptance value")
    if record["gate_id"] in {"GATE-005", "GATE-006"} and set(official) != set(OFFICIAL_EXIT_NAMES):
        raise QualificationError("GATE-005/006 require complete official acceptance map")
    _validate_source_binding(record["source_binding"])
    if review is not None:
        validate_review(review)
        if record["review_digest"] != review["record_digest"]:
            raise QualificationError("gate review digest mismatch")
        if record["blocker_count"] != review["finding_counts"]["blocker"] or record["major_count"] != review["finding_counts"]["major"]:
            raise QualificationError("gate finding counts are not derived from review")
    if index is not None:
        validate_selection_index(index)
        if record["selection_index_digest"] != index["index_digest"]:
            raise QualificationError("selection index digest mismatch")
        if review is not None and (review.get("selection_index_digest") != index["index_digest"] or review.get("gate_id") != record["gate_id"]):
            raise QualificationError("review/index/gate binding mismatch")
        selected = {x["evidence_id"] for x in index["evidence_entries"]}
        if not set(record["required_evidence"]) <= selected:
            raise QualificationError("required evidence not selected")
    validate_digest(record, "record_digest")


def validate_official_exit(record: Mapping[str, Any], source_gate: Mapping[str, Any] | None = None) -> None:
    schema = "gch.full-mcp.official-exit-gates.v1"
    _require(record, schema)
    names = tuple(row.get("name") for row in record["rows"])
    if names != OFFICIAL_EXIT_NAMES:
        raise QualificationError("official exit rows/order mismatch")
    if any(row.get("result") not in {"PASS", "FAIL"} for row in record["rows"]):
        raise QualificationError("invalid official exit result")
    if source_gate is not None:
        validate_gate_decision(source_gate)
        if source_gate["gate_id"] != "GATE-005" or source_gate["decision"] != "GO":
            raise QualificationError("official exit source must be GATE-005 GO")
        if record["source_gate_digest"] != source_gate["record_digest"]:
            raise QualificationError("official exit source gate digest mismatch")
        expected = source_gate["official_acceptance_results"]
        if {row["name"]: row["result"] for row in record["rows"]} != expected:
            raise QualificationError("official exit/source gate result mismatch")
    validate_digest(record, "record_digest")


def validate_phase5_handoff(record: Mapping[str, Any]) -> None:
    schema = "gch.full-mcp.phase5-handoff.v1"
    _require(record, schema)
    if record["handoff_status"] != "CANDIDATE_NOT_AUTHORIZED":
        raise QualificationError("invalid phase5 handoff status")
    validate_digest(record, "record_digest")


def validate_stable_baseline_manifest(record: Mapping[str, Any], gate6: Mapping[str, Any] | None = None) -> None:
    schema = "gch.full-mcp.stable-baseline-manifest.v1"
    _require(record, schema)
    if record["eligibility_status"] != "ELIGIBLE" or record["declaration_status"] != "NOT_DECLARED":
        raise QualificationError("stable baseline manifest status mismatch")
    if gate6 is not None:
        validate_gate_decision(gate6)
        if gate6["gate_id"] != "GATE-006" or gate6["decision"] != "GO" or record["gate6_digest"] != gate6["record_digest"]:
            raise QualificationError("stable baseline requires bound GATE-006 GO")
    validate_digest(record, "record_digest")
def evaluate_gate(
    *, gate_id: str, project_id: str, run_id: str, attempt: int,
    index: Mapping[str, Any], review: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    prerequisite_gates: Mapping[str, Mapping[str, Any]],
    official_acceptance_results: Mapping[str, str], source_binding: Mapping[str, Any],
    review_ref: str, selection_index_ref: str, evaluated_at_utc: str,
    validation_results_by_path: Mapping[str, Mapping[str, Any]],
    current_file_digests: Mapping[str, str],
    current_artifact_digests: Mapping[str, str],
    workspace_state: Mapping[str, Any] | None = None,
    non_material_remediation_pending: bool = False,
) -> dict[str, Any]:
    if gate_id not in GATE_POLICIES:
        raise QualificationError("unknown gate")
    validate_selection_index(index)
    validate_review(review)
    policy = GATE_POLICIES[gate_id]
    required_evidence = required_evidence_for_gate(gate_id)
    selected = {entry["evidence_id"]: entry for entry in index["evidence_entries"]}
    proof_ok = True
    for evidence_id in required_evidence:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None or evidence_id not in selected:
            proof_ok = False
            continue
        validate_evidence(evidence)
        if evidence["verdict"] != "PASS" or selected[evidence_id]["record_digest"] != evidence["record_digest"]:
            proof_ok = False
            continue
        if not evidence_fresh(
            evidence, validation_results_by_path, current_file_digests, current_artifact_digests
        ):
            proof_ok = False
    prereq_states = {}
    for prereq_id in policy["prerequisites"]:
        gate = prerequisite_gates.get(prereq_id)
        prereq_states[prereq_id] = None if gate is None else gate.get("decision")
        if gate is None:
            proof_ok = False
            continue
        validate_gate_decision(gate)
        if gate["decision"] != "GO":
            proof_ok = False
    official = dict(official_acceptance_results)
    if any(value not in {"PASS", "FAIL"} for value in official.values()):
        raise QualificationError("invalid official result")
    for name in policy["official"]:
        if official.get(name) != "PASS":
            proof_ok = False
    if gate_id in {"GATE-005", "GATE-006"} and set(official) != set(OFFICIAL_EXIT_NAMES):
        proof_ok = False
    if review["finding_counts"]["blocker"] or review["finding_counts"]["major"]:
        proof_ok = False
    if workspace_state is not None:
        validate_workspace_state(workspace_state)
        if workspace_state["unauthorized_change_count"] != 0:
            proof_ok = False
    decision = "GO" if proof_ok else "NO_GO"
    if proof_ok and non_material_remediation_pending:
        decision = "NO_GO" if gate_id == "GATE-006" else "CONDITIONAL_GO"
    record = {
        "schema_version": "gch.full-mcp.gate-decision.v2",
        "gate_id": gate_id, "project_id": project_id, "run_id": run_id, "attempt": attempt,
        "decision": decision, "required_evidence": list(required_evidence),
        "evidence_digests": {evid: evidence_by_id[evid]["record_digest"] for evid in required_evidence if evid in evidence_by_id},
        "prerequisite_gate_states": prereq_states,
        "official_acceptance_results": official,
        "review_ref": review_ref, "review_digest": review["record_digest"],
        "blocker_count": review["finding_counts"]["blocker"],
        "major_count": review["finding_counts"]["major"],
        "source_binding": dict(source_binding),
        "selection_index_ref": selection_index_ref,
        "selection_index_digest": index["index_digest"],
        "evaluated_at_utc": evaluated_at_utc,
    }
    record = seal_digest(record, "record_digest")
    validate_gate_decision(record, review=review, index=index)
    return record


def compute_invalidation(
    *, changed_paths: Sequence[str], validation_results_by_path: Mapping[str, Mapping[str, Any]],
    evidence_by_path: Mapping[str, Mapping[str, Any]], gate_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    changed = set(changed_paths)
    stale_results: set[str] = set()
    for ref, result in validation_results_by_path.items():
        validate_validation_result(result)
        source_paths = {entry["path"] for entry in result["source_snapshot"]["files"]}
        if source_paths & changed:
            stale_results.add(ref)
    stale_evidence: set[str] = set()
    for ref, evidence in evidence_by_path.items():
        validate_evidence(evidence)
        if any(vref["relative_path"] in stale_results for vref in evidence["validation_result_refs"]):
            stale_evidence.add(ref)
    invalid_gates: list[str] = []
    stale_evidence_ids = {evidence_by_path[ref]["evidence_id"] for ref in stale_evidence}
    for gate_id in GATE_ORDER:
        gate = gate_records.get(gate_id)
        if gate is None:
            continue
        validate_gate_decision(gate)
        if set(gate["required_evidence"]) & stale_evidence_ids or any(state != "GO" for state in gate["prerequisite_gate_states"].values()):
            invalid_gates.append(gate_id)
    return {
        "stale_validation_result_refs": sorted(stale_results),
        "stale_evidence_refs": sorted(stale_evidence),
        "invalidated_gate_ids": invalid_gates,
        "earliest_invalidated_gate": invalid_gates[0] if invalid_gates else None,
    }


def write_create_once_json(path: str | Path, record: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise
def build_stable_baseline_manifest(
    *, project_id: str, run_id: str, attempt: int, gate6_ref: str,
    gate6: Mapping[str, Any], gate6_index_ref: str, gate6_index_digest: str,
    official_exit_ref: str, official_exit_digest: str,
    phase5_handoff_ref: str, phase5_handoff_digest: str,
    dependency_lock_sha256: str, workspace_state_ref: str,
    workspace_state_digest: str, generated_at_utc: str,
) -> dict[str, Any]:
    validate_gate_decision(gate6)
    if gate6["gate_id"] != "GATE-006" or gate6["decision"] != "GO":
        raise QualificationError("stable baseline eligibility requires GATE-006 GO")
    record = {
        "schema_version": "gch.full-mcp.stable-baseline-manifest.v1",
        "project_id": project_id, "run_id": run_id, "attempt": attempt,
        "gate6_ref": gate6_ref, "gate6_digest": gate6["record_digest"],
        "gate6_index_ref": gate6_index_ref, "gate6_index_digest": gate6_index_digest,
        "official_exit_ref": official_exit_ref, "official_exit_digest": official_exit_digest,
        "phase5_handoff_ref": phase5_handoff_ref, "phase5_handoff_digest": phase5_handoff_digest,
        "dependency_lock_sha256": dependency_lock_sha256,
        "workspace_state_ref": workspace_state_ref, "workspace_state_digest": workspace_state_digest,
        "eligibility_status": "ELIGIBLE", "declaration_status": "NOT_DECLARED",
        "generated_at_utc": generated_at_utc,
    }
    record = seal_digest(record, "record_digest")
    validate_stable_baseline_manifest(record, gate6=gate6)
    return record
