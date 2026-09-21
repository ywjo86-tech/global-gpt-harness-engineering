#!/usr/bin/env python3
"""Run the full unittest suite while emitting concise, actionable failure evidence."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class DiagnosticResult(unittest.TestResult):
    pass


def build_suite() -> unittest.TestSuite:
    """Discover tests with the repository root as the import authority."""
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(REPO_ROOT)
    return unittest.defaultTestLoader.discover(
        str(REPO_ROOT / "tests"),
        pattern="test_*.py",
        top_level_dir=root,
    )


def main() -> int:
    suite = build_suite()
    result = DiagnosticResult()
    suite.run(result)

    print(
        "FULL_REGRESSION_SUMMARY "
        f"run={result.testsRun} failures={len(result.failures)} "
        f"errors={len(result.errors)} skipped={len(result.skipped)}"
    )
    for kind, records in (("FAIL", result.failures), ("ERROR", result.errors)):
        for test, traceback_text in records:
            print(f"\n=== {kind}: {test.id()} ===")
            # Keep the complete unittest traceback for root-cause evidence while avoiding
            # verbose output for every passing test.
            print(traceback_text.rstrip())

    if result.unexpectedSuccesses:
        print("\nUNEXPECTED_SUCCESSES")
        for test in result.unexpectedSuccesses:
            print(test.id())

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
