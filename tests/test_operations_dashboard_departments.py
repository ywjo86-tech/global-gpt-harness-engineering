from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

from runtime.ai_office.department_registry import (
    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
    AIOfficeDepartmentRegistryError,
    AIOfficeDepartmentRegistryStore,
    DashboardDepartmentBindingV1,
)
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import (
    OFFICE_REGISTRY_SCHEMA_V1,
    OFFICE_RUN_SCHEMA_V1,
    OfficeRegistryV1,
    OfficeRunV1,
)
from runtime.orchestrator.operations_dashboard_departments import (
    OperationsDashboardDepartmentSourceError,
    read_operations_dashboard_departments,
)
from runtime.orchestrator.operations_dashboard_source import (
    build_live_operations_dashboard_projection,
)


class DashboardDepartmentAdapterTests(unittest.TestCase):
    def _publish_registry(self, root):
        store = AIOfficeDepartmentRegistryStore(root)
        store.publish_registry(
            OfficeRegistryV1(
                OFFICE_REGISTRY_SCHEMA_V1,
                "global-ai-office",
                ("financial", "development"),
                "registry:test",
            )
        )
        return store

    def test_missing_registry_preserves_unbound_behavior(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(read_operations_dashboard_departments(td))

    def test_registry_without_run_is_bound_idle_without_fake_progress(self):
        with tempfile.TemporaryDirectory() as td:
            self._publish_registry(td)

            rows = read_operations_dashboard_departments(td)

            self.assertEqual([row["department_id"] for row in rows], ["financial", "development"])
            self.assertTrue(all(row["binding_state"] == "BOUND" for row in rows))
            self.assertTrue(all(row["status"] == "IDLE" for row in rows))
            self.assertTrue(all(row["progress"] is None for row in rows))
            self.assertTrue(
                all(row["source_state"] == "CANONICAL_REGISTRY_NO_RUN" for row in rows)
            )

    def test_current_office_run_drives_only_its_registered_department(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._publish_registry(td)
            store.publish_current_run(
                OfficeRunV1(
                    OFFICE_RUN_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "run-dev-1",
                    "schedule:none",
                    "EXECUTION_IN_PROGRESS",
                    2,
                )
            )

            rows = read_operations_dashboard_departments(td)
            by_id = {row["department_id"]: row for row in rows}

            self.assertEqual(by_id["financial"]["status"], "IDLE")
            self.assertEqual(by_id["development"]["status"], "RUNNING")
            self.assertEqual(by_id["development"]["current_work"], "run-dev-1")
            self.assertIsNone(by_id["development"]["progress"])
            self.assertEqual(
                by_id["development"]["source_state"],
                "CANONICAL_OFFICE_RUN_V1",
            )

    def test_live_projection_consumes_canonical_department_registry(self):
        with tempfile.TemporaryDirectory() as td:
            self._publish_registry(td)
            projection = build_live_operations_dashboard_projection(
                td,
                now=datetime(2026, 10, 5, 5, tzinfo=timezone.utc),
            )

            self.assertEqual(
                [row["department_id"] for row in projection["departments"]],
                ["financial", "development"],
            )
            self.assertTrue(
                all(row["binding_state"] == "BOUND" for row in projection["departments"])
            )


    def test_corrupt_registry_blocks_live_projection_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._publish_registry(td)
            payload = store.registry_path.read_text()
            store.registry_path.write_text(payload.replace("financial", "tampered", 1))

            with self.assertRaises(AIOfficeDepartmentRegistryError):
                build_live_operations_dashboard_projection(
                    td,
                    now=datetime(2026, 10, 5, 5, tzinfo=timezone.utc),
                )


    def test_explicit_binding_reads_canonical_state_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._publish_registry(td)
            state = AIOfficeStateStore(td, project_id="project-dev", run_id="run-dev-2")
            state.initialize(
                approved_plan_ref="plan:" + "1" * 64,
                baseline_ref="head:" + "a" * 40,
                workflow_state="EXECUTION_IN_PROGRESS",
            )
            store.publish_binding(
                DashboardDepartmentBindingV1(
                    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "project-dev",
                    "run-dev-2",
                    "binding:test",
                )
            )

            rows = read_operations_dashboard_departments(td)
            by_id = {row["department_id"]: row for row in rows}

            self.assertEqual(by_id["development"]["status"], "RUNNING")
            self.assertEqual(
                by_id["development"]["current_work"],
                "project-dev / run-dev-2",
            )
            self.assertEqual(
                by_id["development"]["source_state"],
                "CANONICAL_STATE_BINDING_V1",
            )
            self.assertIsNone(by_id["development"]["progress"])

    def test_direct_run_and_binding_for_same_department_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._publish_registry(td)
            state = AIOfficeStateStore(td, project_id="project-dev", run_id="run-dev-2")
            state.initialize(
                approved_plan_ref="plan:" + "1" * 64,
                baseline_ref="head:" + "a" * 40,
                workflow_state="EXECUTION_IN_PROGRESS",
            )
            store.publish_binding(
                DashboardDepartmentBindingV1(
                    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "project-dev",
                    "run-dev-2",
                    "binding:test",
                )
            )
            store.publish_current_run(
                OfficeRunV1(
                    OFFICE_RUN_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "direct-run",
                    "schedule:none",
                    "EXECUTION_IN_PROGRESS",
                    1,
                )
            )

            with self.assertRaisesRegex(
                OperationsDashboardDepartmentSourceError,
                "ambiguous canonical department sources",
            ):
                read_operations_dashboard_departments(td)


    def test_binding_to_missing_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._publish_registry(td)
            store.publish_binding(
                DashboardDepartmentBindingV1(
                    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "project-missing",
                    "run-missing",
                    "binding:test",
                )
            )

            with self.assertRaisesRegex(
                OperationsDashboardDepartmentSourceError,
                "bound canonical AI Office state invalid",
            ):
                read_operations_dashboard_departments(td)


if __name__ == "__main__":
    unittest.main()
