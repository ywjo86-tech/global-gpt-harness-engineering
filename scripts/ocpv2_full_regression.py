#!/usr/bin/env python3
"""Run the full unittest suite while emitting concise, actionable failure evidence."""
from __future__ import annotations

import sys
import unittest


class DiagnosticResult(unittest.TestResult):
    pass


def main() -> int:
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
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
