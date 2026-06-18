from __future__ import annotations

import unittest
from pathlib import Path

from runtime.jarvis_bridge.bridge_api import (
    get_active_project,
    get_pending_approvals,
    get_recent_logs,
    get_stage_gate_result,
    get_status,
    get_workers,
    refresh_dashboard_snapshot,
    run_command,
)
from runtime.orchestrator.engine import OrchestrationEngine

from tests.helpers import cloned_sample_project


class JarvisBridgeApiTest(unittest.TestCase):
    def test_bridge_snapshot_and_command_dispatch(self) -> None:
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            plan = engine.plan(mode="manual", run_id="jarvis-bridge-api")
            engine.run(mode="manual", run_id="jarvis-bridge-api")

            snapshot = refresh_dashboard_snapshot(project, run_id="jarvis-bridge-api")
            self.assertEqual(snapshot["run_id"], "jarvis-bridge-api")
            self.assertTrue((Path(project) / "runtime" / "jarvis_bridge" / "dashboard_snapshot.json").exists())
            self.assertTrue((Path(project) / "runtime" / "jarvis_bridge" / "dashboard_snapshot.md").exists())

            status = get_status(project, run_id="jarvis-bridge-api")
            self.assertEqual(status["run_id"], "jarvis-bridge-api")
            self.assertTrue(get_active_project(project, run_id="jarvis-bridge-api")["project_root"])
            self.assertIsInstance(get_workers(project, run_id="jarvis-bridge-api"), list)
            self.assertIsInstance(get_pending_approvals(project, run_id="jarvis-bridge-api"), list)
            self.assertIsInstance(get_stage_gate_result(project, run_id="jarvis-bridge-api"), dict)
            self.assertIsInstance(get_recent_logs(project, run_id="jarvis-bridge-api"), dict)

            command = run_command(project, "inspect", run_id="jarvis-bridge-api", execute=True)
            self.assertEqual(command["status"], "executed")
            queued = run_command(project, "status", run_id="jarvis-bridge-api", execute=False)
            self.assertEqual(queued["status"], "queued")
            self.assertTrue((Path(command["command_path"])).exists())
            self.assertTrue((Path(command["result_path"])).exists())
            self.assertTrue(plan["run_root"])


if __name__ == "__main__":
    unittest.main()
