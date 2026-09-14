from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.orchestrator.engine import OrchestrationEngine
from runtime.agents.stage_gate_reviewer_agent import StageGateReviewerAgent
from runtime.orchestrator.schemas import FanInReport, TaskSlice, WorkerRequest
from runtime.orchestrator.schemas import RuntimeState
from runtime.orchestrator.stage_gate import run_stage_gate

from tests.helpers import cloned_sample_project


class StageGateTest(unittest.TestCase):
    def test_stage_gate_runs_independently_and_returns_go(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            engine.plan()
            engine.run()
            decision = engine.gate()
            self.assertIn(decision["decision"], {"GO", "CONDITIONAL GO"})
            self.assertTrue((Path(project) / "runtime" / "stage_gate.json").exists())
            payload = json.loads((Path(project) / "runtime" / "stage_gate.json").read_text(encoding="utf-8"))
            self.assertIn(payload["status"], {"GO", "CONDITIONAL GO"})

    def _request(self, authority_review=None, include_authority=False):
        extra_context = {"fanin_report": {}}
        if include_authority:
            extra_context["authority_review"] = authority_review
        return WorkerRequest(
            project_root=".",
            task=TaskSlice(
                thread_id="stage-gate",
                assigned_agent="stage_gate_reviewer_agent",
                input="review",
                expected_output="decision",
                validation_criteria=[],
                editable_scope=[],
                forbidden_scope=[],
                merge_point="boundary",
            ),
            contract_summary={"current_phase": "test"},
            state_snapshot={},
            extra_context=extra_context,
        )

    def test_authority_review_packet_is_optional(self) -> None:
        result = StageGateReviewerAgent().run(self._request())
        self.assertEqual(result.status, "GO")

    def test_incomplete_authority_review_blocks_gate(self) -> None:
        result = StageGateReviewerAgent().run(self._request(
            {
                "decision": "NO-GO", "authority": "test-authority",
                "accepted_evidence_refs": [], "rejected_or_missing_evidence": [],
                "conditions": [], "next_gate": "NOT DEFINED",
                "required_issue_ids": ["ISSUE-1"], "issue_dispositions": {},
            },
            include_authority=True,
        ))
        self.assertEqual(result.status, "NO-GO")
        self.assertIn("authority_review_unresolved:ISSUE-1", result.findings + result.warnings + result.errors)

    def test_resolved_authority_review_allows_gate(self) -> None:
        result = StageGateReviewerAgent().run(self._request(
            {
                "decision": "GO", "authority": "test-authority",
                "accepted_evidence_refs": ["evidence/ref"], "rejected_or_missing_evidence": [],
                "conditions": [], "next_gate": "G-NEXT",
                "required_issue_ids": ["ISSUE-1"], "issue_dispositions": {"ISSUE-1": "RESOLVED"},
            },
            include_authority=True,
        ))
        self.assertEqual(result.status, "GO")

    def test_deferred_authority_review_requires_conditional_gate(self) -> None:
        result = StageGateReviewerAgent().run(self._request(
            {
                "decision": "CONDITIONAL GO", "authority": "test-authority",
                "accepted_evidence_refs": [], "rejected_or_missing_evidence": ["ISSUE-1"],
                "conditions": ["collect actual evidence"], "next_gate": "G-NEXT",
                "required_issue_ids": ["ISSUE-1"], "issue_dispositions": {"ISSUE-1": "DEFERRED"},
            },
            include_authority=True,
        ))
        self.assertEqual(result.status, "CONDITIONAL GO")

    def test_stage_gate_forwards_authority_review_packet(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            engine.plan()
            contract = engine._load_contract()
            fanin = FanInReport(
                threads_received=[], completed_outputs=[], missing_outputs=[],
                failed_workers=[], conflicts=[], duplicate_work=[],
                requirement_coverage="complete", risk_summary=[], qa_required=False,
                next_step_decision="advance", final_handoff_readiness="ready",
            )
            decision = run_stage_gate(
                project,
                contract,
                fanin,
                {
                    "current_phase": "ORCH04",
                    "authority_review": {
                        "decision": "NO-GO",
                        "authority": "test-authority",
                        "accepted_evidence_refs": [],
                        "rejected_or_missing_evidence": ["ISSUE-1"],
                        "conditions": [],
                        "next_gate": "NOT DEFINED",
                        "required_issue_ids": ["ISSUE-1"],
                        "issue_dispositions": {},
                    },
                },
                run_root=str(Path(project) / "runtime" / "orchestrator_runs" / "authority-test"),
            )
            self.assertEqual(decision.decision, "NO-GO")
            request = json.loads((Path(project) / "runtime" / "stage_gate_request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["extra_context"]["authority_review"]["required_issue_ids"], ["ISSUE-1"])

    def test_conditional_authority_persists_gate_context(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            engine.plan()
            contract = engine._load_contract()
            fanin = FanInReport(
                threads_received=[], completed_outputs=[], missing_outputs=[],
                failed_workers=[], conflicts=[], duplicate_work=[],
                requirement_coverage="complete", risk_summary=[], qa_required=False,
                next_step_decision="advance", final_handoff_readiness="ready",
            )
            run_root = Path(project) / "runtime" / "orchestrator_runs" / "conditional-authority-test"
            decision = run_stage_gate(
                project,
                contract,
                fanin,
                {
                    "current_phase": "G-4B-RELEASE-HANDOFF",
                    "authority_review": {
                        "decision": "CONDITIONAL GO",
                        "authority": "test-authority",
                        "accepted_evidence_refs": ["evidence/ref"],
                        "rejected_or_missing_evidence": [],
                        "conditions": ["separate release approval required"],
                        "next_gate": "G-4B-RELEASE-HANDOFF",
                        "required_issue_ids": ["ISSUE-1"],
                        "issue_dispositions": {"ISSUE-1": "RESOLVED"},
                    },
                },
                run_root=str(run_root),
            )
            self.assertEqual(decision.decision, "CONDITIONAL GO")
            persisted = json.loads((run_root / "gate" / "stage_gate_result.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["conditions"], ["complete authority review conditions before next phase"])
            self.assertEqual(persisted["remaining_risks"], ["authority review conditions remain."])
            self.assertIn("authority review packet", persisted["evidence_reviewed"])
            self.assertEqual(persisted["authority_review_checked"], "yes")

    def test_stage_gate_uses_snapshot_phase_in_result(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            engine.plan()
            contract = engine._load_contract()
            fanin = FanInReport(
                threads_received=[], completed_outputs=[], missing_outputs=[],
                failed_workers=[], conflicts=[], duplicate_work=[],
                requirement_coverage="complete", risk_summary=[], qa_required=False,
                next_step_decision="advance", final_handoff_readiness="ready",
            )
            decision = run_stage_gate(
                project,
                contract,
                fanin,
                {"current_phase": "G-4B-RELEASE-HANDOFF"},
                run_root=str(Path(project) / "runtime" / "orchestrator_runs" / "phase-test"),
            )
            self.assertEqual(decision.phase, "G-4B-RELEASE-HANDOFF")

    def test_runtime_state_preserves_authority_review_packet(self) -> None:
        packet = {"authority": "Project Owner", "decision": "CONDITIONAL GO"}
        state = RuntimeState(authority_review=packet)
        restored = RuntimeState.from_dict(state.to_dict())
        self.assertEqual(restored.authority_review, packet)


if __name__ == "__main__":
    unittest.main()
