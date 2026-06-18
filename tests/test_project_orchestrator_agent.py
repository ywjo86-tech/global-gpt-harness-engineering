from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.agents.project_execution_agent import ProjectExecutionAgent
from runtime.agents.project_orchestrator_agent import ProjectOrchestratorAgent
from runtime.orchestrator.approval_gate import CAUTION, GENERAL
from runtime.orchestrator.contract_loader import load_contract
from runtime.orchestrator.engine import OrchestrationEngine
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.schemas import TaskSlice

from tests.helpers import cloned_sample_project


class ProjectOrchestratorBoundaryTest(unittest.TestCase):
    def test_planning_artifact_is_created_before_execution(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state_store = StateStore(project)
            planner = ProjectOrchestratorAgent()

            planning_artifact = planner.build_plan(contract, state_store.state)
            self.assertGreaterEqual(planning_artifact.thread_count, 2)
            self.assertTrue(planning_artifact.fanout_ready)
            self.assertTrue(planning_artifact.execution_ready)
            executor = ProjectExecutionAgent()
            materialized_tasks = executor.materialize_tasks(planning_artifact, contract, state_store.state)
            self.assertEqual(len(materialized_tasks), planning_artifact.thread_count)
            self.assertEqual({task.assigned_agent for task in materialized_tasks}, set(planning_artifact.selected_agents))

            engine = OrchestrationEngine(project)
            plan_result = engine.plan()
            runtime_state = json.loads((Path(project) / "runtime" / "orchestrator_state.json").read_text(encoding="utf-8"))

            self.assertIn("planning_artifact", plan_result)
            self.assertIn("thread_plan", plan_result["planning_artifact"])
            self.assertTrue(runtime_state["planning_artifact"]["thread_plan"])
            self.assertEqual(runtime_state["planning_artifact"]["planner_agent"], "project_orchestrator_agent")

            run_result = engine.run()
            self.assertIn("fanin_report", run_result)
            self.assertTrue((Path(project) / "runtime" / "fanout_plan.json").exists())

    def test_execution_agent_requires_ready_planning_artifact(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state_store = StateStore(project)
            planner = ProjectOrchestratorAgent()
            planning_artifact = planner.build_plan(contract, state_store.state)
            executor = ProjectExecutionAgent()

            blocked_artifact = planning_artifact.to_dict()
            blocked_artifact["execution_ready"] = False

            with self.assertRaises(ValueError):
                executor.materialize_tasks(blocked_artifact, contract, state_store.state)

    def test_execution_agent_segments_general_and_pending_tasks(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state_store = StateStore(project)
            executor = ProjectExecutionAgent()
            general = TaskSlice(
                thread_id="T-general",
                assigned_agent="documentation_agent",
                input="Write docs for a release note.",
                expected_output="doc notes",
                validation_criteria=["docs"],
                editable_scope=["docs/"],
                forbidden_scope=[],
                merge_point="fanin",
            )
            caution = TaskSlice(
                thread_id="T-caution",
                assigned_agent="documentation_agent",
                input="Update AGENTS.md and docs/harness rules.",
                expected_output="policy notes",
                validation_criteria=["policy"],
                editable_scope=["AGENTS.md", "docs/harness/"],
                forbidden_scope=[],
                merge_point="fanin",
            )
            runnable, pending = executor.segment_tasks([general, caution], str(contract.paths.project_root))
            self.assertEqual(len(runnable), 1)
            self.assertEqual(len(pending), 1)
            self.assertEqual(runnable[0].risk_class, GENERAL)
            self.assertEqual(pending[0].risk_class, CAUTION)


if __name__ == "__main__":
    unittest.main()
