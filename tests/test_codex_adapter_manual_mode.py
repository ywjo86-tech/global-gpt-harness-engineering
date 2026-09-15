from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.codex_adapter import detect_codex_cli, run_task_prompt
from runtime.orchestrator.codex_launcher import (
    NONZERO_EXIT,
    STRUCTURED_OUTPUT_INVALID,
    TIMEOUT,
    CodexCliCapabilityManifest,
    CodexProcessResult,
)
from runtime.orchestrator.execution_modes import CODEX_CLI, MANUAL


def _compatible_manifest(executable: str = "codex") -> CodexCliCapabilityManifest:
    return CodexCliCapabilityManifest(
        executable_detected=True,
        executable_path_fingerprint="test-fingerprint",
        cli_version="codex-cli 0.test",
        exec_subcommand=True,
        stdin_prompt=True,
        cwd_option=True,
        sandbox_option=True,
        output_schema_option=True,
        output_last_message_option=True,
        json_events_option=True,
        probe_returncodes={"codex --version": 0, "codex exec --help": 0},
        status="COMPATIBILITY_VERIFIED",
        _executable_path=executable,
    )


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

    def test_codex_cli_result_is_normalized_from_structured_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {}, clear=True), patch(
            "runtime.orchestrator.codex_adapter.detect_codex_cli",
            return_value=True,
        ), patch(
            "runtime.orchestrator.codex_adapter.probe_codex_cli_capabilities",
            return_value=_compatible_manifest("/usr/bin/codex"),
        ), patch(
            "runtime.orchestrator.codex_launcher.shutil.which",
            return_value="/usr/bin/codex",
        ), patch("runtime.orchestrator.codex_adapter.execute_codex_invocation") as execute:
            root = Path(temp_dir)
            prompt = root / "task_prompt.md"
            prompt.write_text("# Prompt\n", encoding="utf-8")
            output_dir = root / "outputs" / "T1"
            output_dir.mkdir(parents=True, exist_ok=True)

            def _execute(invocation, prompt_text):
                self.assertEqual(prompt_text, "# Prompt\n")
                self.assertNotIn(prompt_text, invocation.argv)
                self.assertIn("exec", invocation.argv)
                self.assertIn("--output-schema", invocation.argv)
                self.assertIn("-o", invocation.argv)
                self.assertEqual(invocation.argv[-1], "-")
                payload = {
                    "thread_id": "T1",
                    "agent_name": "qa_reviewer_agent",
                    "status": "completed",
                    "summary": "normalized",
                    "findings": ["one"],
                    "warnings": ["two"],
                    "errors": [],
                    "artifacts": ["artifact.md"],
                    "next_step": "review",
                }
                Path(invocation.final_output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
                return CodexProcessResult(
                    status="SUCCESS",
                    failure_class=None,
                    returncode=0,
                    timed_out=False,
                    cancelled=False,
                    killed=False,
                    duration_seconds=0.01,
                    stdout="ok",
                    stderr="",
                    final_output_path=invocation.final_output_path,
                    final_output_exists=True,
                    structured_output_valid=True,
                )

            execute.side_effect = _execute

            result = run_task_prompt(prompt, output_dir, CODEX_CLI, project_root=root, required_capabilities=["implementation"])

            self.assertEqual(result["mode"], CODEX_CLI)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["sandbox_mode"], "workspace-write")
            schema = json.loads((output_dir / "codex_output_schema.json").read_text(encoding="utf-8"))
            self.assertIs(schema["additionalProperties"], False)
            self.assertEqual(
                schema["required"],
                [
                    "thread_id",
                    "agent_name",
                    "status",
                    "summary",
                    "findings",
                    "warnings",
                    "errors",
                    "artifacts",
                    "next_step",
                ],
            )
            normalized = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(normalized["thread_id"], "T1")
            self.assertEqual(normalized["agent_name"], "qa_reviewer_agent")
            self.assertEqual(normalized["status"], "completed")
            self.assertEqual(normalized["summary"], "normalized")
            self.assertTrue((output_dir / "handoff_report.md").exists())
            self.assertTrue((output_dir / "worker_handoff.md").exists())

    def test_legacy_override_fails_closed_to_manual_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CODEX_CLI_COMMAND": "codex run --prompt-file prompt.md --output-dir out"},
            clear=True,
        ), patch(
            "runtime.orchestrator.codex_adapter.shutil.which",
            return_value="/usr/bin/codex",
        ), patch(
            "runtime.orchestrator.codex_adapter.probe_codex_cli_capabilities",
            return_value=_compatible_manifest("/usr/bin/codex"),
        ), patch(
            "runtime.orchestrator.codex_launcher.shutil.which",
            return_value="/usr/bin/codex",
        ):
            root = Path(temp_dir)
            prompt = root / "task_prompt.md"
            prompt.write_text("# Prompt\n", encoding="utf-8")
            output_dir = root / "outputs" / "T1"

            result = run_task_prompt(prompt, output_dir, CODEX_CLI, project_root=root)

            self.assertEqual(result["mode"], MANUAL)
            self.assertEqual(result["status"], "manual_fallback")
            self.assertEqual(result["backend_failure_class"], "OVERRIDE_LEGACY_UNSUPPORTED")
            self.assertIn("legacy unsupported", result["reason"])
            self.assertTrue((output_dir / "manual_execution.md").exists())
            self.assertTrue((output_dir / "codex_launcher.log").exists())

    def test_codex_cli_backend_failures_preserve_manual_fallback_taxonomy(self) -> None:
        cases = (
            (NONZERO_EXIT, 19, False, None),
            (TIMEOUT, None, True, None),
            (STRUCTURED_OUTPUT_INVALID, 0, False, False),
        )
        for failure_class, returncode, timed_out, structured_valid in cases:
            with self.subTest(failure_class=failure_class), tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                os.environ,
                {},
                clear=True,
            ), patch(
                "runtime.orchestrator.codex_adapter.detect_codex_cli",
                return_value=True,
            ), patch(
                "runtime.orchestrator.codex_adapter.probe_codex_cli_capabilities",
                return_value=_compatible_manifest("/usr/bin/codex"),
            ), patch(
                "runtime.orchestrator.codex_launcher.shutil.which",
                return_value="/usr/bin/codex",
            ), patch("runtime.orchestrator.codex_adapter.execute_codex_invocation") as execute:
                root = Path(temp_dir)
                prompt = root / "task_prompt.md"
                prompt.write_text("# Prompt\n", encoding="utf-8")
                output_dir = root / "outputs" / "T1"

                def _execute(invocation, _prompt_text):
                    stdout = f"{failure_class} stdout evidence"
                    stderr = f"{failure_class} stderr evidence"
                    return CodexProcessResult(
                        status=failure_class,
                        failure_class=failure_class,
                        returncode=returncode,
                        timed_out=timed_out,
                        cancelled=False,
                        killed=False,
                        duration_seconds=0.01,
                        stdout=stdout,
                        stderr=stderr,
                        final_output_path=invocation.final_output_path,
                        final_output_exists=False,
                        structured_output_valid=structured_valid,
                    )

                execute.side_effect = _execute

                result = run_task_prompt(prompt, output_dir, CODEX_CLI, project_root=root)

                self.assertEqual(result["mode"], MANUAL)
                self.assertEqual(result["status"], "manual_fallback")
                self.assertEqual(result["backend_failure_class"], failure_class)
                self.assertIn(failure_class, result["reason"])
                self.assertTrue((output_dir / "manual_execution.md").exists())
                log_text = (output_dir / "codex_launcher.log").read_text(encoding="utf-8")
                self.assertIn(f"failure_class: {failure_class}", log_text)
                if failure_class == NONZERO_EXIT:
                    self.assertIn("returncode: 19", log_text)
                    self.assertIn("NONZERO_EXIT stdout evidence", log_text)
                    self.assertIn("NONZERO_EXIT stderr evidence", log_text)


if __name__ == "__main__":
    unittest.main()
