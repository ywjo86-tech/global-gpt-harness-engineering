from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from .execution_modes import normalize_execution_mode
from .schemas import FanInReport, RuntimeState, TaskSlice


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    return path.read_text(encoding="utf-8")


def _bullet_lines(items: list[str] | tuple[str, ...] | None) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def _numbered_lines(items: list[str] | tuple[str, ...] | None) -> str:
    if not items:
        return "1. none"
    return "\n".join(f"{index + 1}. {item}" for index, item in enumerate(items))


def _path_lines(items: list[str] | tuple[str, ...] | None) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def _contract_input_files(contract_summary: dict[str, Any]) -> list[str]:
    ordered_keys = [
        "development_plan_path",
        "changelog_path",
        "app_log_path",
        "orchestration_state_path",
    ]
    return [str(contract_summary[key]) for key in ordered_keys if contract_summary.get(key)]


def build_worker_prompt(
    contract_summary: dict[str, Any],
    state_snapshot: dict[str, Any],
    task: TaskSlice,
    run_root: str,
    mode: str,
) -> str:
    template = Template(_read_template("codex_worker_prompt.md"))
    input_files = _contract_input_files(contract_summary)
    task_input = task.input.strip() or "none"
    return template.safe_substitute(
        project_root=contract_summary.get("project_root", ""),
        run_root=run_root,
        run_id=task.run_id or state_snapshot.get("active_run_id", ""),
        thread_id=task.thread_id,
        assigned_agent=task.assigned_agent,
        execution_mode=normalize_execution_mode(mode),
        task_purpose=task_input,
        development_plan_reference=contract_summary.get("development_plan_path", ""),
        orchestration_state_reference=contract_summary.get("orchestration_state_path", ""),
        input_files=_path_lines(input_files),
        editable_scope=_bullet_lines(task.editable_scope),
        forbidden_scope=_bullet_lines(task.forbidden_scope),
        expected_output=task.expected_output.strip() or "none",
        validation_criteria=_numbered_lines(task.validation_criteria),
        handoff_report_format=(
            "# Handoff Report\n\n"
            f"Thread: {task.thread_id}\n"
            f"Agent: {task.assigned_agent}\n"
            "Status: completed|partial|failed\n"
            "Summary: one or two sentences\n"
            "Findings: bullet list\n"
            "Warnings: bullet list\n"
            "Errors: bullet list\n"
        ),
        approval_classification=task.risk_class,
        safety_warning_protocol=(
            "General work may proceed in the automation flow. "
            "Caution work needs approval. Dangerous work needs exact '위험 확인 후 승인'."
        ),
        stage_gate_rule=(
            "Stage Gate Reviewer decides only GO / CONDITIONAL GO / NO-GO. "
            "That decision does not replace Safety Warning Protocol approval."
        ),
        output_file_path=task.result_path or f"{run_root}/outputs/{task.thread_id}/result.json",
        handoff_report_path=task.handoff_report_path or f"{run_root}/outputs/{task.thread_id}/handoff_report.md",
        manual_execution_path=task.manual_execution_path or f"{run_root}/outputs/{task.thread_id}/manual_execution.md",
        manual_instructions=(
            "1. Paste this file into Codex if CLI execution is unavailable.\n"
            "2. Save the handoff report to the output path above.\n"
            "3. Save result.json if possible.\n"
            "4. Run collect after saving outputs."
        ),
    )


def build_fanin_prompt(
    contract_summary: dict[str, Any],
    state_snapshot: dict[str, Any],
    collection_report: dict[str, Any],
    run_root: str,
) -> str:
    template = Template(_read_template("codex_fanin_prompt.md"))
    return template.safe_substitute(
        project_root=contract_summary.get("project_root", ""),
        current_phase=contract_summary.get("current_phase", ""),
        run_root=run_root,
        run_id=state_snapshot.get("active_run_id", ""),
        development_plan_reference=contract_summary.get("development_plan_path", ""),
        changelog_reference=contract_summary.get("changelog_path", ""),
        app_log_reference=contract_summary.get("app_log_path", ""),
        orchestration_state_reference=contract_summary.get("orchestration_state_path", ""),
        received_threads=", ".join(collection_report.get("received_threads", [])) or "none",
        completed_outputs=", ".join(collection_report.get("completed_outputs", [])) or "none",
        missing_outputs=", ".join(collection_report.get("missing_outputs", [])) or "none",
        failed_workers=", ".join(collection_report.get("failed_workers", [])) or "none",
        duplicate_work=", ".join(collection_report.get("duplicate_work", [])) or "none",
        requirement_coverage=collection_report.get("requirement_coverage", "missing"),
        risk_summary=_bullet_lines(collection_report.get("risk_summary", [])),
        qa_required=str(bool(collection_report.get("qa_required", False))).lower(),
        next_step_decision=collection_report.get("next_step_decision", ""),
        final_handoff_readiness=collection_report.get("final_handoff_readiness", ""),
        approval_classification_summary=_bullet_lines(collection_report.get("approval_classification_summary", [])),
        handoff_reports=_bullet_lines(collection_report.get("handoff_reports", [])),
        worker_results=_bullet_lines(collection_report.get("worker_results", [])),
    )


def build_stage_gate_prompt(
    contract_summary: dict[str, Any],
    state_snapshot: dict[str, Any],
    fanin_report: dict[str, Any],
    run_root: str,
    collection_report: dict[str, Any] | None = None,
) -> str:
    template = Template(_read_template("codex_stage_gate_prompt.md"))
    pending_workers = state_snapshot.get("pending_workers", []) or []
    collection_handoffs = []
    if collection_report:
        collection_handoffs = collection_report.get("handoff_reports", []) or []
    if not collection_handoffs:
        collection_handoffs = fanin_report.get("completed_outputs", []) or []
    approval_lines = [
        f"{item.get('thread_id', 'unknown')}:{item.get('assigned_agent', 'unknown')}:{item.get('risk_class', 'unknown')}"
        for item in pending_workers
    ]
    return template.safe_substitute(
        project_root=contract_summary.get("project_root", ""),
        current_phase=contract_summary.get("current_phase", ""),
        run_root=run_root,
        run_id=state_snapshot.get("active_run_id", ""),
        development_plan_reference=contract_summary.get("development_plan_path", ""),
        changelog_reference=contract_summary.get("changelog_path", ""),
        app_log_reference=contract_summary.get("app_log_path", ""),
        orchestration_state_reference=contract_summary.get("orchestration_state_path", ""),
        fanin_report_summary=fanin_report.get("next_step_decision", ""),
        received_threads=", ".join(fanin_report.get("threads_received", [])) or "none",
        completed_outputs=", ".join(fanin_report.get("completed_outputs", [])) or "none",
        missing_outputs=", ".join(fanin_report.get("missing_outputs", [])) or "none",
        conflicts=", ".join(fanin_report.get("conflicts", [])) or "none",
        duplicate_work=", ".join(fanin_report.get("duplicate_work", [])) or "none",
        requirement_coverage=fanin_report.get("requirement_coverage", "missing"),
        risk_summary=_bullet_lines(fanin_report.get("risk_summary", [])),
        qa_required=str(bool(fanin_report.get("qa_required", False))).lower(),
        next_step_decision=fanin_report.get("next_step_decision", ""),
        final_handoff_readiness=fanin_report.get("final_handoff_readiness", ""),
        completion_criteria=(
            "GO when outputs are complete, conflicts absent, and approval gate is satisfied.\n"
            "CONDITIONAL GO when follow-up items are explicitly recorded.\n"
            "NO-GO when outputs are missing, conflicting, or approval remains pending."
        ),
        approval_classification_summary=_bullet_lines(approval_lines),
        worker_handoff_reports=_bullet_lines(collection_handoffs),
    )
