from __future__ import annotations

from .work_records import ReportDataV1


def _lines(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- Unknown"


def render_human_report(report: ReportDataV1) -> str:
    sections = (
        f"{report.target} 보고서\n작성일: {report.date}\n보고서 ID: {report.report_id}",
        "■ 보고서 작성 목적\n\n" + report.purpose,
        "■ 보고서 요약\n\n" + "\n".join(report.summary),
        f"■ 현재 상태\n\n상태: {report.status}\n영향: {report.impact}",
        "■ 완료\n\n" + _lines(report.completed),
        "■ 진행 중\n\n" + _lines(report.in_progress),
        "■ 문제\n\n" + _lines(report.issues),
        "■ 사용자 조치\n\n" + report.user_action,
        "■ 다음 단계\n\n" + _lines(report.next_actions),
        "■ 최종 상태\n\n" + report.final_state,
        "■ 기술 참조\n\n" + _lines(report.technical_references),
    )
    return "\n\n".join(sections) + "\n"


def render_llm_report(report: ReportDataV1) -> str:
    read_when = f"Read when reviewing {report.target} {report.report_type}."
    meta = (f"report_id: {report.report_id}\nreport_type: {report.report_type}\n"
            f"target: {report.target}\ndate: {report.date}\nstatus: {report.status}")
    sections = (
        ("REPORT_META", meta), ("PURPOSE", report.purpose), ("READ_WHEN", read_when),
        ("SUMMARY", _lines(report.summary)),
        ("CURRENT_STATE", f"status: {report.status}\nimpact: {report.impact}"),
        ("COMPLETED", _lines(report.completed)), ("IN_PROGRESS", _lines(report.in_progress)),
        ("ISSUES", _lines(report.issues)), ("USER_ACTION", report.user_action),
        ("NEXT", _lines(report.next_actions)), ("FINAL_STATE", report.final_state),
        ("TECHNICAL_REFERENCES", _lines(report.technical_references)),
    )
    return "\n\n".join(f"## {heading}\n{body}" for heading, body in sections) + "\n"
