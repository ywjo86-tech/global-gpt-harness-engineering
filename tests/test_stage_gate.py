from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.orchestrator.engine import OrchestrationEngine

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


if __name__ == "__main__":
    unittest.main()
