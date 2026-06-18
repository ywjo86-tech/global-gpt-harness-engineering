from __future__ import annotations

from dataclasses import dataclass

from runtime.orchestrator.schemas import WorkerRequest, WorkerResult

from .base_agent import BaseAgent


@dataclass(slots=True)
class QAReviewerAgent(BaseAgent):
    agent_name = "qa_reviewer_agent"

    def run(self, request: WorkerRequest) -> WorkerResult:
        task = request.task
        findings = [
            f"QA review slice for thread {task.thread_id} completed.",
            f"Validation criteria count: {len(task.validation_criteria)}",
        ]
        warnings = []
        if request.state_snapshot.get("approval_required"):
            warnings.append("Pending approval items remain in the orchestration state.")
        return WorkerResult(
            thread_id=task.thread_id,
            agent_name=self.agent_name,
            status="completed",
            summary="QA review complete.",
            findings=findings,
            warnings=warnings,
            errors=[],
            artifacts=[],
            next_step="request fan-in review",
        )

