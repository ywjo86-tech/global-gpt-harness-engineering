from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from runtime.orchestrator.engine import OrchestrationEngine
from tests.helpers import PYTHON_EXE, cloned_sample_project


class CodexRuntimeFlowTest(unittest.TestCase):
    def _run_cli(self, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PYTHON_EXE), "-m", "runtime.orchestrator.cli", *args, "--project", str(project)],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_manual_mode_collect_fanin_and_gate_flow(self) -> None:
        with cloned_sample_project() as project:
            plan = self._run_cli(project, "plan", "--mode", "manual")
            self.assertEqual(plan.returncode, 0, plan.stderr)
            plan_payload = json.loads(plan.stdout)
            run_id = plan_payload["run_id"]
            package = plan_payload["package"]
            self.assertTrue(plan_payload["manual_execution_required"])

            for task_record in package["task_records"]:
                output_dir = Path(task_record["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                result_payload = {
                    "thread_id": task_record["thread_id"],
                    "agent_name": task_record["assigned_agent"],
                    "status": "completed",
                    "summary": f"completed {task_record['thread_id']}",
                    "findings": [],
                    "warnings": [],
                    "errors": [],
                    "artifacts": [],
                    "next_step": "review",
                }
                (output_dir / "result.json").write_text(json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8")
                (output_dir / "handoff_report.md").write_text(f"# Handoff - {task_record['thread_id']}\n", encoding="utf-8")

            collect = self._run_cli(project, "collect", "--run-id", run_id)
            self.assertEqual(collect.returncode, 0, collect.stderr)
            collect_payload = json.loads(collect.stdout)
            self.assertEqual(collect_payload["collection_status"], "complete")

            fanin = self._run_cli(project, "fanin", "--run-id", run_id)
            self.assertEqual(fanin.returncode, 0, fanin.stderr)
            fanin_payload = json.loads(fanin.stdout)
            self.assertEqual(fanin_payload["final_handoff_readiness"], "ready")

            gate = self._run_cli(project, "gate", "--mode", "manual", "--run-id", run_id)
            self.assertEqual(gate.returncode, 0, gate.stderr)
            gate_payload = json.loads(gate.stdout)
            self.assertEqual(gate_payload["status"], "PENDING")

            status = self._run_cli(project, "status", "--run-id", run_id)
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIn("run_manifest", status_payload)
            self.assertIn("collection_report", status_payload)
            self.assertIn("fanin_report", status_payload)
            self.assertIn("stage_gate_result", status_payload)

            run_root = Path(package["run_root"])
            self.assertTrue((run_root / "fanin" / "fanin_prompt.md").exists())
            self.assertTrue((run_root / "fanin" / "fanin_result.json").exists())
            self.assertTrue((run_root / "gate" / "stage_gate_prompt.md").exists())
            self.assertTrue((run_root / "gate" / "stage_gate_result.json").exists())

    def test_run_id_resume_skips_completed_threads(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            plan = engine.plan(mode="mock", run_id="resume-flow")
            run_root = Path(plan["run_root"])

            first = engine.run(mode="mock", run_id="resume-flow")
            self.assertEqual(len(first["resumed_threads"]), 0)
            self.assertEqual(len(first["completed_workers"]), len(plan["package"]["task_records"]))

            victim = plan["package"]["task_records"][0]
            victim_output = Path(victim["output_dir"])
            (victim_output / "result.json").unlink()
            (victim_output / "handoff_report.md").unlink()

            second = engine.run(mode="mock", run_id="resume-flow")
            self.assertEqual(len(second["resumed_threads"]), len(plan["package"]["task_records"]) - 1)
            self.assertEqual(len(second["completed_workers"]), 1)
            self.assertEqual(second["fanin_report"]["final_handoff_readiness"], "ready")
            self.assertTrue((run_root / "fanin" / "fanin_result.json").exists())


if __name__ == "__main__":
    unittest.main()
