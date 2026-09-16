from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.full_mcp.path_policy import WorkspacePathPolicy
from runtime.full_mcp.process_service import ProcessService, ProcessServiceError, ShellPolicy


class ProcessExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / "work").mkdir()
        policy = WorkspacePathPolicy(self.root, read_scopes=(".",), mutable_scopes=("work",))
        self.service = ProcessService(policy, shell_policy=ShellPolicy(allowed_executables=("python3",)))

    def tearDown(self) -> None: self.temp.cleanup()

    def test_explicit_cwd_zero_and_nonzero_results(self) -> None:
        ok = self.service.execute(argv=["python3", "-c", "import os; print(os.getcwd())"], cwd="work", timeout_seconds=5)
        self.assertEqual(ok["exit_code"], 0); self.assertIn("/work", ok["stdout"]); self.assertFalse(ok["timed_out"])
        bad = self.service.execute(argv=["python3", "-c", "import sys; print('x', file=sys.stderr); sys.exit(7)"], cwd="work", timeout_seconds=5)
        self.assertEqual(bad["exit_code"], 7); self.assertEqual(bad["stderr"].strip(), "x")
        self.assertEqual(len(bad["stderr_sha256"]), 64)

    def test_timeout_terminates_process_group(self) -> None:
        result = self.service.execute(argv=["python3", "-c", "import time; time.sleep(3)"], cwd="work", timeout_seconds=1)
        self.assertTrue(result["timed_out"]); self.assertNotEqual(result["exit_code"], 0)


class ProcessIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / "work").mkdir()
        policy = WorkspacePathPolicy(self.root, read_scopes=(".",), mutable_scopes=("work",))
        self.service = ProcessService(policy, shell_policy=ShellPolicy(env_allowlist=("SAFE",), allowed_executables=("python3",), max_output_bytes=64))

    def tearDown(self) -> None: self.temp.cleanup()

    def test_shell_wrappers_unapproved_executable_env_and_cwd_fail_closed(self) -> None:
        cases = [
            dict(argv=["bash", "-c", "echo x"], cwd="work", timeout_seconds=2),
            dict(argv=["echo", "x"], cwd="work", timeout_seconds=2),
            dict(argv=["python3", "-c", "print(1)"], cwd="../outside", timeout_seconds=2),
            dict(argv=["python3", "-c", "print(1)"], cwd="work", timeout_seconds=2, env={"PATH": "/tmp"}),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ProcessServiceError): self.service.execute(**case)

    def test_environment_is_allowlisted_and_not_inherited(self) -> None:
        result = self.service.execute(argv=["python3", "-c", "import os; print(os.getenv('SAFE')); print(os.getenv('HOME'))"], cwd="work", timeout_seconds=2, env={"SAFE": "yes"})
        self.assertEqual(result["stdout"].splitlines(), ["yes", "None"])

    def test_output_bound_fails_closed(self) -> None:
        with self.assertRaises(ProcessServiceError) as caught:
            self.service.execute(argv=["python3", "-c", "print('x'*100)"], cwd="work", timeout_seconds=2)
        self.assertEqual(caught.exception.code, "OUTPUT_LIMIT_EXCEEDED")
