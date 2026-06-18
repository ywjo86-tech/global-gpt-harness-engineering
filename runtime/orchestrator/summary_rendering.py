from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _as_dict(report: Any) -> dict[str, Any]:
    if hasattr(report, "to_dict"):
        return dict(report.to_dict())
    if isinstance(report, Mapping):
        return dict(report)
    if hasattr(report, "__dict__"):
        return dict(report.__dict__)
    return {}


def _bullet_lines(items: Any) -> list[str]:
    values: list[str]
    if items is None:
        values = []
    elif isinstance(items, list):
        values = [str(item) for item in items if str(item).strip()]
    elif isinstance(items, (tuple, set)):
        values = [str(item) for item in items if str(item).strip()]
    else:
        text = str(items).strip()
        values = [text] if text else []
    return [f"- {item}" for item in values] if values else ["- none"]


def _key_value_lines(pairs: list[tuple[str, Any]]) -> list[str]:
    lines: list[str] = []
    for key, value in pairs:
        text = "none" if value in (None, "", [], {}) else str(value)
        lines.append(f"- {key}: {text}")
    return lines


def render_collection_markdown(report: Any) -> str:
    data = _as_dict(report)
    lines = [
        "# Collection Summary",
        "",
        "## Snapshot",
        *_key_value_lines(
            [
                ("Run ID", data.get("run_id")),
                ("Received Threads", ", ".join(data.get("received_threads", [])) or "none"),
                ("Completed Outputs", ", ".join(data.get("completed_outputs", [])) or "none"),
                ("Missing Outputs", ", ".join(data.get("missing_outputs", [])) or "none"),
                ("Failed Workers", ", ".join(data.get("failed_workers", [])) or "none"),
                ("Requirement Coverage", data.get("requirement_coverage")),
                ("QA Required", data.get("qa_required")),
                ("Collection Status", data.get("collection_status")),
                ("Next Step Decision", data.get("next_step_decision")),
                ("Final Handoff Readiness", data.get("final_handoff_readiness")),
            ]
        ),
        "",
        "## Handoff Reports",
        *_bullet_lines(data.get("handoff_reports", [])),
        "",
        "## Worker Results",
        *_bullet_lines(data.get("worker_results", [])),
        "",
        "## Risk Summary",
        *_bullet_lines(data.get("risk_summary", [])),
        "",
        "## Approval Classification Summary",
        *_bullet_lines(data.get("approval_classification_summary", [])),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_fanin_markdown(report: Any) -> str:
    data = _as_dict(report)
    lines = [
        "# Fan-In Summary",
        "",
        "## Snapshot",
        *_key_value_lines(
            [
                ("Threads Received", ", ".join(data.get("threads_received", [])) or "none"),
                ("Completed Outputs", ", ".join(data.get("completed_outputs", [])) or "none"),
                ("Missing Outputs", ", ".join(data.get("missing_outputs", [])) or "none"),
                ("Failed Workers", ", ".join(data.get("failed_workers", [])) or "none"),
                ("Duplicate Work", ", ".join(data.get("duplicate_work", [])) or "none"),
                ("Requirement Coverage", data.get("requirement_coverage")),
                ("QA Required", data.get("qa_required")),
                ("Next Step Decision", data.get("next_step_decision")),
                ("Final Handoff Readiness", data.get("final_handoff_readiness")),
            ]
        ),
        "",
        "## Conflicts",
        *_bullet_lines(data.get("conflicts", [])),
        "",
        "## Risk Summary",
        *_bullet_lines(data.get("risk_summary", [])),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_stage_gate_markdown(report: Any) -> str:
    data = _as_dict(report)
    lines = [
        "# Stage Gate Summary",
        "",
        "## Decision",
        *_key_value_lines(
            [
                ("Decision", data.get("decision", data.get("status"))),
                ("Phase", data.get("phase")),
                ("Completion Criteria Checked", data.get("completion_criteria_checked")),
                ("Fan-In Reviewed", data.get("fan_in_reviewed")),
                ("Authorization", data.get("authorization")),
                ("Next Step", data.get("next_step")),
            ]
        ),
        "",
        "## Evidence Reviewed",
        *_bullet_lines(data.get("evidence_reviewed", [])),
        "",
        "## Conditions",
        *_bullet_lines(data.get("conditions", [])),
        "",
        "## Open Questions",
        *_bullet_lines(data.get("open_questions", [])),
        "",
        "## Remaining Risks",
        *_bullet_lines(data.get("remaining_risks", [])),
        "",
        "## Blocker Summary",
        str(data.get("blocker_summary", "") or "none"),
    ]
    return "\n".join(lines).rstrip() + "\n"
