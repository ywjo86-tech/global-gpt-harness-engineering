from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.graphify import backend_independence


class BackendIndependenceTests(unittest.TestCase):
    def test_actual_runtime_surface_is_backend_independent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        record = backend_independence.verify_backend_independence(root)
        self.assertTrue(record["verified"], record["violations"])
        self.assertEqual(record["backend_specific_request_fields"], [])

    def test_backend_specific_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bad.py").write_text("import codex_sdk\n", encoding="utf-8")
            with patch.object(backend_independence, "RUNTIME_SURFACE", ("bad.py",)):
                record = backend_independence.verify_backend_independence(root)
            self.assertFalse(record["verified"])
            self.assertTrue(record["violations"])


if __name__ == "__main__":
    unittest.main()
