from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from .approval_gate import CAUTION, DANGEROUS, GENERAL
from .execution_modes import normalize_execution_mode
from .prompt_builder import build_worker_prompt
from .schemas import ExecutionContract, PlanningArtifact, RuntimeState, TaskSlice


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


@dataclass(slots=True)
class RunPackage:
    run_id: str
    mode: str
    project_root: str
    run_root: str
    manifest_path: str
    fanout_plan_path: str
    task_prompt_paths: dict[str, str]
    input_manifest_paths: dict[str, str]
    expected_output_paths: dict[str, str]
    worker_request_paths: dict[str, str]
    output_dirs: dict[str, str]
    fanin_dir: str
    gate_dir: str
    logs_dir: str
    manual_execution_required: bool
    codex_cli_available: bool
    task_records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _approval_summary(tasks: list[TaskSlice]) -> dict[str, int]:
    summary = {GENERAL: 0, CAUTION: 0, DANGEROUS: 0}
    for task in tasks:
        summary[task.risk_class] = summary.get(task.risk_class, 0) + 1
    return summary


def _task_output_paths(run_root: Path, thread_id: str) -> dict[str, str]:
    output_dir = run_root / "outputs" / thread_id
    return {
        "output_dir": str(output_dir),
        "handoff_report_path": str(output_dir / "handoff_report.md"),
        "result_path": str(output_dir / "result.json"),
        "manual_execution_path": str(output_dir / "manual_execution.md"),
    }


def create_run_package(
    contract: ExecutionContract,
    state: RuntimeState,
    planning_artifact: PlanningArtifact,
    tasks: list[TaskSlice],
    mode: str,
    *,
    run_id: str | None = None,
    codex_cli_available: bool = False,
) -> RunPackage:
    normalized_mode = normalize_execution_mode(mode)
    run_id = run_id or state.active_run_id or _new_run_id()
    manual_execution_required = normalized_mode == "manual" or (normalized_mode == "codex-cli" and not codex_cli_available)
    run_root = Path(contract.paths.orchestrator_runs_dir) / run_id
    tasks_dir = run_root / "tasks"
    outputs_dir = run_root / "outputs"
    fanin_dir = run_root / "fanin"
    gate_dir = run_root / "gate"
    logs_dir = run_root / "logs"

    for path in (tasks_dir, outputs_dir, fanin_dir, gate_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    run_manifest = {
        "run_id": run_id,
        "project_root": contract.paths.project_root,
        "mode": normalized_mode,
        "created_at": _utc_now(),
        "current_phase": contract.current_phase,
        "manual_execution_required": manual_execution_required,
        "codex_cli_available": codex_cli_available,
        "task_count": len(tasks),
        "approval_summary": _approval_summary(tasks),
        "planning_artifact": planning_artifact.to_dict(),
        "contract_summary": contract.summary(),
        "task_threads": [task.thread_id for task in tasks],
    }
    manifest_path = run_root / "run_manifest.json"
    _write_json(manifest_path, run_manifest)

    fanout_plan = [task.as_request_payload() for task in tasks]
    fanout_plan_path = run_root / "fanout_plan.json"
    _write_json(fanout_plan_path, fanout_plan)

    task_prompt_paths: dict[str, str] = {}
    input_manifest_paths: dict[str, str] = {}
    expected_output_paths: dict[str, str] = {}
    worker_request_paths: dict[str, str] = {}
    output_directory_paths: dict[str, str] = {}
    task_records: list[dict[str, Any]] = []

    state_snapshot = state.to_dict()
    for task in tasks:
        paths = _task_output_paths(run_root, task.thread_id)
        task.run_id = run_id
        task.run_root = str(run_root)
        task.output_dir = paths["output_dir"]
        task.handoff_report_path = paths["handoff_report_path"]
        task.result_path = paths["result_path"]
        task.manual_execution_path = paths["manual_execution_path"]

        task_dir = tasks_dir / task.thread_id
        task_dir.mkdir(parents=True, exist_ok=True)
        output_dir = Path(task.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        prompt_path = task_dir / "task_prompt.md"
        input_manifest_path = task_dir / "input_manifest.json"
        expected_output_path = task_dir / "expected_output.md"
        worker_request_path = task_dir / "worker_request.json"

        task.task_prompt_path = str(prompt_path)
        task.input_manifest_path = str(input_manifest_path)
        task.expected_output_path = str(expected_output_path)
        task.worker_request_path = str(worker_request_path)

        prompt_text = build_worker_prompt(contract.summary(), state_snapshot, task, str(run_root), normalized_mode)
        prompt_path.write_text(prompt_text, encoding="utf-8")

        input_manifest = {
            "thread_id": task.thread_id,
            "assigned_agent": task.assigned_agent,
            "task_purpose": task.input,
            "project_root": contract.paths.project_root,
            "run_id": run_id,
            "run_root": str(run_root),
            "execution_mode": normalized_mode,
            "approval_classification": task.risk_class,
            "editable_scope": task.editable_scope,
            "forbidden_scope": task.forbidden_scope,
            "validation_criteria": task.validation_criteria,
            "input_files": [
                contract.paths.development_plan,
                contract.paths.changelog,
                contract.paths.app_log,
                contract.paths.orchestration_state_md,
            ],
            "handoff_report_path": task.handoff_report_path,
            "result_path": task.result_path,
            "manual_execution_path": task.manual_execution_path,
        }
        _write_json(input_manifest_path, input_manifest)
        expected_output_path.write_text(
            "\n".join(
                [
                    f"# Expected Output - {task.thread_id}",
                    "",
                    f"Agent: {task.assigned_agent}",
                    f"Purpose: {task.expected_output}",
                    "",
                    "Validation Criteria",
                    *([f"- {criterion}" for criterion in task.validation_criteria] or ["- none"]),
                    "",
                    "Handoff Report",
                    f"- {task.handoff_report_path}",
                    "",
                    "Result File",
                    f"- {task.result_path}",
                ]
            ).rstrip()
            + "\n",
            encoding="utf-8",
        )
        worker_request = {
            "project_root": contract.paths.project_root,
            "task": task.as_request_payload(),
            "contract_summary": contract.summary(),
            "state_snapshot": state_snapshot,
            "extra_context": {
                "run_id": run_id,
                "run_root": str(run_root),
                "planning_artifact": planning_artifact.to_dict(),
                "approval_summary": _approval_summary(tasks),
            },
        }
        _write_json(worker_request_path, worker_request)

        task_prompt_paths[task.thread_id] = str(prompt_path)
        input_manifest_paths[task.thread_id] = str(input_manifest_path)
        expected_output_paths[task.thread_id] = str(expected_output_path)
        worker_request_paths[task.thread_id] = str(worker_request_path)
        output_directory_paths[task.thread_id] = task.output_dir
        task_records.append(
            {
                "thread_id": task.thread_id,
                "assigned_agent": task.assigned_agent,
                "risk_class": task.risk_class,
                "task_prompt_path": str(prompt_path),
                "input_manifest_path": str(input_manifest_path),
                "expected_output_path": str(expected_output_path),
                "worker_request_path": str(worker_request_path),
                "output_dir": task.output_dir,
                "handoff_report_path": task.handoff_report_path,
                "result_path": task.result_path,
                "manual_execution_path": task.manual_execution_path,
            }
        )

    run_log = logs_dir / "run.log"
    if not run_log.exists():
        run_log.write_text(
            "\n".join(
                [
                    f"{_utc_now()} | run | {contract.paths.project_root} | {run_id} | {normalized_mode} | packaged",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    return RunPackage(
        run_id=run_id,
        mode=normalized_mode,
        project_root=contract.paths.project_root,
        run_root=str(run_root),
        manifest_path=str(manifest_path),
        fanout_plan_path=str(fanout_plan_path),
        task_prompt_paths=task_prompt_paths,
        input_manifest_paths=input_manifest_paths,
        expected_output_paths=expected_output_paths,
        worker_request_paths=worker_request_paths,
        output_dirs=output_directory_paths,
        fanin_dir=str(fanin_dir),
        gate_dir=str(gate_dir),
        logs_dir=str(logs_dir),
        manual_execution_required=manual_execution_required,
        codex_cli_available=codex_cli_available,
        task_records=task_records,
    )
