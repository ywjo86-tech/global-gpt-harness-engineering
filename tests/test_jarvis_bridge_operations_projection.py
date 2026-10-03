from __future__ import annotations

import unittest

from runtime.jarvis_bridge.bridge_api import refresh_operations_projection
from runtime.jarvis_bridge.state_reader import read_dashboard_state_projection_only
from runtime.orchestrator.engine import OrchestrationEngine
from tests.helpers import cloned_sample_project


class JarvisBridgeOperationsProjectionTests(unittest.TestCase):
    def test_projection_only_reader_does_not_create_bridge_or_queue_files(self):
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            engine.plan(mode="manual", run_id="projection-only")
            before = {p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()}
            snapshot = read_dashboard_state_projection_only(project, run_id="projection-only")
            after = {p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()}
            self.assertEqual(snapshot["project_root"], str(project.resolve()))
            self.assertEqual(after, before)

    def test_bridge_exports_closed_operations_projection(self):
        with cloned_sample_project() as project:
            engine = OrchestrationEngine(project)
            engine.plan(mode="manual", run_id="operations-projection")
            payload = refresh_operations_projection(project, run_id="operations-projection")
            self.assertEqual(payload["schema_version"], "orchestration.operations-read-model.v1")
            serialized = repr(payload).lower()
            for forbidden in ("credential", "token", "raw_effect_payload", "final_assignee"):
                self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
