from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Mapping

REPORT_DATA_SCHEMA_V1 = "ai-office.report-data.v1"


def _tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("report fact list is invalid")
    return tuple(item.strip() for item in value if item.strip())


@dataclass(frozen=True, slots=True)
class ReportDataV1:
    report_id: str
    schema_version: str
    report_type: str
    target: str
    date: str
    purpose: str
    status: str
    progress: int | None
    progress_source: str
    summary: tuple[str, ...]
    completed: tuple[str, ...]
    in_progress: tuple[str, ...]
    issues: tuple[str, ...]
    impact: str
    user_action: str
    next_actions: tuple[str, ...]
    final_state: str
    technical_references: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    execution_status: str
    verification_status: str
    human_report_status: str = "PENDING"
    llm_report_status: str = "PENDING"
    final_completion_status: str = "WAITING_REPORT"


def build_report_data(verified_result: Mapping[str, object], verification: Mapping[str, object],
                      report_type: str, evidence_refs: Iterable[str]) -> ReportDataV1:
    verification_status = str(verification.get("status") or "")
    if report_type == "completion_report" and verification_status != "PASS":
        raise ValueError("completion report requires verification PASS")
    if report_type != "decision_or_incident_report" and verification_status != "PASS":
        raise ValueError("report requires verification PASS")
    required = ("target", "date", "purpose", "status", "summary", "impact", "user_action", "final_state")
    if any(not verified_result.get(key) for key in required):
        raise ValueError("verified report facts are incomplete")
    purpose = str(verified_result["purpose"]).strip()
    if "\n" in purpose or not purpose:
        raise ValueError("report purpose must be one sentence")
    summary = _tuple(verified_result["summary"])
    if not 5 <= len(summary) <= 8:
        raise ValueError("report summary must contain 5 to 8 facts")
    progress = verified_result.get("progress")
    if progress is not None and (isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100):
        raise ValueError("report progress is invalid")
    facts = {key: verified_result.get(key) for key in sorted(verified_result)}
    identity = {"report_type": report_type, "facts": facts, "verification": dict(verification),
                "evidence_refs": sorted(set(evidence_refs))}
    report_id = "RPT-" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:24]
    return ReportDataV1(
        report_id, REPORT_DATA_SCHEMA_V1, report_type, str(verified_result["target"]),
        str(verified_result["date"]), purpose, str(verified_result["status"]), progress,
        str(verified_result.get("progress_source") or ""), summary,
        _tuple(verified_result.get("completed")), _tuple(verified_result.get("in_progress")),
        _tuple(verified_result.get("issues")), str(verified_result["impact"]),
        str(verified_result["user_action"]), _tuple(verified_result.get("next_actions")),
        str(verified_result["final_state"]), _tuple(verified_result.get("technical_references")),
        tuple(sorted(set(str(item) for item in evidence_refs))),
        str(verified_result.get("execution_status") or "UNKNOWN"), verification_status,
    )
