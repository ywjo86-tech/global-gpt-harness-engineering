from pathlib import Path
import os
import tempfile
import unittest

from runtime.orchestrator.read_only_host_diagnostic_contract import DiagnosticPolicy, ReadOnlyDiagnosticRequestV1
from runtime.orchestrator.read_only_host_diagnostic import (
    DiagnosticSecurityError,
    read_path_metadata,
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
            max_bytes=128,
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


if __name__ == "__main__":
    unittest.main()
