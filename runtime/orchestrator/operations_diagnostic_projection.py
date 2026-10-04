"""Read-only projection over existing diagnostics, attention, and recovery evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_ALLOWED_STATES = frozenset({
    "HEALTHY", "WARN", "DEGRADED", "BLOCKED", "RECOVERING", "UNKNOWN", "STALE"
})
_FRESHNESS_STATES = frozenset({"FRESH", "STALE", "UNKNOWN"})
_ISSUE_STATES = frozenset({"WARN", "DEGRADED", "BLOCKED", "RECOVERING"})
_SEVERITY = {
    "HEALTHY": 0,
    "UNKNOWN": 1,
    "STALE": 2,
    "WARN": 3,
    "DEGRADED": 4,
    "RECOVERING": 5,
    "BLOCKED": 6,
}


class OperationsDiagnosticProjectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DiagnosticHealthProjectionV1:
    overall_state: str
    current_issue_count: int
    recovering: bool
    user_action_required: bool
    domain_states: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...]
    freshness: str


def _state(value: object) -> str:
    item = str(value or "UNKNOWN").strip().upper()
    return item if item in _ALLOWED_STATES else "UNKNOWN"


def _freshness(value: object) -> str:
    item = str(value or "UNKNOWN").strip().upper()
    return item if item in _FRESHNESS_STATES else "UNKNOWN"


def build_diagnostic_health_projection(
    *,
    current_state: Mapping[str, Any],
    diagnostic_findings: Sequence[Mapping[str, Any]],
    attention_events: Sequence[Mapping[str, Any]],
    recovery_refs: Sequence[str],
) -> DiagnosticHealthProjectionV1:
    if not isinstance(current_state, Mapping):
        raise OperationsDiagnosticProjectionError("current state must be a mapping")
    freshness = _freshness(current_state.get("freshness"))
    normalized = str(current_state.get("normalized_state") or "UNKNOWN").strip().upper()
    domain_states: list[tuple[str, str]] = []
    evidence_refs: list[str] = []
    issue_states: list[str] = []

    for finding in diagnostic_findings:
        if not isinstance(finding, Mapping):
            raise OperationsDiagnosticProjectionError("diagnostic finding must be a mapping")
        domain = str(finding.get("domain") or "unknown").strip()
        state = _state(finding.get("state"))
        domain_states.append((domain, state))
        ref = str(finding.get("evidence_ref") or "").strip()
        if ref:
            evidence_refs.append(ref)
        if state in _ISSUE_STATES:
            issue_states.append(state)
        elif state == "STALE":
            issue_states.append("DEGRADED")

    for event in attention_events:
        if not isinstance(event, Mapping):
            raise OperationsDiagnosticProjectionError("attention event must be a mapping")
        event_state = str(event.get("state") or "").strip().upper()
        ref = str(event.get("evidence_ref") or "").strip()
        if ref:
            evidence_refs.append(ref)
        if event_state not in {"HISTORICAL", "RESOLVED", "SUPERSEDED"}:
            mapped = "BLOCKED" if str(event.get("kind") or "").upper() == "STALL_CONFIRMED" else "WARN"
            issue_states.append(mapped)

    for ref in recovery_refs:
        text = str(ref or "").strip()
        if text:
            evidence_refs.append(text)

    if issue_states:
        overall = max(issue_states, key=lambda item: _SEVERITY[item])
    elif normalized == "RECOVERING":
        overall = "RECOVERING"
    elif normalized == "FAILED":
        overall = "DEGRADED"
    elif freshness in {"STALE", "UNKNOWN"}:
        overall = freshness
    else:
        overall = "HEALTHY"
    return DiagnosticHealthProjectionV1(
        overall_state=overall,
        current_issue_count=len(issue_states),
        recovering=overall == "RECOVERING" or normalized == "RECOVERING",
        user_action_required=overall == "BLOCKED",
        domain_states=tuple(domain_states),
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        freshness=freshness,
    )
