from pathlib import Path
from datetime import datetime, timezone
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runtime.orchestrator.read_only_host_diagnostic_contract import DiagnosticPolicy, ReadOnlyDiagnosticRequestV1
from runtime.orchestrator.read_only_host_diagnostic import (
    DiagnosticError,
    DiagnosticSecurityError,
    DiagnosticUnavailableError,
    collect_repo_snapshot,
    execute_read_only_host_diagnostic,
    read_path_metadata,
    read_user_service_properties,
    read_project_file_range,
)


class ReadOnlyHostDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.policy = DiagnosticPolicy(
            roots={"project": self.root.resolve()},
            user_services=("ocpv2.service",),
            max_bytes=32768,
            max_lines=4,
            timeout_seconds=5,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def file_request(self, relative_path, *, start_line=1, line_count=4):
        return ReadOnlyDiagnosticRequestV1.from_mapping({
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
            "request_id": "REQ-FILE",
            "operation": "project.file_range",
            "root_id": "project",
            "relative_path": relative_path,
            "start_line": start_line,
            "line_count": line_count,
            "service_id": "",
        })

    def metadata_request(self, relative_path):
        return ReadOnlyDiagnosticRequestV1.from_mapping({
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
            "request_id": "REQ-META",
            "operation": "path.metadata",
            "root_id": "project",
            "relative_path": relative_path,
            "start_line": 0,
            "line_count": 0,
            "service_id": "",
        })

    def test_file_range_blocks_intermediate_symlink_escape(self):
        outside = self.base / "outside"; outside.mkdir()
        (outside / "secret.txt").write_text("password=do-not-return\n", encoding="utf-8")
        (self.root / "jump").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(DiagnosticSecurityError, "symlink"):
            read_project_file_range(self.file_request("jump/secret.txt"), self.policy)

    def test_file_range_blocks_final_symlink_and_special_file(self):
        target = self.root / "real.txt"; target.write_text("hello\n", encoding="utf-8")
        (self.root / "link.txt").symlink_to(target)
        with self.assertRaisesRegex(DiagnosticSecurityError, "symlink"):
            read_project_file_range(self.file_request("link.txt"), self.policy)
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(DiagnosticSecurityError, "regular file"):
            read_project_file_range(self.file_request("pipe"), self.policy)

    def test_file_range_blocks_sensitive_names_and_binary(self):
        for name in (".env", "id_rsa", "cert.pem", "secret.key"):
            (self.root / name).write_text("token=abc123\n", encoding="utf-8")
            with self.subTest(name=name), self.assertRaisesRegex(DiagnosticSecurityError, "sensitive"):
                read_project_file_range(self.file_request(name), self.policy)
        (self.root / "binary.bin").write_bytes(b"abc\x00def")
        with self.assertRaisesRegex(DiagnosticSecurityError, "binary"):
            read_project_file_range(self.file_request("binary.bin"), self.policy)

    def test_file_range_redacts_secret_like_values(self):
        (self.root / "safe.txt").write_text("name=ok\ntoken=abc123\npassword: swordfish\n", encoding="utf-8")
        payload = read_project_file_range(self.file_request("safe.txt"), self.policy)
        joined = "\n".join(payload["lines"])
        self.assertIn("[REDACTED]", joined)
        self.assertNotIn("abc123", joined)
        self.assertNotIn("swordfish", joined)
        self.assertTrue(payload["redaction_applied"])

    def test_file_range_redacts_entire_secret_bearing_value_even_with_spaces(self):
        (self.root / "headers.txt").write_text(
            'Authorization: Bearer very-secret-token\npassword: "two word secret"\napi_key=alpha beta gamma\n',
            encoding="utf-8",
        )
        payload = read_project_file_range(self.file_request("headers.txt"), self.policy)
        joined = "\n".join(payload["lines"])
        self.assertTrue(payload["redaction_applied"])
        for secret in ("very-secret-token", "two word secret", "alpha beta gamma"):
            self.assertNotIn(secret, joined)

    def test_file_range_blocks_sensitive_intermediate_path_component(self):
        sensitive = self.root / ".env"
        sensitive.mkdir()
        (sensitive / "visible.txt").write_text("token=must-not-read\n", encoding="utf-8")
        with self.assertRaisesRegex(DiagnosticSecurityError, "sensitive"):
            read_project_file_range(self.file_request(".env/visible.txt"), self.policy)

    def test_file_range_bounds_lines_and_bytes(self):
        (self.root / "many.txt").write_text("\n".join(f"line-{i}-" + "x" * 30 for i in range(1, 10)) + "\n", encoding="utf-8")
        payload = read_project_file_range(self.file_request("many.txt", line_count=20), self.policy)
        self.assertLessEqual(len(payload["lines"]), self.policy.max_lines)
        self.assertLessEqual(len("\n".join(payload["lines"]).encode("utf-8")), self.policy.max_bytes)
        self.assertTrue(payload["truncated"])

    def test_path_metadata_returns_only_allowlisted_fields(self):
        path = self.root / "info.txt"; path.write_text("hello", encoding="utf-8")
        payload = read_path_metadata(self.metadata_request("info.txt"), self.policy)
        self.assertEqual(set(payload), {"exists", "type", "size", "mtime_ns", "mode_class", "canonical_relative_path"})
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["type"], "regular")
        self.assertEqual(payload["canonical_relative_path"], "info.txt")

    def repo_request(self):
        return ReadOnlyDiagnosticRequestV1.from_mapping({
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
            "request_id": "REQ-REPO", "operation": "repo.snapshot", "root_id": "project",
            "relative_path": "", "start_line": 0, "line_count": 0, "service_id": "",
        })

    def test_repo_snapshot_uses_fixed_noninteractive_git_environment(self):
        calls = []
        status_count = 0
        def runner(argv, **kwargs):
            nonlocal status_count
            calls.append((list(argv), dict(kwargs)))
            if "status" in argv:
                status_count += 1
                out = "# branch.oid " + "a" * 40 + "\n# branch.head main\n"
            elif "rev-parse" in argv and "--verify" in argv:
                out = "a" * 40 + "\n"
            elif "--git-dir" in argv or "--git-common-dir" in argv:
                out = ".git\n"
            else:
                out = ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        payload = collect_repo_snapshot(self.repo_request(), self.policy, runner=runner)
        self.assertFalse(payload["stale"])
        self.assertGreaterEqual(status_count, 2)
        required = {
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_PAGER": "cat", "PAGER": "cat",
        }
        for argv, kwargs in calls:
            self.assertEqual(argv[:3], ["git", "-C", str(self.root.resolve())])
            self.assertFalse(kwargs["shell"])
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])
            for key, value in required.items():
                self.assertEqual(kwargs["env"][key], value)

    def test_repo_snapshot_allows_large_internal_index_without_projecting_it(self):
        large_index = "100644 " + "a" * 40 + " 0\ttracked.txt\n"
        large_index *= 2000
        def runner(argv, **kwargs):
            if "status" in argv:
                out = "# branch.oid " + "a" * 40 + "\n# branch.head main\n"
            elif "rev-parse" in argv and "--verify" in argv:
                out = "a" * 40 + "\n"
            elif "rev-parse" in argv:
                out = ".git\n"
            elif "ls-files" in argv:
                out = large_index
            else:
                out = ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        payload = collect_repo_snapshot(self.repo_request(), self.policy, runner=runner)
        self.assertEqual(payload["submodule_paths"], [])
        self.assertNotIn("index", payload)
        self.assertNotIn("tracked.txt", repr(payload))

    def test_repo_snapshot_internal_index_still_has_hard_safety_cap(self):
        def runner(argv, **kwargs):
            if "status" in argv:
                out = "# branch.oid " + "a" * 40 + "\n# branch.head main\n"
            elif "rev-parse" in argv and "--verify" in argv:
                out = "a" * 40 + "\n"
            elif "rev-parse" in argv:
                out = ".git\n"
            elif "ls-files" in argv:
                out = "x" * 101
            else:
                out = ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        with patch("runtime.orchestrator.read_only_host_diagnostic._INTERNAL_GIT_INDEX_MAX_BYTES", 100):
            with self.assertRaisesRegex(DiagnosticUnavailableError, "internal safety cap"):
                collect_repo_snapshot(self.repo_request(), self.policy, runner=runner)

    def test_repo_snapshot_does_not_execute_malicious_diff_driver(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        tracked = self.root / "tracked.txt"
        tracked.write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"], check=True)
        marker_path = self.base / "helper-ran"
        helper = self.base / "evil.sh"
        helper.write_text(f"#!/bin/sh\ntouch {marker_path}\nexit 0\n", encoding="utf-8")
        helper.chmod(0o700)
        subprocess.run(["git", "-C", str(self.root), "config", "diff.evil.command", str(helper)], check=True)
        (self.root / ".gitattributes").write_text("*.txt diff=evil\n", encoding="utf-8")
        tracked.write_text("two\n", encoding="utf-8")
        payload = collect_repo_snapshot(self.repo_request(), self.policy)
        self.assertFalse(marker_path.exists())
        self.assertIn("tracked.txt", payload["worktree_name_status"])

    def test_repo_snapshot_marks_concurrent_status_drift_stale(self):
        status_outputs = iter([
            "# branch.oid " + "a" * 40 + "\n# branch.head main\n",
            "# branch.oid " + "a" * 40 + "\n# branch.head main\n? changed.txt\n",
        ])
        def runner(argv, **kwargs):
            if "status" in argv:
                out = next(status_outputs)
            elif "rev-parse" in argv and "--verify" in argv:
                out = "a" * 40 + "\n"
            elif "rev-parse" in argv:
                out = ".git\n"
            else:
                out = ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        self.assertTrue(collect_repo_snapshot(self.repo_request(), self.policy, runner=runner)["stale"])



    def service_request(self, service_id="ocpv2.service"):
        return ReadOnlyDiagnosticRequestV1.from_mapping({
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
            "request_id": "REQ-SVC", "operation": "user_service.properties", "root_id": "",
            "relative_path": "", "start_line": 0, "line_count": 0, "service_id": service_id,
        })

    def test_user_service_properties_blocks_non_allowlisted_unit(self):
        request = self.service_request("other.service")
        with self.assertRaisesRegex(DiagnosticSecurityError, "allowlisted"):
            read_user_service_properties(request, self.policy)

    def test_user_service_properties_uses_exact_fixed_argv(self):
        calls = []
        output = "\n".join([
            "ActiveState=active",
            "SubState=running",
            "Result=success",
            "ExecMainStatus=0",
            "InvocationID=abc123",
        ]) + "\n"
        def runner(argv, **kwargs):
            calls.append((list(argv), dict(kwargs)))
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
        payload = read_user_service_properties(self.service_request(), self.policy, runner=runner)
        self.assertEqual(calls[0][0], [
            "systemctl", "--user", "show", "ocpv2.service", "--no-pager",
            "--property=ActiveState", "--property=SubState", "--property=Result",
            "--property=ExecMainStatus", "--property=InvocationID",
        ])
        kwargs = calls[0][1]
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertFalse(kwargs["check"])
        self.assertEqual(payload, {
            "ActiveState": "active", "SubState": "running", "Result": "success",
            "ExecMainStatus": "0", "InvocationID": "abc123",
        })

    def test_user_service_properties_rejects_duplicate_or_malformed_output(self):
        for output in (
            "ActiveState=active\nActiveState=inactive\n",
            "ActiveState=active\nmalformed\n",
        ):
            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
            with self.subTest(output=output), self.assertRaises(DiagnosticError):
                read_user_service_properties(self.service_request(), self.policy, runner=runner)

    def test_user_service_properties_nonzero_is_unavailable_without_stderr_leak(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="token=do-not-return")
        with self.assertRaisesRegex(DiagnosticUnavailableError, "systemd user service unavailable") as ctx:
            read_user_service_properties(self.service_request(), self.policy, runner=runner)
        self.assertNotIn("do-not-return", str(ctx.exception))



    def test_dispatcher_classifies_content_and_provenance(self):
        path = self.root / "note.txt"
        path.write_text("token=abc123\nhello\n", encoding="utf-8")
        result = execute_read_only_host_diagnostic(
            self.file_request("note.txt"),
            self.policy,
            project_id="P1",
            correlation_id="CORR-1",
            source_sha="a" * 40,
            runtime_sha="b" * 40,
            now=lambda: datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data_class, "DIAG_CONTENT")
        self.assertEqual(result.execution_owner, "NONE")
        self.assertTrue(result.redaction_applied)
        self.assertNotIn("abc123", str(result.payload))
        self.assertTrue(result.captured_at)
        self.assertTrue(result.payload_hash)

    def test_dispatcher_marks_truncated_content_partial(self):
        path = self.root / "many-lines.txt"
        path.write_text("\n".join(f"line-{i}" for i in range(20)) + "\n", encoding="utf-8")
        result = execute_read_only_host_diagnostic(
            self.file_request("many-lines.txt", line_count=20),
            self.policy,
            project_id="P1",
            correlation_id="CORR-2",
            source_sha="a" * 40,
            runtime_sha="b" * 40,
        )
        self.assertEqual(result.status, "PARTIAL")
        self.assertTrue(result.truncated)

    def test_dispatcher_maps_policy_denial_to_blocked(self):
        (self.root / ".env").write_text("token=abc123\n", encoding="utf-8")
        result = execute_read_only_host_diagnostic(
            self.file_request(".env"),
            self.policy,
            project_id="P1",
            correlation_id="CORR-3",
            source_sha="a" * 40,
            runtime_sha="b" * 40,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertNotIn("abc123", str(result.payload))

    def test_dispatcher_maps_service_failure_to_unavailable(self):
        def unavailable(request, policy):
            raise DiagnosticUnavailableError("systemd user service unavailable")
        with patch("runtime.orchestrator.read_only_host_diagnostic.read_user_service_properties", unavailable):
            result = execute_read_only_host_diagnostic(
                self.service_request(),
                self.policy,
                project_id="P1",
                correlation_id="CORR-4",
                source_sha="a" * 40,
                runtime_sha="b" * 40,
            )
        self.assertEqual(result.status, "UNAVAILABLE")

    def test_dispatcher_never_promotes_stale_repo_snapshot_to_ok(self):
        def stale(request, policy):
            return {"stale": True, "truncated": False, "redaction_applied": False}
        with patch("runtime.orchestrator.read_only_host_diagnostic.collect_repo_snapshot", stale):
            result = execute_read_only_host_diagnostic(
                self.repo_request(),
                self.policy,
                project_id="P1",
                correlation_id="CORR-5",
                source_sha="a" * 40,
                runtime_sha="b" * 40,
            )
        self.assertEqual(result.status, "STALE")
        self.assertEqual(result.freshness, "STALE")



if __name__ == "__main__":
    unittest.main()
