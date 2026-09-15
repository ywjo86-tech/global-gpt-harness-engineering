from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.codex_launcher import (
    BACKEND_LAUNCHER_COMPATIBILITY_FAILED,
    CANCELLED,
    COMPATIBILITY_VERIFIED,
    COMPATIBILITY_FAILED,
    NONZERO_EXIT,
    OVERRIDE_DANGEROUS_BYPASS,
    OVERRIDE_LEGACY_UNSUPPORTED,
    STRUCTURED_OUTPUT_INVALID,
    TIMEOUT,
    CodexCliCapabilityManifest,
    CodexLauncherError,
    CodexLauncherInvocation,
    execute_codex_invocation,
    probe_codex_cli_capabilities,
    resolve_codex_launcher,
    sandbox_for_capabilities,
)


def _manifest(executable: str, *, json_events: bool = True) -> CodexCliCapabilityManifest:
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
        json_events_option=json_events,
        probe_returncodes={"codex --version": 0, "codex exec --help": 0},
        status=COMPATIBILITY_VERIFIED,
        _executable_path=executable,
    )


class CodexLauncherContractTests(unittest.TestCase):
    def test_probe_requires_current_exec_stdin_output_contract(self) -> None:
        def runner(argv):
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, "codex-cli 0.test\n", "")
            return subprocess.CompletedProcess(
                argv,
                0,
                "Usage: codex exec [OPTIONS]\n"
                "  -              read from stdin\n"
                "  -C, --cd <DIR>\n"
                "  -s, --sandbox <MODE> read-only workspace-write\n"
                "      --output-schema <FILE>\n"
                "  -o, --output-last-message <FILE>\n"
                "      --json\n",
                "",
            )

        manifest = probe_codex_cli_capabilities(executable_resolver=lambda _name: "/usr/bin/codex", runner=runner)

        self.assertEqual(manifest.status, COMPATIBILITY_VERIFIED)
        self.assertEqual(manifest.missing_capabilities, ())
        self.assertTrue(manifest.stdin_prompt)
        self.assertTrue(manifest.output_schema_option)
        self.assertTrue(manifest.output_last_message_option)

    def test_probe_fails_closed_when_exec_help_lacks_required_options(self) -> None:
        def runner(argv):
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, "codex-cli 0.test\n", "")
            return subprocess.CompletedProcess(argv, 0, "Usage: codex exec [OPTIONS]\n", "")

        manifest = probe_codex_cli_capabilities(executable_resolver=lambda _name: "/usr/bin/codex", runner=runner)

        self.assertEqual(manifest.status, BACKEND_LAUNCHER_COMPATIBILITY_FAILED)
        self.assertIn("stdin_prompt", manifest.missing_capabilities)
        self.assertIn("output_schema_option", manifest.missing_capabilities)

    def test_resolve_builds_supported_exec_invocation_without_prompt_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invocation = resolve_codex_launcher(
                _manifest("/usr/bin/codex"),
                root,
                root / "out",
                required_capabilities=["read_only", "reasoning"],
            )

        self.assertEqual(invocation.argv[:2], ("/usr/bin/codex", "exec"))
        self.assertEqual(invocation.argv[-1], "-")
        self.assertIn("--output-schema", invocation.argv)
        self.assertIn("-o", invocation.argv)
        self.assertEqual(invocation.sandbox_mode, "read-only")
        self.assertEqual(invocation.stdin_mode, "prompt_text")
        self.assertTrue(invocation.json_events)

    def test_state_changing_capabilities_select_workspace_write_sandbox(self) -> None:
        self.assertEqual(sandbox_for_capabilities(["read_only"]), "read-only")
        self.assertEqual(sandbox_for_capabilities(["read_only", "implementation"]), "workspace-write")

    def test_legacy_override_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(CodexLauncherError) as caught:
                resolve_codex_launcher(
                    _manifest("/usr/bin/codex"),
                    root,
                    root / "out",
                    override_command="/usr/bin/codex run --prompt-file prompt.md --output-dir out",
                )

        self.assertEqual(caught.exception.failure_class, OVERRIDE_LEGACY_UNSUPPORTED)
        self.assertEqual(caught.exception.status, BACKEND_LAUNCHER_COMPATIBILITY_FAILED)

    def test_compatible_override_is_accepted_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "out"
            schema = output_dir / "schema.json"
            final = output_dir / "last.json"
            command = (
                f"/usr/bin/codex exec -C {root} --sandbox workspace-write "
                f"--output-schema {schema} --output-last-message {final} --json -"
            )

            invocation = resolve_codex_launcher(
                _manifest("/usr/bin/codex"),
                root,
                output_dir,
                required_capabilities=["implementation"],
                output_schema_path=schema,
                final_output_path=final,
                override_command=command,
            )

        self.assertEqual(invocation.argv, tuple(command.split()))
        self.assertEqual(invocation.sandbox_mode, "workspace-write")
        self.assertEqual(invocation.output_schema_path, str(schema))
        self.assertEqual(invocation.final_output_path, str(final))
        self.assertTrue(invocation.json_events)

    def test_dangerous_bypass_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "out" / "codex_output_schema.json"
            final = root / "out" / "codex_last_message.json"
            command = (
                f"/usr/bin/codex exec -C {root} --sandbox read-only "
                f"--output-schema {schema} -o {final} "
                "--dangerously-bypass-approvals-and-sandbox -"
            )
            with self.assertRaises(CodexLauncherError) as caught:
                resolve_codex_launcher(_manifest("/usr/bin/codex"), root, root / "out", override_command=command)

        self.assertEqual(caught.exception.failure_class, OVERRIDE_DANGEROUS_BYPASS)

    def test_execute_invocation_requires_valid_structured_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "last.json"
            invocation = CodexLauncherInvocation(
                argv=(sys.executable, "-c", f"from pathlib import Path; Path({str(final)!r}).write_text('not-json')"),
                stdin_mode="prompt_text",
                sandbox_mode="read-only",
                output_schema_path=str(Path(directory) / "schema.json"),
                final_output_path=str(final),
                json_events=False,
            )

            result = execute_codex_invocation(invocation, "prompt text", timeout_seconds=5)

        self.assertEqual(result.status, STRUCTURED_OUTPUT_INVALID)
        self.assertEqual(result.failure_class, STRUCTURED_OUTPUT_INVALID)
        self.assertFalse(result.structured_output_valid)

    def test_execute_invocation_accepts_valid_structured_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "last.json"
            payload = json.dumps({"status": "completed"})
            invocation = CodexLauncherInvocation(
                argv=(sys.executable, "-c", f"from pathlib import Path; Path({str(final)!r}).write_text({payload!r})"),
                stdin_mode="prompt_text",
                sandbox_mode="read-only",
                output_schema_path=str(Path(directory) / "schema.json"),
                final_output_path=str(final),
                json_events=False,
            )

            result = execute_codex_invocation(invocation, "prompt text", timeout_seconds=5)

        self.assertEqual(result.status, "SUCCESS")
        self.assertTrue(result.structured_output_valid)

    def test_execute_invocation_reports_timeout_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "last.json"
            invocation = CodexLauncherInvocation(
                argv=(sys.executable, "-c", "import time; time.sleep(5)"),
                stdin_mode="prompt_text",
                sandbox_mode="read-only",
                output_schema_path=str(Path(directory) / "schema.json"),
                final_output_path=str(final),
                json_events=False,
            )

            result = execute_codex_invocation(invocation, "prompt text", timeout_seconds=0.05)

        self.assertEqual(result.status, TIMEOUT)
        self.assertEqual(result.failure_class, TIMEOUT)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.cancelled)

    def test_execute_invocation_reports_cancellation_taxonomy(self) -> None:
        calls = 0

        def cancel_after_start() -> bool:
            nonlocal calls
            calls += 1
            return calls > 1

        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "last.json"
            invocation = CodexLauncherInvocation(
                argv=(sys.executable, "-c", "import time; time.sleep(5)"),
                stdin_mode="prompt_text",
                sandbox_mode="read-only",
                output_schema_path=str(Path(directory) / "schema.json"),
                final_output_path=str(final),
                json_events=False,
            )

            result = execute_codex_invocation(invocation, "prompt text", timeout_seconds=5, cancel_check=cancel_after_start)

        self.assertEqual(result.status, CANCELLED)
        self.assertEqual(result.failure_class, CANCELLED)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.timed_out)

    def test_execute_invocation_rejects_nonzero_retry_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "last.json"
            invocation = CodexLauncherInvocation(
                argv=(sys.executable, "-c", "raise SystemExit(99)"),
                stdin_mode="prompt_text",
                sandbox_mode="read-only",
                output_schema_path=str(Path(directory) / "schema.json"),
                final_output_path=str(final),
                json_events=False,
                retry=1,
            )

            result = execute_codex_invocation(invocation, "prompt text", timeout_seconds=5)

        self.assertEqual(result.status, BACKEND_LAUNCHER_COMPATIBILITY_FAILED)
        self.assertEqual(result.failure_class, COMPATIBILITY_FAILED)
        self.assertIsNone(result.returncode)
        self.assertFalse(result.final_output_exists)

    def test_execute_invocation_reports_nonzero_exit_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "last.json"
            invocation = CodexLauncherInvocation(
                argv=(sys.executable, "-c", "raise SystemExit(7)"),
                stdin_mode="prompt_text",
                sandbox_mode="read-only",
                output_schema_path=str(Path(directory) / "schema.json"),
                final_output_path=str(final),
                json_events=False,
                retry=0,
            )

            result = execute_codex_invocation(invocation, "prompt text", timeout_seconds=5)

        self.assertEqual(result.status, NONZERO_EXIT)
        self.assertEqual(result.failure_class, NONZERO_EXIT)
        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
