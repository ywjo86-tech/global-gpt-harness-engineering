from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_isolation import (
    AssetManifest,
    ProjectIsolation,
    ProjectIsolationError,
    route_assets,
    validate_parallel_assignments,
)


class ProjectIsolationTests(unittest.TestCase):
    def fixture(self, base: Path) -> ProjectIsolation:
        namespace = base / "namespaces"
        project = base / "project-one"
        namespace.mkdir()
        project.mkdir()
        return ProjectIsolation(namespace, project, "project-one", "one", {"one": "project-one"})

    def test_actual_io_is_separated_by_namespace_and_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            isolation = self.fixture(Path(directory))
            for kind in ("state", "approval", "artifact", "run", "secret"):
                path = isolation.write_exclusive(kind, "item.bin", kind.encode())
                self.assertEqual(isolation.read(kind, "item.bin"), kind.encode())
                self.assertIn(f"project-one/{kind}", path.as_posix())
                with self.assertRaisesRegex(ProjectIsolationError, "already exists"):
                    isolation.write_exclusive(kind, "item.bin", b"overwrite")

    def test_traversal_and_cross_project_reuse_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            isolation = self.fixture(Path(directory))
            for path in ("../project-two/state.json", "/tmp/x", "a\\b"):
                with self.subTest(path=path), self.assertRaises(ProjectIsolationError):
                    isolation.write_exclusive("state", path, b"x")
            with self.assertRaises(ProjectIsolationError):
                isolation.namespace_path("other-project", "state.json")

    def test_symlinked_root_and_io_component_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            isolation = self.fixture(base)
            outside = base / "outside"
            outside.mkdir()
            (isolation.root / "state").mkdir(parents=True)
            os.symlink(outside, isolation.root / "state/link")
            with self.assertRaisesRegex(ProjectIsolationError, "symlinked"):
                isolation.write_exclusive("state", "link/escape", b"x")
            linked_project = base / "linked-project"
            os.symlink(isolation.project_root, linked_project)
            with self.assertRaisesRegex(ProjectIsolationError, "without symlink"):
                ProjectIsolation(isolation.namespace_root, linked_project, "project-one", "one", {})

    def test_alias_collision_and_project_identity_mismatch_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            namespace = base / "namespaces"; namespace.mkdir()
            project = base / "project-one"; project.mkdir()
            with self.assertRaisesRegex(ProjectIsolationError, "alias collision"):
                ProjectIsolation(namespace, project, "project-one", "one", {"one": "project-two"})
            with self.assertRaisesRegex(ProjectIsolationError, "identity"):
                ProjectIsolation(namespace, project, "project-two", "two", {})

    def test_owned_file_lock_blocks_concurrent_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            isolation = self.fixture(Path(directory))
            isolation.acquire_owned_lock("agent-a", "runtime/a.py")
            with self.assertRaisesRegex(ProjectIsolationError, "already exists"):
                isolation.acquire_owned_lock("agent-b", "runtime/a.py")

    def test_exact_manifest_routing_records_selected_and_excluded_reasons(self) -> None:
        registry = [
            AssetManifest.from_mapping({"asset_id": "exact", "scope": "global", "capabilities": ["review"], "permissions": ["read"], "owned_files": ["runtime/"]}),
            AssetManifest.from_mapping({"asset_id": "review-helper", "scope": "project", "capabilities": ["review-helper"], "permissions": ["read"], "owned_files": ["runtime/"]}),
            AssetManifest.from_mapping({"asset_id": "wrong-scope", "scope": "project", "capabilities": ["review"], "permissions": ["read"], "owned_files": ["docs/"]}),
        ]
        outcome = route_assets(registry, capabilities={"review"}, permissions={"read"}, owned_files=["runtime/a.py"])
        self.assertEqual(outcome["selected"], ["exact"])
        self.assertIn("capability_exact_set_not_satisfied", outcome["excluded"]["review-helper"])
        self.assertIn("owned_file_contract_not_satisfied", outcome["excluded"]["wrong-scope"])
        self.assertFalse(outcome["substring_matching_used"])

    def test_parallel_assignments_require_independence_and_disjoint_files(self) -> None:
        validate_parallel_assignments([
            {"agent_id": "a", "independent": True, "owned_files": ["runtime/a.py"]},
            {"agent_id": "b", "independent": True, "owned_files": ["tests/b.py"]},
        ])
        with self.assertRaisesRegex(ProjectIsolationError, "only independent"):
            validate_parallel_assignments([{"agent_id": "a", "independent": False, "owned_files": ["a.py"]}])
        with self.assertRaisesRegex(ProjectIsolationError, "collision"):
            validate_parallel_assignments([
                {"agent_id": "a", "independent": True, "owned_files": ["runtime/"]},
                {"agent_id": "b", "independent": True, "owned_files": ["runtime/a.py"]},
            ])


if __name__ == "__main__":
    unittest.main()
