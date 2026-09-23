from pathlib import Path
import hashlib
import json
import os
import tempfile
import unittest

from runtime.orchestrator.read_only_host_diagnostic_contract import (
    DiagnosticContractError,
    DiagnosticPolicy,
    ReadOnlyDiagnosticRequestV1,
    ReadOnlyDiagnosticResultV1,
    diagnostic_feature_enabled,
)


class DiagnosticContractTests(unittest.TestCase):
    def repo_request(self):
        return {
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
            "request_id": "REQ-1",
            "operation": "repo.snapshot",
            "root_id": "jarvis-assistant",
            "relative_path": "",
            "start_line": 0,
            "line_count": 0,
            "service_id": "",
        }

    def write_policy(self, base: Path, payload: dict) -> Path:
        path = base / "policy.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
        return path

    def valid_policy(self, root: Path) -> dict:
        return {
            "schema_version": "orchestration.read-only-host-diagnostic-config.v1",
            "roots": {"jarvis-assistant": str(root)},
            "user_services": ["ocpv2.service"],
            "limits": {"max_bytes": 32768, "max_lines": 400, "timeout_seconds": 10},
        }

    def test_repo_snapshot_request_rejects_unused_fields(self):
        request = ReadOnlyDiagnosticRequestV1.from_mapping(self.repo_request())
        self.assertEqual(request.operation, "repo.snapshot")
        with self.assertRaisesRegex(DiagnosticContractError, "unused request field"):
            ReadOnlyDiagnosticRequestV1.from_mapping({**request.to_dict(), "relative_path": "README.md"})

    def test_file_range_requires_relative_path_and_positive_range(self):
        payload = {**self.repo_request(), "operation": "project.file_range", "relative_path": "README.md", "start_line": 1, "line_count": 10}
        request = ReadOnlyDiagnosticRequestV1.from_mapping(payload)
        self.assertEqual(request.relative_path, "README.md")
        for change in ({"relative_path": ""}, {"start_line": 0}, {"line_count": 0}, {"service_id": "ocpv2.service"}):
            with self.subTest(change=change), self.assertRaises(DiagnosticContractError):
                ReadOnlyDiagnosticRequestV1.from_mapping({**payload, **change})

    def test_file_range_rejects_absolute_and_traversal_paths(self):
        payload = {**self.repo_request(), "operation": "project.file_range", "relative_path": "README.md", "start_line": 1, "line_count": 10}
        for unsafe in ("/etc/passwd", "../secret.txt", "sub/../../secret.txt"):
            with self.subTest(path=unsafe), self.assertRaisesRegex(DiagnosticContractError, "unsafe relative path"):
                ReadOnlyDiagnosticRequestV1.from_mapping({**payload, "relative_path": unsafe})

    def test_feature_flag_accepts_only_explicit_true(self):
        self.assertFalse(diagnostic_feature_enabled({}))
        self.assertFalse(diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "false"}))
        self.assertTrue(diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true"}))
        with self.assertRaises(DiagnosticContractError):
            diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "yes"})

    def test_policy_loads_secure_regular_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "root"; root.mkdir()
            policy = DiagnosticPolicy.load(self.write_policy(base, self.valid_policy(root)))
            self.assertEqual(policy.roots["jarvis-assistant"], root.resolve())
            self.assertEqual(policy.user_services, ("ocpv2.service",))
            self.assertEqual((policy.max_bytes, policy.max_lines, policy.timeout_seconds), (32768, 400, 10))

    def test_policy_rejects_unsafe_roots_services_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / "root"; root.mkdir()
            cases = [
                {"roots": {"../escape": str(root)}},
                {"roots": {"jarvis-assistant": "relative/root"}},
                {"roots": {"jarvis-assistant": str(base / "missing")}},
                {"user_services": ["ocpv2.service", "ocpv2.service"]},
                {"user_services": ["../bad.service"]},
                {"limits": {"max_bytes": 32769, "max_lines": 400, "timeout_seconds": 10}},
                {"limits": {"max_bytes": 32768, "max_lines": 401, "timeout_seconds": 10}},
                {"limits": {"max_bytes": 32768, "max_lines": 400, "timeout_seconds": 16}},
            ]
            baseline = self.valid_policy(root)
            for change in cases:
                payload = dict(baseline)
                payload.update(change)
                with self.subTest(change=change), self.assertRaises(DiagnosticContractError):
                    DiagnosticPolicy.load(self.write_policy(base, payload))

    def test_policy_rejects_symlink_and_group_writable_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / "root"; root.mkdir()
            real = self.write_policy(base, self.valid_policy(root))
            link = base / "policy-link.json"; link.symlink_to(real)
            with self.assertRaisesRegex(DiagnosticContractError, "symlink"):
                DiagnosticPolicy.load(link)
            real.chmod(0o620)
            with self.assertRaisesRegex(DiagnosticContractError, "writable"):
                DiagnosticPolicy.load(real)

    def test_policy_rejects_symlink_registered_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); real_root = base / "real"; real_root.mkdir()
            linked_root = base / "linked"; linked_root.symlink_to(real_root, target_is_directory=True)
            with self.assertRaisesRegex(DiagnosticContractError, "root.*symlink"):
                DiagnosticPolicy.load(self.write_policy(base, self.valid_policy(linked_root)))

    def test_result_hashes_already_sanitized_payload_and_rejects_bad_class(self):
        payload = {"branch": "main", "dirty": False}
        result = ReadOnlyDiagnosticResultV1.build(
            request_id="REQ-1", correlation_id="CORR-1", project_id="P1",
            root_id="jarvis-assistant", operation_id="repo.snapshot",
            authorization_decision="ALLOW", captured_at="2026-09-23T00:00:00+00:00",
            freshness="CURRENT", source_sha="a" * 40, runtime_sha="b" * 40,
            data_class="DIAG_SUMMARY", redaction_applied=False, truncated=False,
            status="OK", error_class="", payload=payload,
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(result.payload_hash, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(result.execution_owner, "NONE")
        with self.assertRaises(DiagnosticContractError):
            ReadOnlyDiagnosticResultV1.build(
                request_id="REQ-1", correlation_id="CORR-1", project_id="P1",
                root_id="jarvis-assistant", operation_id="repo.snapshot",
                authorization_decision="ALLOW", captured_at="2026-09-23T00:00:00+00:00",
                freshness="CURRENT", source_sha="a" * 40, runtime_sha="b" * 40,
                data_class="SECRET_DATA", redaction_applied=False, truncated=False,
                status="OK", error_class="", payload=payload,
            )


if __name__ == "__main__":
    unittest.main()
