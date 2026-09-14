from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from runtime.orchestrator.schemas import WorkerRequest, WorkerResult

from .base_agent import BaseAgent


@dataclass(slots=True)
class StageGateReviewerAgent(BaseAgent):
    agent_name = "stage_gate_reviewer_agent"

    @staticmethod
    def _authority_review_risks(request: WorkerRequest) -> list[str]:
        """Return blocking risks for an explicitly supplied authority packet.

        The stage-gate reviewer consumes authority findings; it does not create
        or override authority decisions.  The packet is optional so existing
        projects retain the pre-existing gate behavior.
        """
        if "authority_review" not in request.extra_context:
            return []
        packet = request.extra_context.get("authority_review")
        if not isinstance(packet, Mapping):
            return ["authority_review_packet_invalid"]

        required_fields = ("decision", "authority", "accepted_evidence_refs",
                           "rejected_or_missing_evidence", "conditions", "next_gate")
        if any(field not in packet for field in required_fields):
            return ["authority_review_packet_incomplete"]
        if packet.get("decision") not in {"GO", "CONDITIONAL GO", "NO-GO"}:
            return ["authority_review_decision_invalid"]
        if not isinstance(packet.get("authority"), str) or not packet["authority"].strip():
            return ["authority_review_authority_missing"]
        if not isinstance(packet.get("next_gate"), str) or not packet["next_gate"].strip():
            return ["authority_review_next_gate_missing"]
        if any(not isinstance(packet.get(field), list) for field in (
                "accepted_evidence_refs", "rejected_or_missing_evidence", "conditions")):
            return ["authority_review_packet_invalid"]

        required_issue_ids = packet.get("required_issue_ids", [])
        dispositions = packet.get("issue_dispositions", {})
        if not isinstance(required_issue_ids, list) or not isinstance(dispositions, Mapping):
            return ["authority_review_packet_invalid"]

        allowed_dispositions = {"RESOLVED", "OPEN", "DEFERRED"}
        unresolved = [
            str(issue_id)
            for issue_id in required_issue_ids
            if str(dispositions.get(issue_id, "")).upper() not in allowed_dispositions
            or str(dispositions.get(issue_id, "")).upper() != "RESOLVED"
        ]
        return [f"authority_review_unresolved:{issue_id}" for issue_id in unresolved]

    def run(self, request: WorkerRequest) -> WorkerResult:
        fanin_report = request.extra_context.get("fanin_report", {})
        missing_outputs = list(fanin_report.get("missing_outputs", []))
        conflicts = list(fanin_report.get("conflicts", []))
        pending_approval = bool(request.state_snapshot.get("approval_required"))
        qa_required = bool(fanin_report.get("qa_required", False))
        authority_review_risks = self._authority_review_risks(request)
        authority_packet = request.extra_context.get("authority_review", {})
        authority_decision = authority_packet.get("decision") if isinstance(authority_packet, Mapping) else None
        authority_no_go = authority_decision == "NO-GO"
        authority_conditional = authority_decision == "CONDITIONAL GO"
        dispositions = authority_packet.get("issue_dispositions", {}) if isinstance(authority_packet, Mapping) else {}
        deferred_only = (
            bool(authority_review_risks)
            and isinstance(dispositions, Mapping)
            and any(str(value).upper() == "DEFERRED" for value in dispositions.values())
            and all(str(value).upper() in {"RESOLVED", "DEFERRED"} for value in dispositions.values())
            and authority_conditional
        )

        if missing_outputs or conflicts or (authority_review_risks and not deferred_only) or authority_no_go:
            decision = "NO-GO"
            remaining_risks = missing_outputs + conflicts + authority_review_risks
            if authority_no_go:
                remaining_risks.append("authority_review_decision_no_go")
            blocker_summary = (
                "Authority review is incomplete."
                if authority_review_risks and not (missing_outputs or conflicts)
                else "Missing outputs, conflicts, or incomplete authority review prevent phase advance."
            )
            conditions = []
            authorization = ""
        elif pending_approval:
            decision = "NO-GO"
            remaining_risks = ["approval_required"]
            blocker_summary = "Approval-gated work remains pending."
            conditions = []
            authorization = ""
        elif qa_required or authority_conditional or deferred_only:
            decision = "CONDITIONAL GO"
            remaining_risks = ["QA follow-up remains advisable."] if qa_required else ["authority review conditions remain."]
            blocker_summary = ""
            conditions = (["complete QA follow-up before next phase"] if qa_required else [])
            if authority_conditional:
                conditions.append("complete authority review conditions before next phase")
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
        if "authority_review" in request.extra_context:
            payload["evidence_reviewed"].append("authority review packet")
            payload["authority_review_checked"] = "yes"
        return WorkerResult(
            thread_id=request.task.thread_id,
            agent_name=self.agent_name,
            status=decision,
            summary=f"Stage gate decision: {decision}",
            findings=[
                f"decision={decision}",
                f"phase={payload['phase']}",
                *authority_review_risks,
            ],
            warnings=[],
            errors=[],
            artifacts=[],
            next_step=payload["next_step"],
        )
