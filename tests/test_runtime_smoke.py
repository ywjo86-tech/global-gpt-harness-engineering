from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from tests.helpers import PYTHON_EXE, cloned_sample_project


class RuntimeSmokeTest(unittest.TestCase):
    def _run_cli(self, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PYTHON_EXE), "-m", "runtime.orchestrator.cli", *args, "--project", str(project)],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_inspect_plan_run_gate_status(self) -> None:
        with cloned_sample_project() as project:
            inspect = self._run_cli(project, "inspect")
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            self.assertIn("contract", inspect.stdout.lower())

            plan = self._run_cli(project, "plan")
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertIn("plan", plan.stdout.lower())

            run = self._run_cli(project, "run")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("fanin_report", run.stdout.lower())

            gate = self._run_cli(project, "gate")
            self.assertEqual(gate.returncode, 0, gate.stderr)
            gate_payload = json.loads((Path(project) / "runtime" / "stage_gate.json").read_text(encoding="utf-8"))
            self.assertIn(gate_payload["status"], {"GO", "CONDITIONAL GO"})

            status = self._run_cli(project, "status")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("state", status.stdout.lower())


if __name__ == "__main__":
    unittest.main()
