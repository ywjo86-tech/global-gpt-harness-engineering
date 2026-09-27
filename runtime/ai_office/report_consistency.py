from __future__ import annotations

from dataclasses import dataclass
from .work_records import ReportDataV1


@dataclass(frozen=True, slots=True)
class ReportConsistencyResultV1:
    status: str
    mismatched_fields: tuple[str, ...]
    report_id: str


def validate_report_consistency(report: ReportDataV1, human_text: str, llm_text: str) -> ReportConsistencyResultV1:
    anchors = {
        "report_id": (report.report_id,), "status": (report.status,), "impact": (report.impact,),
        "user_action": (report.user_action,), "next_actions": report.next_actions,
        "issues": report.issues if report.issues else ("Unknown",),
    }
    mismatched = tuple(name for name, values in anchors.items()
                       if any(value not in human_text or value not in llm_text for value in values))
    return ReportConsistencyResultV1("PASS" if not mismatched else "FAIL", mismatched, report.report_id)
