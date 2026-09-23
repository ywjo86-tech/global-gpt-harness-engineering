"""Read-only incident lifecycle projection for current versus historical evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence


INCIDENT_STATES = frozenset({
    "OPEN", "ACKNOWLEDGED", "RECOVERING", "RESOLVED", "SUPERSEDED", "HISTORICAL"
})
_CURRENT_INCIDENT_STATES = frozenset({"STALLED", "FAILED"})


class IncidentProjectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IncidentProjectionV1:
    incident_id: str
    kind: str
    opened_at: str
    last_observed_at: str
    resolved_at: str
    state: str
    current_state_ref: str
    superseded_by: str
    impact: str
    user_action_required: bool
    evidence_refs: tuple[str, ...]


def project_incidents(
    *,
    current_state: str,
    current_state_ref: str,
    evidence_rows: Sequence[Mapping[str, Any]],
    now: datetime,
) -> tuple[IncidentProjectionV1, ...]:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise IncidentProjectionError("timezone-aware now is required")
    state_now = str(current_state or "UNKNOWN").strip().upper()
    result: list[IncidentProjectionV1] = []
    for row in evidence_rows:
        if not isinstance(row, Mapping):
            raise IncidentProjectionError("incident evidence row must be a mapping")
        incident_id = str(row.get("incident_id") or "").strip()
        kind = str(row.get("kind") or "").strip()
        opened_at = str(row.get("opened_at") or "").strip()
        last_observed_at = str(row.get("last_observed_at") or opened_at).strip()
        evidence_ref = str(row.get("evidence_ref") or "").strip()
        if not incident_id or not kind or not opened_at or not evidence_ref:
            raise IncidentProjectionError("incident evidence identity is incomplete")
        explicit_unresolved = bool(row.get("unresolved"))
        explicit_state = str(row.get("state") or "").strip().upper()
        if explicit_state in INCIDENT_STATES:
            projected_state = explicit_state
        elif state_now == "RECOVERING":
            projected_state = "RECOVERING"
        elif state_now in _CURRENT_INCIDENT_STATES or explicit_unresolved:
            projected_state = "OPEN"
        else:
            projected_state = "HISTORICAL"
        user_action_required = projected_state == "OPEN" and state_now in _CURRENT_INCIDENT_STATES
        result.append(IncidentProjectionV1(
            incident_id=incident_id,
            kind=kind,
            opened_at=opened_at,
            last_observed_at=last_observed_at,
            resolved_at=str(row.get("resolved_at") or ""),
            state=projected_state,
            current_state_ref=str(current_state_ref or ""),
            superseded_by=str(row.get("superseded_by") or ""),
            impact=str(row.get("impact") or ""),
            user_action_required=user_action_required,
            evidence_refs=(evidence_ref,),
        ))
    return tuple(result)
