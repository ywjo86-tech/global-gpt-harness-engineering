from __future__ import annotations

from dataclasses import dataclass

from runtime.orchestrator.schemas import (
    ExecutionContract,
    PlanningArtifact,
    RuntimeState,
    TaskSlice,
    WorkerRequest,
    WorkerResult,
)

from .base_agent import BaseAgent


@dataclass(slots=True)
class ProjectOrchestratorAgent(BaseAgent):
    agent_name = "project_orchestrator_agent"

    def build_plan(self, contract: ExecutionContract, state: RuntimeState) -> PlanningArtifact:
        from runtime.orchestrator.task_router import route_tasks

        tasks = route_tasks(contract, state)
        selected_agents = sorted({task.assigned_agent for task in tasks})
        routing_notes = [
            "Planning phase is separate from execution phase.",
            "Worker threads remain bounded and file-based.",
            "Execution must consume the persisted plan rather than re-deriving it silently.",
        ]
        return PlanningArtifact(
            current_phase=contract.current_phase,
            planner_agent=self.agent_name,
            thread_count=len(tasks),
            selected_agents=selected_agents,
            routing_notes=routing_notes,
            fanout_ready=len(tasks) >= 2,
            execution_ready=True,
            thread_plan=[task.as_request_payload() for task in tasks],
            planning_summary=f"Prepared {len(tasks)} worker thread(s) for phase '{contract.current_phase}'.",
        )

    def run(self, request: WorkerRequest) -> WorkerResult:
        contract = request.contract_summary
        state = request.state_snapshot
        summary = f"Planning boundary reviewed for phase '{contract.get('current_phase', 'unknown')}'"
        findings = [
            f"Project root: {request.project_root}",
            f"Current phase: {contract.get('current_phase', 'unknown')}",
            f"State keys: {', '.join(sorted(state.keys())) if isinstance(state, dict) else 'unknown'}",
            "This agent only prepares plans; the executor agent materializes tasks and the engine dispatches workers.",
        ]
        return WorkerResult(
            thread_id=request.task.thread_id,
            agent_name=self.agent_name,
            status="completed",
            summary=summary,
            findings=findings,
            warnings=[],
            errors=[],
            artifacts=[],
            next_step="persist the plan and let the engine dispatch workers",
        )
