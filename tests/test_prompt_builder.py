from __future__ import annotations

import unittest
from pathlib import Path

from runtime.agents.project_orchestrator_agent import ProjectOrchestratorAgent
from runtime.orchestrator.contract_loader import load_contract
from runtime.orchestrator.prompt_builder import build_fanin_prompt, build_stage_gate_prompt, build_worker_prompt
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.task_package import create_run_package
from runtime.agents.project_execution_agent import ProjectExecutionAgent

from tests.helpers import cloned_sample_project


class PromptBuilderTest(unittest.TestCase):
    def test_worker_prompt_includes_codex_instructions_and_paths(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state = StateStore(project).state
            planning = ProjectOrchestratorAgent().build_plan(contract, state)
            task = ProjectExecutionAgent().materialize_tasks(planning, contract, state)[0]
            package = create_run_package(contract, state, planning, [task], "manual", run_id="run-prompt-test")
            prompt_text = build_worker_prompt(contract.summary(), state.to_dict(), task, package.run_root, "manual")

            self.assertIn(contract.paths.project_root, prompt_text)
            self.assertIn("Safety Warning Protocol", prompt_text)
            self.assertIn("Stage Gate Reviewer", prompt_text)
            self.assertIn(task.thread_id, prompt_text)
            self.assertIn(task.assigned_agent, prompt_text)
            self.assertIn(task.manual_execution_path, prompt_text)

    def test_fanin_and_stage_gate_prompts_include_evidence(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state = StateStore(project).state
            planning = ProjectOrchestratorAgent().build_plan(contract, state)
            task = ProjectExecutionAgent().materialize_tasks(planning, contract, state)[0]
            package = create_run_package(contract, state, planning, [task], "manual", run_id="run-prompt-evidence")
            collection_report = {
                "received_threads": [task.thread_id],
                "completed_outputs": [task.thread_id],
                "missing_outputs": [],
                "failed_workers": [],
                "handoff_reports": [task.handoff_report_path],
                "worker_results": [task.result_path],
                "duplicate_work": [],
                "requirement_coverage": "complete",
                "risk_summary": [],
                "approval_classification_summary": [f"{task.thread_id}:{task.risk_class}"],
                "qa_required": False,
                "next_step_decision": "request stage gate review",
                "final_handoff_readiness": "ready",
            }
            fanin_text = build_fanin_prompt(contract.summary(), state.to_dict(), collection_report, package.run_root)
            gate_text = build_stage_gate_prompt(contract.summary(), state.to_dict(), collection_report, package.run_root, collection_report=collection_report)

            self.assertIn(task.handoff_report_path, fanin_text)
            self.assertIn("request stage gate review", fanin_text)
            self.assertIn(task.handoff_report_path, gate_text)
            self.assertIn("GO", gate_text)


if __name__ == "__main__":
    unittest.main()
