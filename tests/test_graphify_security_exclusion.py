from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poc.graphify.environment import prepare_isolated_environment


class GraphifySecurityExclusionTests(unittest.TestCase):
    def test_snapshot_excludes_secret_patterns(self) -> None:
        project = Path(__file__).resolve().parents[1]
        secret = project / ".env.graphify_test"
        secret.write_text("SECRET=value\n", encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                record = prepare_isolated_environment(
                    project, Path(temp_dir) / "run", create_venv=False
                )
                snapshot = Path(record["source_snapshot"])
                self.assertFalse((snapshot / secret.name).exists())
                self.assertTrue(record["ready_for_package_installation"])
        finally:
            secret.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
