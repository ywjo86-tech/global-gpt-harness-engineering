from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.lv_review import _run_tests


class LVReviewDirectoryScopeTest(unittest.TestCase):
    def test_changed_test_inside_owned_directory_is_a_valid_test_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "tests/pkg").mkdir(parents=True)
            (root / "tests/__init__.py").write_text("", encoding="utf-8")
            (root / "tests/pkg/__init__.py").write_text("", encoding="utf-8")
            (root / "app/module.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests/pkg/test_sample.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            results, error = _run_tests(
                root, Path(sys.executable), ["app/module.py", "tests/pkg/"],
                runner="unittest", changed_files=["app/module.py", "tests/pkg/test_sample.py"],
            )
            self.assertIsNone(error)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(not item.get("timeout") for item in results))
            self.assertTrue(all(item.get("exit_code") == 0 for item in results))


    def test_test_only_file_scope_can_run_without_runtime_import_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "tests/__init__.py").write_text("", encoding="utf-8")
            (root / "tests/test_qualification.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            results, error = _run_tests(
                root, Path(sys.executable), ["tests/test_qualification.py"],
                runner="unittest", allow_test_only=True,
                changed_files=["tests/test_qualification.py"],
            )
            self.assertIsNone(error)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(not item.get("timeout") for item in results))
            self.assertTrue(all(item.get("exit_code") == 0 for item in results))

    def test_test_only_directory_scope_stays_inside_owned_tests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests/pkg").mkdir(parents=True)
            (root / "tests/__init__.py").write_text("", encoding="utf-8")
            (root / "tests/pkg/__init__.py").write_text("", encoding="utf-8")
            (root / "tests/pkg/test_one.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            results, error = _run_tests(
                root, Path(sys.executable), ["tests/pkg/"],
                runner="unittest", allow_test_only=True,
            )
            self.assertIsNone(error)
            commands = [item.get("argv") for item in results if item.get("argv")]
            self.assertTrue(commands)
            self.assertIn("tests.pkg.test_one", commands[0])
            self.assertIn("tests.pkg.test_one", commands[1])


if __name__ == "__main__":
    unittest.main()
