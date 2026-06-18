"""Agent registry for the orchestration runtime."""

from .documentation_agent import DocumentationAgent
from .implementation_agent import ImplementationAgent
from .project_execution_agent import ProjectExecutionAgent
from .project_orchestrator_agent import ProjectOrchestratorAgent
from .qa_reviewer_agent import QAReviewerAgent
from .stage_gate_reviewer_agent import StageGateReviewerAgent

AGENT_REGISTRY = {
    DocumentationAgent.agent_name: DocumentationAgent,
    ImplementationAgent.agent_name: ImplementationAgent,
    ProjectExecutionAgent.agent_name: ProjectExecutionAgent,
    ProjectOrchestratorAgent.agent_name: ProjectOrchestratorAgent,
    QAReviewerAgent.agent_name: QAReviewerAgent,
    StageGateReviewerAgent.agent_name: StageGateReviewerAgent,
}


def get_agent_class(agent_name: str):
    try:
        return AGENT_REGISTRY[agent_name]
    except KeyError as exc:
        raise KeyError(f"Unknown agent: {agent_name}") from exc
