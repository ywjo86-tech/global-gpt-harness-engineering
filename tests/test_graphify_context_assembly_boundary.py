from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poc.graphify.context_assembly_boundary import verify_context_assembly_boundary


class ContextAssemblyBoundaryTests(unittest.TestCase):
    def test_normal_repository_module_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ok.py").write_text("def find_symbol():\n    return 1\n", encoding="utf-8")
            record = verify_context_assembly_boundary(root, ["ok.py"])
            self.assertTrue(record["verified"])

    def test_context_assembly_symbol_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bad.py").write_text("def project_context_assembly():\n    pass\n", encoding="utf-8")
            record = verify_context_assembly_boundary(root, ["bad.py"])
            self.assertFalse(record["verified"])
            self.assertTrue(record["violations"])


if __name__ == "__main__":
    unittest.main()
