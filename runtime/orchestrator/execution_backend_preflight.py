from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

PREFLIGHT_RECORD_TYPE = "ExecutionBackendPreflightRecord"
PREFLIGHT_CONTRACT_VERSION = "IF-108.v1"
PREFLIGHT_PASS = "PASS"
PREFLIGHT_FAIL = "BACKEND_LAUNCHER_COMPATIBILITY_FAILED"

REQUIRED_TOP_LEVEL_FIELDS = (
    "identity_baseline_binding",
    "cli",
    "launcher_contract",
    "process_policy",
    "fallback_policy",
    "result_flow_contract",
    "known_issue",
    "compatibility_status",
    "blocking_reasons",
    "evidence_references",
)


@dataclass(frozen=True, slots=True)
class ExecutionBackendPreflightInput:
    identity_baseline_binding: Mapping[str, Any]
    cli: Mapping[str, Any]
    launcher_contract: Mapping[str, Any]
    process_policy: Mapping[str, Any]
    fallback_policy: Mapping[str, Any]
    result_flow_contract: Mapping[str, Any]
    known_issue: Mapping[str, Any]
    evidence_references: tuple[str, ...] = field(default_factory=tuple)


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value)


def _yes(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().upper() in {"YES", "PASS", "TRUE"})


def _no(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.strip().upper() in {"NO", "FAIL", "FALSE"})


def _reasons_for_preflight(record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []

    for field_name in REQUIRED_TOP_LEVEL_FIELDS:
        if field_name not in record:
            if field_name != "blocking_reasons":
                reasons.append(f"missing:{field_name}")

    identity = record.get("identity_baseline_binding")
    if not _is_mapping(identity):
        reasons.append("identity_baseline_binding_missing")
    else:
        for key in ("project_id", "baseline_ref"):
            if not _has_text(identity.get(key)):
                reasons.append(f"identity_baseline_binding_{key}_missing")

    cli = record.get("cli")
    if not _is_mapping(cli):
        reasons.append("cli_missing")
    else:
        if not _yes(cli.get("detected")):
            reasons.append("cli_not_detected")
        if not _has_text(cli.get("version")):
            reasons.append("cli_version_missing")
        if not _has_text(cli.get("executable")):
            reasons.append("cli_executable_missing")

    launcher = record.get("launcher_contract")
    if not _is_mapping(launcher):
        reasons.append("launcher_contract_missing")
    else:
        if not _yes(launcher.get("supported_invocation_verified")):
            reasons.append("supported_invocation_not_verified")
        if not _yes(launcher.get("launcher_compatibility")):
            reasons.append("launcher_compatibility_not_pass")
        if _yes(launcher.get("legacy_or_unsupported_invocation_detected")):
            reasons.append("legacy_or_unsupported_invocation_detected")

    process_policy = record.get("process_policy")
    if not _is_mapping(process_policy):
        reasons.append("process_policy_missing")
    else:
        if process_policy.get("automatic_retry_count") not in (0, "0"):
            reasons.append("automatic_retry_not_zero")
        if not _has_text(process_policy.get("cwd_mode")):
            reasons.append("cwd_mode_missing")
        if not _has_text(process_policy.get("output_transport")):
            reasons.append("output_transport_missing")

    fallback_policy = record.get("fallback_policy")
    if not _is_mapping(fallback_policy):
        reasons.append("fallback_policy_missing")
    else:
        if not _yes(fallback_policy.get("codex_to_manual_fallback_preserved")):
            reasons.append("codex_to_manual_fallback_not_preserved")
        if not _yes(fallback_policy.get("nvidia_to_codex_auto_fallback_absent")):
            reasons.append("nvidia_to_codex_auto_fallback_not_absent")

    result_flow = record.get("result_flow_contract")
    if not _is_mapping(result_flow):
        reasons.append("result_flow_contract_missing")
    else:
        if not _yes(result_flow.get("provider_neutral_normalization_preserved")):
            reasons.append("provider_neutral_normalization_not_preserved")
        if not _yes(result_flow.get("stage_gate_authority_preserved")):
            reasons.append("stage_gate_authority_not_preserved")
        if not _yes(result_flow.get("provider_router_authority_preserved")):
            reasons.append("provider_router_authority_not_preserved")

    known_issue = record.get("known_issue")
    if not _is_mapping(known_issue):
        reasons.append("known_issue_missing")
    else:
        if known_issue.get("issue_id") != "GRAPHIFY_PHASE2_LAUNCHER_MISMATCH":
            reasons.append("known_issue_id_mismatch")
        for key in ("observed_phase", "temporary_recovery", "required_phase3_action"):
            if not _has_text(known_issue.get(key)):
                reasons.append(f"known_issue_{key}_missing")
        if not _yes(known_issue.get("historical_completion_preserved")):
            reasons.append("known_issue_historical_completion_not_preserved")
        if not _yes(known_issue.get("no_core_modification_preserved")):
            reasons.append("known_issue_no_core_modification_not_preserved")

    evidence_refs = record.get("evidence_references")
    if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs or any(not _has_text(item) for item in evidence_refs):
        reasons.append("evidence_references_missing")

    status = record.get("compatibility_status")
    if status not in {PREFLIGHT_PASS, PREFLIGHT_FAIL}:
        reasons.append("compatibility_status_unknown")
    elif status == PREFLIGHT_PASS and reasons:
        reasons.append("compatibility_status_pass_with_blockers")

    return reasons


def evaluate_execution_backend_preflight(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an IF-108 preflight record with unknown or missing evidence closed."""
    reasons = _reasons_for_preflight(record)
    status = PREFLIGHT_PASS if not reasons else PREFLIGHT_FAIL
    return {
        "record_type": PREFLIGHT_RECORD_TYPE,
        "contract_version": PREFLIGHT_CONTRACT_VERSION,
        "compatibility_status": status,
        "preflight_passed": status == PREFLIGHT_PASS,
        "blocking_reasons": reasons,
    }


def collect_execution_backend_preflight(
    preflight_input: ExecutionBackendPreflightInput | Mapping[str, Any],
) -> dict[str, Any]:
    """Build a reusable future-run IF-108 record from supplied evidence only."""
    if isinstance(preflight_input, ExecutionBackendPreflightInput):
        payload: dict[str, Any] = {
            "identity_baseline_binding": dict(preflight_input.identity_baseline_binding),
            "cli": dict(preflight_input.cli),
            "launcher_contract": dict(preflight_input.launcher_contract),
            "process_policy": dict(preflight_input.process_policy),
            "fallback_policy": dict(preflight_input.fallback_policy),
            "result_flow_contract": dict(preflight_input.result_flow_contract),
            "known_issue": dict(preflight_input.known_issue),
            "evidence_references": list(preflight_input.evidence_references),
        }
    elif isinstance(preflight_input, Mapping):
        payload = {key: preflight_input.get(key) for key in REQUIRED_TOP_LEVEL_FIELDS if key != "compatibility_status"}
        payload.setdefault("evidence_references", preflight_input.get("evidence_references", []))
    else:
        payload = {}

    evaluation = evaluate_execution_backend_preflight({**payload, "compatibility_status": PREFLIGHT_PASS})
    payload.update(
        {
            "record_type": PREFLIGHT_RECORD_TYPE,
            "contract_version": PREFLIGHT_CONTRACT_VERSION,
            "compatibility_status": evaluation["compatibility_status"],
            "blocking_reasons": evaluation["blocking_reasons"],
        }
    )
    return payload
