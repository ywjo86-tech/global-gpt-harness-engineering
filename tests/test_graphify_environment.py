from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poc.graphify import environment


class GraphifyEnvironmentTests(unittest.TestCase):
    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_secret_patterns_are_excluded(self) -> None:
        for name in (".env", ".env.local", "server.pem", "private.key", "id_rsa", "credentials.json"):
            with self.subTest(name=name):
                self.assertTrue(environment._is_secret_name(name))
        self.assertFalse(environment._is_secret_name("README.md"))

    def test_run_root_inside_project_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            environment.prepare_isolated_environment(
                self.project_root,
                self.project_root / "poc" / "graphify" / "invalid-run",
                create_venv=False,
            )

    def test_canonical_manifest_is_clear(self) -> None:
        manifest = environment.canonical_manifest(self.project_root)
        self.assertEqual(manifest["missing_protected_paths"], [])
        self.assertTrue(all(manifest["expected_absent"].values()))
        self.assertEqual(len(manifest["protected_hashes"]), 11)

    def test_disposable_snapshot_preserves_canonical_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "gch-graphify-poc" / "test-run"
            record = environment.prepare_isolated_environment(
                self.project_root,
                run_root,
                create_venv=False,
            )
            self.assertFalse(record["canonical_mutation_detected"])
            self.assertTrue(record["ready_for_package_installation"])
            snapshot = Path(record["source_snapshot"])
            self.assertTrue(snapshot.is_dir())
            self.assertFalse((snapshot / ".git").exists())
            self.assertFalse((snapshot / "runtime" / "orchestrator_runs").exists())


if __name__ == "__main__":
    unittest.main()
