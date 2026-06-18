from __future__ import annotations

import json
from pathlib import Path

from .result_collector import CollectionReport
from .result_normalizer import normalize_worker_result
from .summary_rendering import render_fanin_markdown
from .schemas import FanInReport, TaskSlice, WorkerResult


def _read_result(path: Path) -> dict[str, object] | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    legacy_path = path.with_name("worker_result.json")
    if legacy_path.exists():
        return json.loads(legacy_path.read_text(encoding="utf-8"))
    return None


def _has_handoff(path: Path) -> bool:
    if path.exists():
        return True
    return path.with_name("worker_handoff.md").exists()


def _format_coverage(planned: list[TaskSlice], completed: list[WorkerResult]) -> str:
    if len(completed) == len(planned):
        return "complete"
    if completed:
        return "partial"
    return "missing"


def build_fanin_report(project_root: str | Path, planned: list[TaskSlice], output_dir: str | Path) -> FanInReport:
    output_dir = Path(output_dir)
    completed_results: list[WorkerResult] = []
    missing_outputs: list[str] = []
    failed_workers: list[str] = []
    conflicts: list[str] = []
    duplicate_work: list[str] = []
    risk_summary: list[str] = []

    seen_inputs: set[tuple[str, str]] = set()
    for task in planned:
        task_dir = output_dir / task.thread_id
        result_path = task_dir / "result.json"
        payload = _read_result(result_path)
        handoff_exists = _has_handoff(task_dir / "handoff_report.md")
        if payload is None or not handoff_exists:
            missing_outputs.append(task.thread_id)
            continue
        normalized = normalize_worker_result(
            payload,
            task=task,
            source="fanin",
            output_dir=str(task_dir),
            run_root=str(Path(output_dir).parent),
        )
        completed_results.append(
            WorkerResult(
                thread_id=normalized["thread_id"],
                agent_name=normalized["agent_name"],
                status=normalized["status"],
                summary=normalized["summary"],
                findings=list(normalized.get("findings", []) or []),
                warnings=list(normalized.get("warnings", []) or []),
                errors=list(normalized.get("errors", []) or []),
                artifacts=list(normalized.get("artifacts", []) or []),
                next_step=normalized.get("next_step", ""),
            )
        )
        risk_summary.extend(completed_results[-1].warnings)
        key = (task.assigned_agent, task.input.strip())
        if key in seen_inputs:
            duplicate_work.append(f"{task.thread_id}:{task.assigned_agent}")
        else:
            seen_inputs.add(key)
        if completed_results[-1].errors:
            conflicts.append(f"{task.thread_id} reported errors: {', '.join(completed_results[-1].errors)}")
            failed_workers.append(task.thread_id)

    qa_required = bool(conflicts or missing_outputs or any(item.lower().find("review") >= 0 for item in risk_summary))
    readiness = "ready" if not missing_outputs and not conflicts else "blocked"
    next_step_decision = "request stage gate review" if readiness == "ready" else "remediate fan-in conflicts"
    return FanInReport(
        threads_received=[task.thread_id for task in planned],
        completed_outputs=[result.thread_id for result in completed_results],
        missing_outputs=missing_outputs,
        failed_workers=failed_workers,
        conflicts=conflicts,
        duplicate_work=duplicate_work,
        requirement_coverage=_format_coverage(planned, completed_results),
        risk_summary=risk_summary,
        qa_required=qa_required,
        next_step_decision=next_step_decision,
        final_handoff_readiness=readiness,
    )


def build_fanin_report_from_collection(collection: CollectionReport, planned: list[TaskSlice]) -> FanInReport:
    completed_results: list[WorkerResult] = []
    conflicts: list[str] = []
    duplicate_work = list(collection.duplicate_work)
    risk_summary = list(collection.risk_summary)
    failed_workers = list(collection.failed_workers)
    for item in collection.task_outputs:
        if not item.get("result_exists"):
            continue
        result = WorkerResult(
            thread_id=item["thread_id"],
            agent_name=item["assigned_agent"],
            status=item["status"],
            summary=item.get("summary", ""),
            findings=list(item.get("findings", []) or []),
            warnings=list(item.get("warnings", []) or []),
            errors=list(item.get("errors", []) or []),
            artifacts=list(item.get("artifacts", []) or []),
            next_step=item.get("next_step", ""),
        )
        completed_results.append(result)
        if result.errors:
            conflicts.append(f"{result.thread_id} reported errors: {', '.join(result.errors)}")
            if result.thread_id not in failed_workers:
                failed_workers.append(result.thread_id)

    requirement_coverage = collection.requirement_coverage
    qa_required = collection.qa_required or bool(conflicts)
    readiness = collection.final_handoff_readiness
    next_step_decision = collection.next_step_decision
    return FanInReport(
        threads_received=collection.received_threads,
        completed_outputs=[result.thread_id for result in completed_results],
        missing_outputs=list(collection.missing_outputs),
        failed_workers=failed_workers,
        conflicts=conflicts,
        duplicate_work=duplicate_work,
        requirement_coverage=requirement_coverage,
        risk_summary=risk_summary,
        qa_required=qa_required,
        next_step_decision=next_step_decision,
        final_handoff_readiness=readiness,
    )

