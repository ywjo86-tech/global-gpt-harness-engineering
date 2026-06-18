from __future__ import annotations

from dataclasses import dataclass

from runtime.orchestrator.approval_gate import GENERAL, classify_task
from runtime.orchestrator.schemas import ExecutionContract, PlanningArtifact, RuntimeState, TaskSlice, WorkerRequest, WorkerResult

from .base_agent import BaseAgent


@dataclass(slots=True)
class ProjectExecutionAgent(BaseAgent):
    agent_name = "project_execution_agent"

    def materialize_tasks(self, planning_artifact: PlanningArtifact | dict[str, object], contract: ExecutionContract, state: RuntimeState) -> list[TaskSlice]:
        artifact = planning_artifact if isinstance(planning_artifact, PlanningArtifact) else PlanningArtifact.from_dict(dict(planning_artifact))
        if not artifact.execution_ready:
            raise ValueError("Execution cannot start before the planning artifact is ready.")
        return [TaskSlice(**task) for task in artifact.thread_plan]

    def segment_tasks(self, tasks: list[TaskSlice], project_root: str) -> tuple[list[TaskSlice], list[TaskSlice]]:
        runnable: list[TaskSlice] = []
        pending: list[TaskSlice] = []
        for task in tasks:
            assessment = classify_task(task, project_root)
            task.risk_class = assessment.classification
            if assessment.classification == GENERAL:
                runnable.append(task)
            else:
                pending.append(task)
        return runnable, pending

    def run(self, request: WorkerRequest) -> WorkerResult:
        planning_artifact = request.extra_context.get("planning_artifact", {})
        thread_plan = planning_artifact.get("thread_plan", []) if isinstance(planning_artifact, dict) else []
        findings = [
            f"Execution boundary materialized {len(thread_plan)} thread(s).",
            "Execution happens only after planning persists the thread plan.",
        ]
        return WorkerResult(
            thread_id=request.task.thread_id,
            agent_name=self.agent_name,
            status="completed",
            summary="Execution boundary reviewed.",
            findings=findings,
            warnings=[],
            errors=[],
            artifacts=[],
            next_step="dispatch materialized worker threads",
        )
