from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from runtime.ai_office.department_registry import (
    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
    AIOfficeDepartmentRegistryError,
    AIOfficeDepartmentRegistryStore,
    DashboardDepartmentBindingV1,
)
from runtime.ai_office.department_registry_cli import main
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.ai_office.workflow import OFFICE_REGISTRY_SCHEMA_V1, OfficeRegistryV1


class DepartmentRegistryCliTests(unittest.TestCase):
    def test_init_registry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            args = [
                "--state-root", td,
                "init",
                "--office-id", "global-ai-office",
                "--registry-ref", "registry:dashboard-v1",
                "--department-id", "financial",
                "--department-id", "development",
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 0)

            registry = AIOfficeDepartmentRegistryStore(td).load_registry()
            self.assertEqual(registry.department_ids, ("financial", "development"))

    def test_init_registry_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(
                OfficeRegistryV1(
                    OFFICE_REGISTRY_SCHEMA_V1,
                    "global-ai-office",
                    ("financial",),
                    "registry:existing",
                )
            )

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "registry already exists with different content",
            ):
                main([
                    "--state-root", td,
                    "init",
                    "--office-id", "global-ai-office",
                    "--registry-ref", "registry:new",
                    "--department-id", "financial",
                    "--department-id", "development",
                ])

            self.assertEqual(store.load_registry().department_ids, ("financial",))

    def test_bind_requires_existing_canonical_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(
                OfficeRegistryV1(
                    OFFICE_REGISTRY_SCHEMA_V1,
                    "global-ai-office",
                    ("development",),
                    "registry:test",
                )
            )

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "binding target state invalid",
            ):
                main([
                    "--state-root", td,
                    "bind",
                    "--department-id", "development",
                    "--project-id", "project-missing",
                    "--run-id", "run-missing",
                    "--binding-ref", "binding:test",
                ])
            self.assertEqual(store.load_bindings(), ())

    def test_bind_persists_verified_target_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(
                OfficeRegistryV1(
                    OFFICE_REGISTRY_SCHEMA_V1,
                    "global-ai-office",
                    ("development",),
                    "registry:test",
                )
            )
            state = AIOfficeStateStore(td, project_id="project-dev", run_id="run-dev")
            state.initialize(
                approved_plan_ref="plan:" + "1" * 64,
                baseline_ref="head:" + "a" * 40,
                workflow_state="EXECUTION_IN_PROGRESS",
            )
            args = [
                "--state-root", td,
                "bind",
                "--department-id", "development",
                "--project-id", "project-dev",
                "--run-id", "run-dev",
                "--binding-ref", "binding:test",
            ]

            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 0)

            binding = store.load_bindings()[0]
            self.assertEqual(binding.project_id, "project-dev")
            self.assertEqual(binding.run_id, "run-dev")

    def test_bind_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(
                OfficeRegistryV1(
                    OFFICE_REGISTRY_SCHEMA_V1,
                    "global-ai-office",
                    ("development",),
                    "registry:test",
                )
            )
            for run in ("run-old", "run-new"):
                state = AIOfficeStateStore(td, project_id="project-dev", run_id=run)
                state.initialize(
                    approved_plan_ref="plan:" + "1" * 64,
                    baseline_ref="head:" + "a" * 40,
                )
            store.publish_binding(
                DashboardDepartmentBindingV1(
                    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "project-dev",
                    "run-old",
                    "binding:old",
                )
            )

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "binding already exists with different content",
            ):
                main([
                    "--state-root", td,
                    "bind",
                    "--department-id", "development",
                    "--project-id", "project-dev",
                    "--run-id", "run-new",
                    "--binding-ref", "binding:new",
                ])

            self.assertEqual(store.load_bindings()[0].run_id, "run-old")

    def test_validate_prints_bounded_summary(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(
                OfficeRegistryV1(
                    OFFICE_REGISTRY_SCHEMA_V1,
                    "global-ai-office",
                    ("financial", "development"),
                    "registry:test",
                )
            )
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--state-root", td, "validate"]), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["status"], "PASS")
            self.assertEqual(value["department_count"], 2)
            self.assertEqual(value["binding_count"], 0)
            self.assertNotIn("state_root", value)


if __name__ == "__main__":
    unittest.main()
