from __future__ import annotations

import importlib
import unittest


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


class TestDiscoveryIntegrityTest(unittest.TestCase):
    def test_lv_execution_package_does_not_reexport_lv_preview_testcase(self) -> None:
        module = importlib.import_module("tests.test_lv_execution_package")
        suite = unittest.TestLoader().loadTestsFromModule(module)
        ids = [case.id() for case in _flatten(suite)]
        duplicates = [test_id for test_id in ids if ".LVPreviewTest." in test_id]
        self.assertEqual(duplicates, [])

    def test_lv_preview_retains_exact_original_test_methods_once(self) -> None:
        module = importlib.import_module("tests.test_lv_preview")
        names = unittest.TestLoader().getTestCaseNames(module.LVPreviewTest)
        self.assertEqual(len(names), 13)
        suite = unittest.TestLoader().loadTestsFromTestCase(module.LVPreviewTest)
        ids = [case.id() for case in _flatten(suite)]
        self.assertEqual(len(ids), 13)
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__": unittest.main()
