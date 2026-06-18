from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .result_normalizer import normalize_worker_result
from .summary_rendering import render_collection_markdown
from .schemas import TaskSlice


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_result_payload(path: Path) -> dict[str, Any] | None:
    payload = _read_json(path)
    if payload is not None:
        return payload
    legacy = path.with_name("worker_result.json")
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    return None


def _read_task_payloads(run_root: Path) -> list[TaskSlice]:
    fanout_plan = _read_json(run_root / "fanout_plan.json")
    if not fanout_plan:
        return []
    return [TaskSlice(**payload) for payload in fanout_plan]


@dataclass(slots=True)
class CollectedTaskOutput:
    thread_id: str
    assigned_agent: str
    output_dir: str
    handoff_report_path: str
    result_path: str
    handoff_report_exists: bool
    result_exists: bool
    status: str
    summary: str = ""
    findings: list[str] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]
    errors: list[str] = None  # type: ignore[assignment]
    artifacts: list[str] = None  # type: ignore[assignment]
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = list(self.findings or [])
        payload["warnings"] = list(self.warnings or [])
        payload["errors"] = list(self.errors or [])
        payload["artifacts"] = list(self.artifacts or [])
        return payload


@dataclass(slots=True)
class CollectionReport:
    run_id: str
    run_root: str
    received_threads: list[str]
    completed_outputs: list[str]
    missing_outputs: list[str]
    failed_workers: list[str]
    handoff_reports: list[str]
    worker_results: list[str]
    duplicate_work: list[str]
    requirement_coverage: str
    risk_summary: list[str]
    approval_classification_summary: list[str]
    qa_required: bool
    next_step_decision: str
    final_handoff_readiness: str
    collection_status: str
    task_outputs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coverage_status(received: int, completed: int, missing: int) -> str:
    if received == 0:
        return "missing"
    if missing:
        return "partial"
    return "complete" if completed == received else "partial"


def collect_run_outputs(run_root: str | Path) -> CollectionReport:
    root = Path(run_root)
    run_manifest = _read_json(root / "run_manifest.json") or {}
    tasks = _read_task_payloads(root)
    received_threads = [task.thread_id for task in tasks]
    task_outputs: list[CollectedTaskOutput] = []
    missing_outputs: list[str] = []
    failed_workers: list[str] = []
    handoff_reports: list[str] = []
    worker_results: list[str] = []
    risk_summary: list[str] = []
    approval_classification_summary: list[str] = []
    duplicate_work: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()

    for task in tasks:
        output_dir = Path(task.output_dir or root / "outputs" / task.thread_id)
        result_path = Path(task.result_path or output_dir / "result.json")
        handoff_path = Path(task.handoff_report_path or output_dir / "handoff_report.md")

        raw_result_payload = _read_result_payload(result_path)
        handoff_exists = handoff_path.exists()
        result_payload = (
            normalize_worker_result(
                raw_result_payload,
                task=task,
                source="collector",
                output_dir=str(output_dir),
                run_root=str(root),
            )
            if raw_result_payload is not None
            else None
        )
        result_exists = result_payload is not None
        status = str(result_payload.get("status", "")) if result_payload else "missing"
        summary = str(result_payload.get("summary", "")) if result_payload else ""
        findings = list(result_payload.get("findings", []) or []) if result_payload else []
        warnings = list(result_payload.get("warnings", []) or []) if result_payload else []
        errors = list(result_payload.get("errors", []) or []) if result_payload else []
        artifacts = list(result_payload.get("artifacts", []) or []) if result_payload else []
        next_step = str(result_payload.get("next_step", "")) if result_payload else ""

        collected = CollectedTaskOutput(
            thread_id=task.thread_id,
            assigned_agent=task.assigned_agent,
            output_dir=str(output_dir),
            handoff_report_path=str(handoff_path),
            result_path=str(result_path),
            handoff_report_exists=handoff_exists,
            result_exists=result_exists,
            status=status,
            summary=summary,
            findings=findings,
            warnings=warnings,
            errors=errors,
            artifacts=artifacts,
            next_step=next_step,
        )
        task_outputs.append(collected)

        key = (task.assigned_agent, task.input.strip())
        if key in seen_pairs:
            duplicate_work.append(task.thread_id)
        else:
            seen_pairs.add(key)

        if not handoff_exists or not result_exists:
            missing_outputs.append(task.thread_id)
        elif status and status.lower() != "completed":
            failed_workers.append(task.thread_id)

        if handoff_exists:
            handoff_reports.append(str(handoff_path))
        if result_exists:
            worker_results.append(str(result_path))
        risk_summary.extend(warnings)
        approval_classification_summary.append(f"{task.thread_id}:{task.risk_class}")

    manual_mode = bool(run_manifest.get("manual_execution_required")) or any(
        (Path(task.output_dir or root / "outputs" / task.thread_id) / "manual_execution.md").exists()
        for task in tasks
    )
    collection_status = "complete"
    if missing_outputs and manual_mode:
        collection_status = "waiting_manual"
    elif missing_outputs or failed_workers:
        collection_status = "partial"
    if not tasks:
        collection_status = "missing"
    requirement_coverage = _coverage_status(len(tasks), len(tasks) - len(missing_outputs), len(missing_outputs))
    qa_required = bool(missing_outputs or failed_workers or risk_summary)
    final_handoff_readiness = "ready" if not missing_outputs and not failed_workers else "blocked"
    next_step_decision = "build fan-in report" if final_handoff_readiness == "ready" else "wait for missing outputs"

    report = CollectionReport(
        run_id=root.name,
        run_root=str(root),
        received_threads=received_threads,
        completed_outputs=[item.thread_id for item in task_outputs if item.result_exists and item.status == "completed"],
        missing_outputs=missing_outputs,
        failed_workers=failed_workers,
        handoff_reports=handoff_reports,
        worker_results=worker_results,
        duplicate_work=duplicate_work,
        requirement_coverage=requirement_coverage,
        risk_summary=risk_summary,
        approval_classification_summary=approval_classification_summary,
        qa_required=qa_required,
        next_step_decision=next_step_decision,
        final_handoff_readiness=final_handoff_readiness,
        collection_status=collection_status,
        task_outputs=[item.to_dict() for item in task_outputs],
    )

    fanin_dir = root / "fanin"
    fanin_dir.mkdir(parents=True, exist_ok=True)
    (fanin_dir / "collection_report.json").write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    (fanin_dir / "collection_report.md").write_text(render_collection_markdown(report), encoding="utf-8")
    return report
