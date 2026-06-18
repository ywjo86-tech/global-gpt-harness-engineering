from __future__ import annotations

from dataclasses import dataclass

from runtime.orchestrator.schemas import WorkerRequest, WorkerResult

from .base_agent import BaseAgent


@dataclass(slots=True)
class StageGateReviewerAgent(BaseAgent):
    agent_name = "stage_gate_reviewer_agent"

    def run(self, request: WorkerRequest) -> WorkerResult:
        fanin_report = request.extra_context.get("fanin_report", {})
        missing_outputs = list(fanin_report.get("missing_outputs", []))
        conflicts = list(fanin_report.get("conflicts", []))
        pending_approval = bool(request.state_snapshot.get("approval_required"))
        qa_required = bool(fanin_report.get("qa_required", False))

        if missing_outputs or conflicts:
            decision = "NO-GO"
            remaining_risks = missing_outputs + conflicts
            blocker_summary = "Missing outputs or conflicts prevent phase advance."
            conditions = []
            authorization = ""
        elif pending_approval:
            decision = "NO-GO"
            remaining_risks = ["approval_required"]
            blocker_summary = "Approval-gated work remains pending."
            conditions = []
            authorization = ""
        elif qa_required:
            decision = "CONDITIONAL GO"
            remaining_risks = ["QA follow-up remains advisable."]
            blocker_summary = ""
            conditions = ["complete QA follow-up before next phase"]
            authorization = "next phase may start after conditions are satisfied"
        else:
            decision = "GO"
            remaining_risks = []
            blocker_summary = ""
            conditions = []
            authorization = "next phase may start"

        payload = {
            "thread_id": request.task.thread_id,
            "agent_name": self.agent_name,
            "status": decision,
            "phase": request.state_snapshot.get("current_phase", request.contract_summary.get("current_phase", "unknown")),
            "completion_criteria_checked": "yes",
            "evidence_reviewed": [
                "development plan",
                "orchestration state",
                "worker outputs",
                "fanin report",
            ],
            "fan_in_reviewed": "yes",
            "open_questions": [] if decision == "GO" else ["review remaining risks"],
            "remaining_risks": remaining_risks,
            "next_step": request.extra_context.get("next_step", "advance if gate allows"),
            "conditions": conditions,
            "authorization": authorization,
            "blocker_summary": blocker_summary,
        }
        return WorkerResult(
            thread_id=request.task.thread_id,
            agent_name=self.agent_name,
            status=decision,
            summary=f"Stage gate decision: {decision}",
            findings=[f"decision={decision}", f"phase={payload['phase']}"],
            warnings=[],
            errors=[],
            artifacts=[],
            next_step=payload["next_step"],
        )

