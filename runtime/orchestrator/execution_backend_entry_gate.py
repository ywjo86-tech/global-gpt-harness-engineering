from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

ENTRY_GATE_RECORD_TYPE = "ExecutionBackendEntryGateRecord"
ENTRY_GATE_CONTRACT_VERSION = "IF-109.v1"
GO = "GO"
NO_GO = "NO_GO"

MANDATORY_PREDICATES = (
    "codex_cli_detected",
    "codex_cli_version_recorded",
    "supported_invocation_verified",
    "launcher_compatibility_pass",
    "read_only_backend_diagnostic_smoke_pass",
    "isolated_state_changing_smoke_pass",
    "codex_to_manual_fallback_pass",
    "provider_separation_smoke_pass",
    "nvidia_to_codex_auto_fallback_absent",
    "provider_router_authority_preserved",
    "full_plan_core_regression_pass",
    "graphify_phase2_regression_pass",
)

ALLOWED_CORE_CHANGE_CLASSIFICATIONS = frozenset(
    {
        "NO_CORE_AUTHORITY_CHANGE",
        "SEMANTICS_PRESERVING_CONTROLLED_CHANGE",
        "PLAN_REVISION_REQUIRED",
    }
)


@dataclass(frozen=True, slots=True)
class ExecutionBackendEntryGateInput:
    preflight: Mapping[str, Any]
    smoke_records: Mapping[str, Any] = field(default_factory=dict)
    fallback_record: Mapping[str, Any] = field(default_factory=dict)
    routing_record: Mapping[str, Any] = field(default_factory=dict)
    regression_records: Mapping[str, Any] = field(default_factory=dict)
    changed_file_record: Mapping[str, Any] = field(default_factory=dict)
    core_change_record: Mapping[str, Any] = field(default_factory=dict)
    known_issue_closure: Mapping[str, Any] = field(default_factory=dict)
    final_question_matrix: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    evidence_references: tuple[str, ...] = field(default_factory=tuple)
    independent_review_reference: str = ""


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _yes(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().upper() in {"YES", "PASS", "TRUE"})


def _pass_status(value: Any) -> bool:
    return value == "PASS" or _yes(value)


def _record_passes(record: Mapping[str, Any], *keys: str) -> bool:
    if not isinstance(record, Mapping) or not record:
        return False
    if not keys:
        return _pass_status(record.get("status") or record.get("result") or record.get("decision"))
    return all(_pass_status(record.get(key)) for key in keys)


def _as_input(payload: ExecutionBackendEntryGateInput | Mapping[str, Any]) -> ExecutionBackendEntryGateInput:
    if isinstance(payload, ExecutionBackendEntryGateInput):
        return payload
    if not isinstance(payload, Mapping):
        return ExecutionBackendEntryGateInput(preflight={})
    final_question_matrix = payload.get("final_question_matrix", ())
    evidence_references = payload.get("evidence_references", ())
    return ExecutionBackendEntryGateInput(
        preflight=payload.get("preflight", {}),
        smoke_records=payload.get("smoke_records", {}),
        fallback_record=payload.get("fallback_record", {}),
        routing_record=payload.get("routing_record", {}),
        regression_records=payload.get("regression_records", {}),
        changed_file_record=payload.get("changed_file_record", {}),
        core_change_record=payload.get("core_change_record", {}),
        known_issue_closure=payload.get("known_issue_closure", {}),
        final_question_matrix=tuple(final_question_matrix if isinstance(final_question_matrix, (list, tuple)) else ()),
        evidence_references=tuple(evidence_references if isinstance(evidence_references, (list, tuple)) else ()),
        independent_review_reference=str(payload.get("independent_review_reference", "")),
    )


def _final_questions_all_yes(final_question_matrix: tuple[Mapping[str, Any], ...]) -> bool:
    if len(final_question_matrix) != 10:
        return False
    seen: set[str] = set()
    for index, item in enumerate(final_question_matrix, start=1):
        if not isinstance(item, Mapping):
            return False
        question_id = str(item.get("question_id") or item.get("id") or f"Q{index:02d}")
        if question_id in seen:
            return False
        seen.add(question_id)
        if not _yes(item.get("answer")):
            return False
    return True


def _core_change_allowed(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping) or not record:
        return False
    classification = record.get("core_change_classification")
    if classification not in ALLOWED_CORE_CHANGE_CLASSIFICATIONS:
        return False
    if classification == "PLAN_REVISION_REQUIRED":
        return False
    if classification == "SEMANTICS_PRESERVING_CONTROLLED_CHANGE":
        return _pass_status(record.get("controlled_change_record_status"))
    return record.get("authority_semantics_changed") is False


def _known_issue_closed(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping) or not record:
        return False
    return (
        record.get("issue_id") == "GRAPHIFY_PHASE2_LAUNCHER_MISMATCH"
        and _yes(record.get("historical_completion_preserved"))
        and _yes(record.get("manual_recovery_history_preserved"))
        and _yes(record.get("no_core_modification_preserved"))
        and _yes(record.get("closure_evidence_bound"))
        and _pass_status(record.get("closure_status"))
    )


def _changed_files_allowed(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping) or not record:
        return False
    return (
        _pass_status(record.get("status"))
        and _yes(record.get("only_approved_targets_changed"))
        and record.get("protected_product_core_mutation_count") == 0
    )


def _evidence_complete(evidence_references: tuple[str, ...], independent_review_reference: str) -> bool:
    return (
        len(evidence_references) >= 16
        and all(_has_text(item) for item in evidence_references)
        and _has_text(independent_review_reference)
    )


def _predicate_results(payload: ExecutionBackendEntryGateInput) -> dict[str, bool]:
    preflight = payload.preflight
    smoke = payload.smoke_records
    routing = payload.routing_record
    regressions = payload.regression_records
    cli = preflight.get("cli", {}) if isinstance(preflight.get("cli", {}), Mapping) else {}
    launcher = preflight.get("launcher_contract", {}) if isinstance(preflight.get("launcher_contract", {}), Mapping) else {}
    read_only_smoke = smoke.get("read_only_backend_diagnostic") if isinstance(smoke, Mapping) else {}
    state_smoke = smoke.get("isolated_state_changing") if isinstance(smoke, Mapping) else {}
    if not isinstance(read_only_smoke, Mapping):
        read_only_smoke = {}
    if not isinstance(state_smoke, Mapping):
        state_smoke = {}
    if not isinstance(routing, Mapping):
        routing = {}
    if not isinstance(regressions, Mapping):
        regressions = {}
    full_plan_core = regressions.get("full_plan_core", {})
    graphify_phase2 = regressions.get("graphify_phase2", {})
    if not isinstance(full_plan_core, Mapping):
        full_plan_core = {}
    if not isinstance(graphify_phase2, Mapping):
        graphify_phase2 = {}

    return {
        "codex_cli_detected": isinstance(preflight, Mapping) and _yes(cli.get("detected")),
        "codex_cli_version_recorded": isinstance(preflight, Mapping) and _has_text(cli.get("version")),
        "supported_invocation_verified": isinstance(preflight, Mapping)
        and _yes(launcher.get("supported_invocation_verified")),
        "launcher_compatibility_pass": isinstance(preflight, Mapping)
        and preflight.get("compatibility_status") == "PASS"
        and _yes(launcher.get("launcher_compatibility")),
        "read_only_backend_diagnostic_smoke_pass": _record_passes(read_only_smoke),
        "isolated_state_changing_smoke_pass": _record_passes(state_smoke)
        and state_smoke.get("protected_product_core_mutation_count") == 0,
        "codex_to_manual_fallback_pass": _record_passes(payload.fallback_record)
        and _yes(payload.fallback_record.get("manual_fallback_artifact_created")),
        "provider_separation_smoke_pass": _record_passes(routing)
        and _yes(routing.get("planner_provider_neutral"))
        and _yes(routing.get("state_changing_routes_to_codex"))
        and _yes(routing.get("read_only_reasoning_routes_to_nvidia")),
        "nvidia_to_codex_auto_fallback_absent": _yes(routing.get("nvidia_to_codex_auto_fallback_absent")),
        "provider_router_authority_preserved": _yes(routing.get("provider_router_authority_preserved")),
        "full_plan_core_regression_pass": _record_passes(full_plan_core),
        "graphify_phase2_regression_pass": _record_passes(graphify_phase2)
        and _yes(graphify_phase2.get("historical_status_preserved")),
    }


def evaluate_execution_backend_entry_gate(
    evidence: ExecutionBackendEntryGateInput | Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate IF-109 as a pure fail-closed GO/NO_GO conjunction."""
    payload = _as_input(evidence)
    predicates = _predicate_results(payload)
    question_matrix_passed = _final_questions_all_yes(payload.final_question_matrix)
    core_change_passed = _core_change_allowed(payload.core_change_record)
    changed_files_passed = _changed_files_allowed(payload.changed_file_record)
    known_issue_passed = _known_issue_closed(payload.known_issue_closure)
    evidence_package_complete = _evidence_complete(payload.evidence_references, payload.independent_review_reference)

    all_results = {
        **predicates,
        "final_10_questions_yes": question_matrix_passed,
        "core_change_classification_allowed": core_change_passed,
        "changed_file_protected_mutation_record_pass": changed_files_passed,
        "graphify_known_issue_closure_bound": known_issue_passed,
        "evidence_package_complete": evidence_package_complete,
    }
    blocking_reasons = [name for name, passed in all_results.items() if passed is not True]
    decision = GO if not blocking_reasons else NO_GO
    return {
        "record_type": ENTRY_GATE_RECORD_TYPE,
        "contract_version": ENTRY_GATE_CONTRACT_VERSION,
        "decision": decision,
        "gate_status": decision,
        "mandatory_predicates": {name: predicates[name] for name in MANDATORY_PREDICATES},
        "final_question_count": len(payload.final_question_matrix),
        "final_questions_yes": question_matrix_passed,
        "core_change_classification": payload.core_change_record.get("core_change_classification")
        if isinstance(payload.core_change_record, Mapping)
        else None,
        "known_issue_closure_bound": known_issue_passed,
        "blocking_reasons": blocking_reasons,
    }
