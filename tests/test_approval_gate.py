from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.approval_gate import CAUTION, DANGEROUS, GENERAL, classify_task
from runtime.orchestrator.engine import OrchestrationEngine
from runtime.orchestrator.schemas import PlanningArtifact, TaskSlice
from runtime.agents.project_orchestrator_agent import ProjectOrchestratorAgent

from tests.helpers import cloned_sample_project


class ApprovalGateTest(unittest.TestCase):
    def test_classifies_general_caution_and_dangerous_tasks(self) -> None:
        general = TaskSlice(
            thread_id="T1",
            assigned_agent="documentation_agent",
            input="Write documentation in project files.",
            expected_output="doc notes",
            validation_criteria=["docs"],
            editable_scope=["docs/"],
            forbidden_scope=[],
            merge_point="fan-in",
        )
        caution = TaskSlice(
            thread_id="T2",
            assigned_agent="documentation_agent",
            input="Update AGENTS.md and existing docs/harness guidance.",
            expected_output="policy note",
            validation_criteria=["policy"],
            editable_scope=["AGENTS.md", "docs/harness/"],
            forbidden_scope=[],
            merge_point="fan-in",
        )
        dangerous = TaskSlice(
            thread_id="T3",
            assigned_agent="implementation_agent",
            input="Delete files outside workspace and push changes.",
            expected_output="danger note",
            validation_criteria=["safety"],
            editable_scope=["../outside.txt"],
            forbidden_scope=[],
            merge_point="fan-in",
        )
        self.assertEqual(classify_task(general).classification, GENERAL)
        self.assertEqual(classify_task(caution).classification, CAUTION)
        self.assertEqual(classify_task(dangerous, "C:/Users/ywjo8/Documents/AI-Workspace/global-gpt-harness-engineering").classification, DANGEROUS)

    def test_caution_and_dangerous_tasks_stay_pending_without_approval(self) -> None:
        with cloned_sample_project() as project:
            caution_task = TaskSlice(
                thread_id="T1",
                assigned_agent="documentation_agent",
                input="Update AGENTS.md and existing docs/harness guidance.",
                expected_output="policy note",
                validation_criteria=["policy"],
                editable_scope=["AGENTS.md", "docs/harness/"],
                forbidden_scope=[],
                merge_point="fan-in",
            )
            planning_artifact = PlanningArtifact(
                current_phase="phase-1",
                planner_agent="project_orchestrator_agent",
                thread_count=1,
                selected_agents=["documentation_agent"],
                routing_notes=["planning boundary"],
                fanout_ready=False,
                execution_ready=True,
                thread_plan=[caution_task.as_request_payload()],
                planning_summary="Prepared 1 worker thread for approval-gated documentation work.",
            )
            with patch.object(ProjectOrchestratorAgent, "build_plan", return_value=planning_artifact):
                engine = OrchestrationEngine(project)
                result = engine.run()
                self.assertTrue(result["pending_workers"])
                self.assertTrue((Path(project) / "runtime" / "orchestrator_state.json").exists())

            with patch.object(ProjectOrchestratorAgent, "build_plan", return_value=planning_artifact):
                engine = OrchestrationEngine(project)
                with self.assertRaises(PermissionError):
                    engine.approve("위험 확인 후 승인")


if __name__ == "__main__":
    unittest.main()
