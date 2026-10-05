from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.ai_office.department_registry import (
    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
    AIOfficeDepartmentRegistryError,
    AIOfficeDepartmentRegistryStore,
    DashboardDepartmentBindingV1,
)
from runtime.ai_office.workflow import (
    OFFICE_REGISTRY_SCHEMA_V1,
    OFFICE_RUN_SCHEMA_V1,
    OfficeRegistryV1,
    OfficeRunV1,
)


class DepartmentRegistryStoreTests(unittest.TestCase):
    def _registry(self) -> OfficeRegistryV1:
        return OfficeRegistryV1(
            OFFICE_REGISTRY_SCHEMA_V1,
            "global-ai-office",
            ("financial", "development"),
            "registry:test",
        )

    def test_registry_round_trip_and_current_runs(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())
            store.publish_current_run(
                OfficeRunV1(
                    OFFICE_RUN_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "run-dev-1",
                    "schedule:none",
                    "EXECUTION_IN_PROGRESS",
                    4,
                )
            )

            registry = store.load_registry()
            runs = store.load_current_runs()

            self.assertEqual(registry.department_ids, ("financial", "development"))
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].department_id, "development")
            self.assertEqual(runs[0].run_id, "run-dev-1")

    def test_registry_digest_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())
            payload = json.loads(store.registry_path.read_text())
            payload["department_ids"] = ["financial", "development", "research"]
            store.registry_path.write_text(json.dumps(payload))

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "registry digest mismatch",
            ):
                store.load_registry()

    def test_unknown_department_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "department is not registered",
            ):
                store.publish_current_run(
                    OfficeRunV1(
                        OFFICE_RUN_SCHEMA_V1,
                        "global-ai-office",
                        "research",
                        "run-r-1",
                        "schedule:none",
                        "EXECUTION_IN_PROGRESS",
                        1,
                    )
                )

    def test_registry_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = AIOfficeDepartmentRegistryStore(root)
            store.root.mkdir(parents=True)
            target = root / "real-registry.json"
            target.write_text("{}")
            store.registry_path.symlink_to(target)

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "unsafe registry path",
            ):
                store.load_registry()


    def test_registry_root_symlink_is_rejected_for_publish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "_workspace"
            workspace.mkdir()
            target = root / "redirected"
            target.mkdir()
            (workspace / "ai-office-departments").symlink_to(target, target_is_directory=True)
            store = AIOfficeDepartmentRegistryStore(root)

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "unsafe registry root",
            ):
                store.publish_registry(self._registry())

    def test_current_run_revision_type_is_strict(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())
            path = store.publish_current_run(
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
            payload = json.loads(path.read_text())
            payload["revision"] = "2"
            path.write_text(json.dumps(payload))

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "current run contract invalid",
            ):
                store.load_current_runs()


    def test_broken_current_root_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = AIOfficeDepartmentRegistryStore(root)
            store.publish_registry(self._registry())
            store.current_root.symlink_to(
                root / "missing-current-target",
                target_is_directory=True,
            )

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "unsafe current run root",
            ):
                store.load_current_runs()


    def test_explicit_department_binding_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())
            store.publish_binding(
                DashboardDepartmentBindingV1(
                    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "project-dev",
                    "run-dev-1",
                    "binding:test",
                )
            )

            bindings = store.load_bindings()

            self.assertEqual(len(bindings), 1)
            self.assertEqual(bindings[0].department_id, "development")
            self.assertEqual(bindings[0].project_id, "project-dev")
            self.assertEqual(bindings[0].run_id, "run-dev-1")

    def test_binding_for_unregistered_department_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "department is not registered",
            ):
                store.publish_binding(
                    DashboardDepartmentBindingV1(
                        DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                        "global-ai-office",
                        "research",
                        "project-r",
                        "run-r",
                        "binding:test",
                    )
                )


    def test_binding_digest_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = AIOfficeDepartmentRegistryStore(td)
            store.publish_registry(self._registry())
            path = store.publish_binding(
                DashboardDepartmentBindingV1(
                    DASHBOARD_DEPARTMENT_BINDING_SCHEMA_V1,
                    "global-ai-office",
                    "development",
                    "project-dev",
                    "run-dev-1",
                    "binding:test",
                )
            )
            payload = json.loads(path.read_text())
            payload["project_id"] = "tampered-project"
            path.write_text(json.dumps(payload))

            with self.assertRaisesRegex(
                AIOfficeDepartmentRegistryError,
                "binding digest mismatch",
            ):
                store.load_bindings()


if __name__ == "__main__":
    unittest.main()
