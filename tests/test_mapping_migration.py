from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.mapping_migration import MappingMigrationError, migrate_plan_sha_mapping


OLD, NEW = "a"*64, "b"*64


class MappingMigrationTests(unittest.TestCase):
    def fixture(self, base: Path, name: str) -> tuple[Path, Path, Path]:
        root = base / name; root.mkdir(); registry = base / f"registry-{name}"; registry.mkdir()
        path = registry / f"{name}.json"
        path.write_text(json.dumps({"project_id": name, "canonical_implementation_source": {"path": "PLAN.md", "sha256": OLD},
                                    "approved_source_reference": {"path": "PLAN.md", "sha256": OLD}}))
        return root, registry, path

    def test_existing_second_and_new_project_fixture_compatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ("existing-project", "second-project", "new-project"):
                with self.subTest(name=name):
                    root, registry, path = self.fixture(base, name)
                    result = migrate_plan_sha_mapping(mapping_root=registry, project_root=root, old_plan_sha256=OLD, new_plan_sha256=NEW)
                    self.assertEqual(result["status"], "MIGRATED")
                    payload = json.loads(path.read_text())
                    self.assertEqual(payload["canonical_implementation_source"]["sha256"], NEW)
                    self.assertEqual(payload["plan_sha_migrations"], [{"from": OLD, "to": NEW}])

    def test_partial_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root, registry, path = self.fixture(Path(temp), "project"); before = path.read_bytes()
            with patch("runtime.orchestrator.mapping_migration.os.replace", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    migrate_plan_sha_mapping(mapping_root=registry, project_root=root, old_plan_sha256=OLD, new_plan_sha256=NEW)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(any(item.name.startswith(".project.json.") for item in registry.iterdir()))

    def test_cross_project_traversal_and_symlink_are_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); root, registry, path = self.fixture(base, "project")
            payload = json.loads(path.read_text()); payload["project_id"] = "other"; path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MappingMigrationError, "project_id"):
                migrate_plan_sha_mapping(mapping_root=registry, project_root=root, old_plan_sha256=OLD, new_plan_sha256=NEW)
            path.unlink(); outside = base / "outside.json"; outside.write_text("{}") ; path.symlink_to(outside)
            with self.assertRaisesRegex(MappingMigrationError, "unsafe"):
                migrate_plan_sha_mapping(mapping_root=registry, project_root=root, old_plan_sha256=OLD, new_plan_sha256=NEW)
            alias = base / "alias"; alias.symlink_to(registry, target_is_directory=True)
            with self.assertRaisesRegex(MappingMigrationError, "unsafe"):
                migrate_plan_sha_mapping(mapping_root=alias, project_root=root, old_plan_sha256=OLD, new_plan_sha256=NEW)


if __name__ == "__main__": unittest.main()
