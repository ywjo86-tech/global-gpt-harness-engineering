from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.graphify import memory_independence


class MemoryIndependenceTests(unittest.TestCase):
    def test_actual_runtime_surface_has_no_memory_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        record = memory_independence.verify_memory_independence(root)
        self.assertTrue(record["verified"], record["violations"])
        self.assertFalse(record["obsidian_connected"])
        self.assertFalse(record["notion_connected"])
        self.assertFalse(record["memory_adapter_connected"])

    def test_forbidden_import_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bad.py").write_text("import notion_client\n", encoding="utf-8")
            with patch.object(memory_independence, "RUNTIME_SURFACE", ("bad.py",)):
                record = memory_independence.verify_memory_independence(root)
            self.assertFalse(record["verified"])


if __name__ == "__main__":
    unittest.main()
