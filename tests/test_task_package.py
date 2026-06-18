from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.agents.project_execution_agent import ProjectExecutionAgent
from runtime.agents.project_orchestrator_agent import ProjectOrchestratorAgent
from runtime.orchestrator.contract_loader import load_contract
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.task_package import create_run_package

from tests.helpers import cloned_sample_project


class TaskPackageTest(unittest.TestCase):
    def test_manual_mode_creates_run_package_and_prompt_files(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state = StateStore(project).state
            planning = ProjectOrchestratorAgent().build_plan(contract, state)
            tasks = ProjectExecutionAgent().materialize_tasks(planning, contract, state)

            package = create_run_package(contract, state, planning, tasks, "manual", run_id="run-task-package")

            manifest = json.loads(Path(package.manifest_path).read_text(encoding="utf-8"))
            self.assertTrue(package.manual_execution_required)
            self.assertEqual(manifest["run_id"], package.run_id)
            self.assertTrue(manifest["manual_execution_required"])
            self.assertEqual(len(package.task_prompt_paths), len(tasks))

            for task in tasks:
                prompt_path = Path(package.task_prompt_paths[task.thread_id])
                input_manifest_path = Path(package.input_manifest_paths[task.thread_id])
                expected_output_path = Path(package.expected_output_paths[task.thread_id])
                self.assertTrue(prompt_path.exists())
                self.assertTrue(input_manifest_path.exists())
                self.assertTrue(expected_output_path.exists())
                prompt_text = prompt_path.read_text(encoding="utf-8")
                self.assertIn("Manual Execution Instructions", prompt_text)
                self.assertIn("Safety Warning Protocol", prompt_text)
                self.assertIn(task.thread_id, prompt_text)


if __name__ == "__main__":
    unittest.main()
