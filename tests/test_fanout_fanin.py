from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.orchestrator.engine import OrchestrationEngine

from tests.helpers import cloned_sample_project


class FanOutFanInTest(unittest.TestCase):
    def test_run_creates_worker_outputs_and_fanin_report(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            plan = engine.plan()
            self.assertGreaterEqual(len(plan), 2)

            run_result = engine.run()
            self.assertIn("fanin_report", run_result)

            runtime_dir = Path(project) / "runtime"
            self.assertTrue((runtime_dir / "fanout_plan.json").exists())
            self.assertTrue((runtime_dir / "fanin_report.json").exists())

            threads_dir = runtime_dir / "threads"
            worker_results = sorted(threads_dir.glob("*/worker_result.json"))
            self.assertGreaterEqual(len(worker_results), 2)
            report = json.loads((runtime_dir / "fanin_report.json").read_text(encoding="utf-8"))
            self.assertIn("completed_outputs", report)
            self.assertEqual(report["final_handoff_readiness"], "ready")


if __name__ == "__main__":
    unittest.main()
