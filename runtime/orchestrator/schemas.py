from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ProjectPaths:
    project_root: str
    development_plan: str
    changelog: str
    app_log: str
    orchestration_state_md: str
    runtime_dir: str
    orchestrator_runs_dir: str
    runtime_state_json: str
    fanout_plan_json: str
    fanin_report_json: str
    stage_gate_json: str
    threads_dir: str
    reports_dir: str

    @classmethod
    def from_root(cls, project_root: Path) -> "ProjectPaths":
        runtime_dir = project_root / "runtime"
        return cls(
            project_root=str(project_root),
            development_plan=str(project_root / "docs" / "DEVELOPMENT_PLAN.txt"),
            changelog=str(project_root / "CHANGELOG.txt"),
            app_log=str(project_root / "logs" / "app.log"),
            orchestration_state_md=str(project_root / "docs" / "harness" / "orchestration-state.md"),
            runtime_dir=str(runtime_dir),
            orchestrator_runs_dir=str(runtime_dir / "orchestrator_runs"),
            runtime_state_json=str(runtime_dir / "orchestrator_state.json"),
            fanout_plan_json=str(runtime_dir / "fanout_plan.json"),
            fanin_report_json=str(runtime_dir / "fanin_report.json"),
            stage_gate_json=str(runtime_dir / "stage_gate.json"),
            threads_dir=str(runtime_dir / "threads"),
            reports_dir=str(runtime_dir / "reports"),
        )

    def as_path_map(self) -> dict[str, Path]:
        return {key: Path(value) for key, value in asdict(self).items()}


@dataclass(slots=True)
class ExecutionContract:
    paths: ProjectPaths
    development_plan_text: str
    changelog_text: str
    app_log_text: str
    orchestration_state_text: str
    current_phase: str
    missing_files: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "project_root": self.paths.project_root,
            "current_phase": self.current_phase,
            "missing_files": list(self.missing_files),
            "development_plan_path": self.paths.development_plan,
            "changelog_path": self.paths.changelog,
            "app_log_path": self.paths.app_log,
            "orchestration_state_path": self.paths.orchestration_state_md,
        }


@dataclass(slots=True)
class TaskSlice:
    thread_id: str
    assigned_agent: str
    input: str
    expected_output: str
    validation_criteria: list[str]
    editable_scope: list[str]
    forbidden_scope: list[str]
    merge_point: str
    status: str = "pending"
    risk_class: str = "general"
    run_id: str = ""
    run_root: str = ""
    task_prompt_path: str = ""
    input_manifest_path: str = ""
    expected_output_path: str = ""
    worker_request_path: str = ""
    output_dir: str = ""
    handoff_report_path: str = ""
    result_path: str = ""
    manual_execution_path: str = ""

    def as_request_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanningArtifact:
    current_phase: str
    planner_agent: str
    thread_count: int
    selected_agents: list[str]
    routing_notes: list[str]
    fanout_ready: bool
    execution_ready: bool
    thread_plan: list[dict[str, Any]]
    planning_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanningArtifact":
        return cls(**payload)


@dataclass(slots=True)
class WorkerRequest:
    project_root: str
    task: TaskSlice
    contract_summary: dict[str, Any]
    state_snapshot: dict[str, Any]
    extra_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "task": asdict(self.task),
            "contract_summary": self.contract_summary,
            "state_snapshot": self.state_snapshot,
            "extra_context": self.extra_context,
        }


@dataclass(slots=True)
class WorkerResult:
    thread_id: str
    agent_name: str
    status: str
    summary: str
    findings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FanInReport:
    threads_received: list[str]
    completed_outputs: list[str]
    missing_outputs: list[str]
    failed_workers: list[str]
    conflicts: list[str]
    duplicate_work: list[str]
    requirement_coverage: str
    risk_summary: list[str]
    qa_required: bool
    next_step_decision: str
    final_handoff_readiness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StageGateDecision:
    decision: str
    phase: str
    completion_criteria_checked: str
    evidence_reviewed: list[str]
    fan_in_reviewed: str
    open_questions: list[str]
    remaining_risks: list[str]
    next_step: str
    conditions: list[str] = field(default_factory=list)
    authorization: str = ""
    blocker_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.decision
        return payload


@dataclass(slots=True)
class RuntimeState:
    current_phase: str = "unknown"
    active_run_id: str = ""
    run_root: str = ""
    execution_mode: str = "mock"
    manual_execution_required: bool = False
    codex_cli_available: bool = False
    active_threads: list[dict[str, Any]] = field(default_factory=list)
    pending_workers: list[dict[str, Any]] = field(default_factory=list)
    completed_workers: list[dict[str, Any]] = field(default_factory=list)
    failed_workers: list[dict[str, Any]] = field(default_factory=list)
    fanout_status: str = "idle"
    fanin_status: str = "idle"
    collection_status: str = "idle"
    stage_gate_decision: dict[str, Any] = field(default_factory=dict)
    stage_gate_prompt_path: str = ""
    approval_required: bool = False
    next_step: str = ""
    last_updated: str = ""
    fanout_plan: list[dict[str, Any]] = field(default_factory=list)
    fanin_report: dict[str, Any] = field(default_factory=dict)
    collection_report: dict[str, Any] = field(default_factory=dict)
    planning_artifact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeState":
        return cls(**payload)
