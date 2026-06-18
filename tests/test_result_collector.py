from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.agents.project_execution_agent import ProjectExecutionAgent
from runtime.agents.project_orchestrator_agent import ProjectOrchestratorAgent
from runtime.orchestrator.contract_loader import load_contract
from runtime.orchestrator.result_collector import collect_run_outputs
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.task_package import create_run_package

from tests.helpers import cloned_sample_project


class ResultCollectorTest(unittest.TestCase):
    def test_collects_hand_off_reports_and_detects_missing_outputs(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state = StateStore(project).state
            planning = ProjectOrchestratorAgent().build_plan(contract, state)
            tasks = ProjectExecutionAgent().materialize_tasks(planning, contract, state)[:2]
            package = create_run_package(contract, state, planning, tasks, "manual", run_id="run-collector")

            first = tasks[0]
            first_output = Path(package.output_dirs[first.thread_id])
            first_output.mkdir(parents=True, exist_ok=True)
            result_payload = {
                "thread": first.thread_id,
                "agent": first.assigned_agent,
                "state": "done",
                "message": "done",
                "issues": [],
                "cautions": [],
                "failures": [],
                "outputs": [],
                "recommendation": "review",
            }
            (first_output / "result.json").write_text(json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            (first_output / "handoff_report.md").write_text("# Handoff\n", encoding="utf-8")

            report = collect_run_outputs(package.run_root)

            self.assertEqual(report.collection_status, "waiting_manual")
            self.assertIn(first.thread_id, report.completed_outputs)
            self.assertIn(tasks[1].thread_id, report.missing_outputs)
            self.assertTrue(report.handoff_reports)
            self.assertTrue(report.worker_results)
            first_output_report = next(item for item in report.task_outputs if item["thread_id"] == first.thread_id)
            self.assertEqual(first_output_report["status"], "completed")
            self.assertEqual(first_output_report["summary"], "done")
            self.assertTrue((Path(package.run_root) / "fanin" / "collection_report.json").exists())
            self.assertTrue((Path(package.run_root) / "fanin" / "collection_report.md").exists())
            self.assertIn("Collection Summary", (Path(package.run_root) / "fanin" / "collection_report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
