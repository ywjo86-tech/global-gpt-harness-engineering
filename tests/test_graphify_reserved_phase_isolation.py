from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poc.graphify.reserved_phase_isolation import verify_reserved_phase_isolation


class ReservedPhaseIsolationTests(unittest.TestCase):
    def test_normal_phase2_module_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ok.py").write_text("def query_graph():\n    return 1\n", encoding="utf-8")
            record = verify_reserved_phase_isolation(root, ["ok.py"])
            self.assertTrue(record["verified"])

    def test_reserved_capabilities_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bad.py").write_text(
                "provider_scoring = True\ninstruction_registry = {}\n", encoding="utf-8"
            )
            record = verify_reserved_phase_isolation(root, ["bad.py"])
            self.assertFalse(record["verified"])
            self.assertEqual(len(record["violations"]), 2)


if __name__ == "__main__":
    unittest.main()
