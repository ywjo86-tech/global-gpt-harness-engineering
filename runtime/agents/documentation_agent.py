from __future__ import annotations

from dataclasses import dataclass

from runtime.orchestrator.schemas import WorkerRequest, WorkerResult

from .base_agent import BaseAgent


@dataclass(slots=True)
class DocumentationAgent(BaseAgent):
    agent_name = "documentation_agent"

    def run(self, request: WorkerRequest) -> WorkerResult:
        task = request.task
        findings = [
            f"Reviewed documentation slice for thread {task.thread_id}.",
            f"Editable scope: {', '.join(task.editable_scope)}",
        ]
        warnings = []
        if "TODO" in task.input or "TBD" in task.input:
            warnings.append("Documentation slice contains placeholder language.")
        return WorkerResult(
            thread_id=task.thread_id,
            agent_name=self.agent_name,
            status="completed",
            summary=f"Documentation review complete for {task.thread_id}.",
            findings=findings,
            warnings=warnings,
            errors=[],
            artifacts=[],
            next_step="merge documentation notes",
        )

