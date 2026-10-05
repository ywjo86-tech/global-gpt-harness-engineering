from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_worker_executor import _candidate_validation_commands


class CandidateValidationInterpreterBindingTests(unittest.TestCase):
    def test_project_venv_command_is_rebound_to_absolute_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interpreter = root / ".venv" / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text("#!/bin/sh\n", encoding="utf-8")
            interpreter.chmod(0o755)
            commands = _candidate_validation_commands(
                root,
                [[".venv/bin/python", "-m", "pytest", "-q"]],
            )
            self.assertEqual(commands[0][0], str(interpreter.absolute()))
            self.assertEqual(commands[0][1:], ["-m", "pytest", "-q"])

    def test_non_python_toolchain_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = _candidate_validation_commands(
                root,
                [["npm", "--prefix", "backend", "test"]],
            )
            self.assertEqual(commands, [["npm", "--prefix", "backend", "test"]])


if __name__ == "__main__":
    unittest.main()
