from __future__ import annotations

import os
import json
import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.codex_adapter import detect_codex_cli, run_task_prompt
from runtime.orchestrator.execution_modes import CODEX_CLI, MANUAL


class CodexAdapterManualModeTest(unittest.TestCase):
    def test_manual_mode_creates_manual_execution_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt = root / "task_prompt.md"
            prompt.write_text("# Prompt\n", encoding="utf-8")
            output_dir = root / "outputs" / "T1"

            result = run_task_prompt(prompt, output_dir, MANUAL)

            self.assertEqual(result["mode"], MANUAL)
            self.assertTrue((output_dir / "manual_execution.md").exists())
            self.assertEqual(result["status"], "manual_pending")

    def test_codex_cli_missing_gracefully_falls_back_to_manual(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {}, clear=True), patch(
            "runtime.orchestrator.codex_adapter.shutil.which",
            return_value=None,
        ), patch("runtime.orchestrator.codex_adapter.subprocess.run") as mock_run:
            root = Path(temp_dir)
            prompt = root / "task_prompt.md"
            prompt.write_text("# Prompt\n", encoding="utf-8")
            output_dir = root / "outputs" / "T1"

            result = run_task_prompt(prompt, output_dir, CODEX_CLI)

            self.assertEqual(result["mode"], MANUAL)
            self.assertEqual(result["status"], "manual_fallback")
            self.assertTrue((output_dir / "manual_execution.md").exists())
            mock_run.assert_not_called()

    def test_detect_codex_cli_false_without_executable(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("runtime.orchestrator.codex_adapter.shutil.which", return_value=None):
            self.assertFalse(detect_codex_cli())

    def test_codex_cli_result_is_normalized_when_result_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CODEX_CLI_COMMAND": "codex run --prompt-file {prompt} --output-dir {output_dir}"}, clear=False), patch(
            "runtime.orchestrator.codex_adapter.detect_codex_cli",
            return_value=True,
        ), patch(
            "runtime.orchestrator.codex_adapter.subprocess.run",
        ) as mock_run:
            root = Path(temp_dir)
            prompt = root / "task_prompt.md"
            prompt.write_text("# Prompt\n", encoding="utf-8")
            output_dir = root / "outputs" / "T1"
            output_dir.mkdir(parents=True, exist_ok=True)

            def _side_effect(*args, **kwargs):
                payload = {
                    "thread": "T1",
                    "agent": "qa_reviewer_agent",
                    "state": "done",
                    "message": "normalized",
                    "issues": ["one"],
                    "cautions": ["two"],
                    "failures": [],
                    "outputs": ["artifact.md"],
                    "recommendation": "review",
                }
                (output_dir / "result.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                return CompletedProcess(args[0], 0, stdout="ok", stderr="")

            mock_run.side_effect = _side_effect

            result = run_task_prompt(prompt, output_dir, CODEX_CLI)

            self.assertEqual(result["mode"], CODEX_CLI)
            self.assertEqual(result["status"], "completed")
            normalized = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(normalized["thread_id"], "T1")
            self.assertEqual(normalized["agent_name"], "qa_reviewer_agent")
            self.assertEqual(normalized["status"], "completed")
            self.assertEqual(normalized["summary"], "normalized")
            self.assertTrue((output_dir / "handoff_report.md").exists())
            self.assertTrue((output_dir / "worker_handoff.md").exists())


if __name__ == "__main__":
    unittest.main()
