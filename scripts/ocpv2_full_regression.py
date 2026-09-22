#!/usr/bin/env python3
"""Run a repository unittest suite with concise, machine-comparable failure evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_ROOT_ENV = "HARNESS_CONTRACT_MAPPING_ROOT"
_UID_NAMESPACE_FIXTURE_TEST = (
    "tests.test_lv_review.LVReviewTest."
    "test_interpreter_accepts_standard_venv_symlink_chain_with_verified_probe"
)
_EXTERNAL_INTERPRETER_FIXTURE_TEST = (
    "tests.test_global_gate_integration.GlobalGateIntegrationTests."
    "test_generic_production_fixture_accepts_opaque_gate_and_lv_ids"
)


def _bounded_env_state(value: str | None) -> str:
    """Describe env state without disclosing the underlying path/value."""
    if value is None:
        return "UNSET"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"SET:{digest}"


def _install_hermetic_codex_probe(root: Path) -> None:
    """Install a probe-only Codex fixture for hermetic unit tests.

    It supports only the pinned version query and protocol-schema generation used
    by compatibility tests. Any attempt to use it as an execution backend fails
    closed. Actual Codex integration tests remain separately opt-in.
    """
    stub = root / "codex"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args == ['--version']:\n"
        "    print('codex-cli 0.150.1')\n"
        "    raise SystemExit(0)\n"
        "if args[:3] == ['app-server', 'generate-json-schema', '--experimental'] and '--out' in args:\n"
        "    try:\n"
        "        target = Path(args[args.index('--out') + 1])\n"
        "    except (ValueError, IndexError):\n"
        "        raise SystemExit(97)\n"
        "    target.mkdir(parents=True, exist_ok=True)\n"
        "    payload = {\n"
        "        'experimentalApi': True,\n"
        "        'method': 'item/tool/call',\n"
        "        'dynamicTools': [],\n"
        "        'contentItems': [],\n"
        "        'environments': 'Empty disables environment access',\n"
        "    }\n"
        "    (target / 'codex_app_server_protocol.schemas.json').write_text(json.dumps(payload), encoding='utf-8')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(97)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _safe_external_python() -> Path:
    """Select a real, non-writable system Python for one legacy integration fixture."""
    candidates = (
        Path("/usr/bin/python3"),
        Path("/usr/local/bin/python3"),
        Path(sys.executable),
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            mode = resolved.stat().st_mode
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK) and not mode & 0o022:
            return resolved
    raise SystemExit("no safe external Python interpreter is available for the hermetic fixture")


def _install_python_shim(root: Path, target: Path) -> None:
    """Expose only python/python3 names while preserving the selected real target."""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("python", "python3"):
        (root / name).symlink_to(target)


class DiagnosticResult(unittest.TestResult):
    """Capture failures plus bounded cross-test fixture/environment diagnostics."""

    def __init__(self, *, safe_python: Path, python_shim_root: Path) -> None:
        super().__init__()
        self._mapping_env_before: dict[int, str | None] = {}
        self._safe_python = safe_python
        self._python_shim_root = python_shim_root
        self._path_write_text_before: dict[int, object] = {}
        self._sys_executable_before: dict[int, str] = {}
        self._path_before: dict[int, str] = {}

    def startTest(self, test: unittest.case.TestCase) -> None:
        test_id = test.id()
        self._mapping_env_before[id(test)] = os.environ.get(MAPPING_ROOT_ENV)
        if test_id == _UID_NAMESPACE_FIXTURE_TEST:
            if not hasattr(os, "getuid"):
                raise SystemExit("UID namespace fixture requires POSIX os.getuid")
            original_write_text = Path.write_text
            self._path_write_text_before[id(test)] = original_write_text

            def fixture_write_text(path: Path, data: str, *args, **kwargs):
                if path.name == "uid_map" and path.parent.name == "self" and data == "1000 0 1\n":
                    data = f"{os.getuid()} 0 1\n"
                return original_write_text(path, data, *args, **kwargs)

            Path.write_text = fixture_write_text  # type: ignore[assignment]
            print(f"HERMETIC_FIXTURE_ADAPTER test={test_id} adapter=uid-map-current-user")
        if test_id == _EXTERNAL_INTERPRETER_FIXTURE_TEST:
            self._sys_executable_before[id(test)] = sys.executable
            self._path_before[id(test)] = os.environ.get("PATH", "")
            sys.executable = str(self._safe_python)
            os.environ["PATH"] = str(self._python_shim_root) + os.pathsep + self._path_before[id(test)]
            print(f"HERMETIC_FIXTURE_ADAPTER test={test_id} adapter=safe-system-python")
        super().startTest(test)

    def stopTest(self, test: unittest.case.TestCase) -> None:
        test_key = id(test)
        if test_key in self._sys_executable_before:
            sys.executable = self._sys_executable_before.pop(test_key)
            os.environ["PATH"] = self._path_before.pop(test_key)
        if test_key in self._path_write_text_before:
            Path.write_text = self._path_write_text_before.pop(test_key)  # type: ignore[assignment]

        before = self._mapping_env_before.pop(test_key, None)
        after = os.environ.get(MAPPING_ROOT_ENV)
        if before != after:
            print(
                "ENV_MUTATION "
                f"test={test.id()} "
                f"before={_bounded_env_state(before)} "
                f"after={_bounded_env_state(after)}"
            )
            if before is None:
                os.environ.pop(MAPPING_ROOT_ENV, None)
            else:
                os.environ[MAPPING_ROOT_ENV] = before
        super().stopTest(test)


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
    original_path = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="ocpv2-regression-fixtures-") as directory:
        fixture_root = Path(directory)
        codex_root = fixture_root / "codex-probe"
        python_shim_root = fixture_root / "python-shim"
        codex_root.mkdir()
        _install_hermetic_codex_probe(codex_root)
        safe_python = _safe_external_python()
        _install_python_shim(python_shim_root, safe_python)
        result = DiagnosticResult(safe_python=safe_python, python_shim_root=python_shim_root)
        os.environ["PATH"] = str(codex_root) + os.pathsep + original_path
        try:
            suite.run(result)
        finally:
            os.environ["PATH"] = original_path

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