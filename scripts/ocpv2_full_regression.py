#!/usr/bin/env python3
"""Run a repository unittest suite with concise, machine-comparable failure evidence."""
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


class DiagnosticResult(unittest.TestResult):
    pass


def build_suite(repo_root: Path) -> unittest.TestSuite:
    """Discover tests with the selected repository root as import authority."""
    repo_root = repo_root.resolve()
    tests_root = repo_root / "tests"
    if not tests_root.is_dir():
        raise SystemExit(f"tests directory not found: {tests_root}")
    root = str(repo_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(repo_root)
    return unittest.defaultTestLoader.discover(
        str(tests_root),
        pattern="test_*.py",
        top_level_dir=root,
    )


def _ids(records: list[tuple[unittest.case.TestCase, str]]) -> list[str]:
    return sorted(test.id() for test, _ in records)


def write_report(path: Path, *, repo_root: Path, result: DiagnosticResult) -> None:
    payload = {
        "repo_root": str(repo_root.resolve()),
        "tests_run": result.testsRun,
        "failure_ids": _ids(result.failures),
        "error_ids": _ids(result.errors),
        "skipped_ids": sorted(test.id() for test, _ in result.skipped),
        "unexpected_success_ids": sorted(test.id() for test in result.unexpectedSuccesses),
        "successful": result.wasSuccessful(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument(
        "--ids-only",
        action="store_true",
        help="print failure/error IDs without full tracebacks",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    suite = build_suite(repo_root)
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
            if not args.ids_only:
                print(traceback_text.rstrip())

    if result.unexpectedSuccesses:
        print("\nUNEXPECTED_SUCCESSES")
        for test in result.unexpectedSuccesses:
            print(test.id())

    if args.report_json is not None:
        write_report(args.report_json, repo_root=repo_root, result=result)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
