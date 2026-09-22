from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from runtime.orchestrator.read_only_host_diagnostic_contract import (
    CONFIG_SCHEMA,
    REQUEST_SCHEMA,
    DiagnosticContractError,
    DiagnosticPolicy,
    ReadOnlyDiagnosticRequestV1,
    ReadOnlyDiagnosticResultV1,
    diagnostic_feature_enabled,
)


class DiagnosticContractTests(unittest.TestCase):
    def request(self, **changes):
        value = {
            "schema_version": REQUEST_SCHEMA,
            "request_id": "REQ-1",
            "operation": "repo.snapshot",
            "root_id": "jarvis-assistant",
            "relative_path": "",
            "start_line": 0,
            "line_count": 0,
            "service_id": "",
        }
        value.update(changes)
        return value

    def test_repo_snapshot_request_rejects_unused_fields(self):
        request = ReadOnlyDiagnosticRequestV1.from_mapping(self.request())
        self.assertEqual(request.operation, "repo.snapshot")
        with self.assertRaisesRegex(DiagnosticContractError, "unused request field"):
            ReadOnlyDiagnosticRequestV1.from_mapping({**request.to_dict(), "relative_path": "README.md"})

    def test_operation_specific_request_shapes(self):
        file_req = ReadOnlyDiagnosticRequestV1.from_mapping(self.request(
            operation="project.file_range", relative_path="README.md", start_line=1, line_count=10,
        ))
        self.assertEqual(file_req.line_count, 10)
        meta_req = ReadOnlyDiagnosticRequestV1.from_mapping(self.request(
            operation="path.metadata", relative_path="README.md",
        ))
        self.assertEqual(meta_req.relative_path, "README.md")
        svc_req = ReadOnlyDiagnosticRequestV1.from_mapping(self.request(
            operation="user_service.properties", root_id="", service_id="ocpv2.service",
        ))
        self.assertEqual(svc_req.service_id, "ocpv2.service")
        with self.assertRaises(DiagnosticContractError):
            ReadOnlyDiagnosticRequestV1.from_mapping(self.request(operation="project.file_range"))

    def test_feature_flag_accepts_only_explicit_true_or_false(self):
        self.assertFalse(diagnostic_feature_enabled({}))
        self.assertFalse(diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "false"}))
        self.assertTrue(diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true"}))
        with self.assertRaises(DiagnosticContractError):
            diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "yes"})

    def _write_policy(self, base: Path, root: Path, *, mutate=None) -> Path:
        payload = {
            "schema_version": CONFIG_SCHEMA,
            "roots": {"jarvis-assistant": str(root)},
            "user_services": ["ocpv2.service"],
            "limits": {"max_bytes": 32768, "max_lines": 400, "timeout_seconds": 10},
        }
        if mutate:
            mutate(payload)
        path = base / "policy.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_policy_loads_owner_controlled_absolute_existing_roots(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "root"
            root.mkdir()
            policy = DiagnosticPolicy.load(self._write_policy(base, root))
            self.assertEqual(policy.root("jarvis-assistant"), root.resolve())
            self.assertEqual(policy.user_services, ("ocpv2.service",))
            self.assertEqual((policy.max_bytes, policy.max_lines, policy.timeout_seconds), (32768, 400, 10))

    def test_policy_rejects_unsafe_config_and_bounds(self):
        mutations = [
            lambda p: p.__setitem__("roots", {"../bad": next(iter(p["roots"].values()))}),
            lambda p: p.__setitem__("roots", {"jarvis-assistant": "relative/root"}),
            lambda p: p.__setitem__("roots", {"jarvis-assistant": "/definitely/missing/rohd-root"}),
            lambda p: p.__setitem__("user_services", ["ocpv2.service", "ocpv2.service"]),
            lambda p: p.__setitem__("user_services", ["../../evil.service"]),
            lambda p: p["limits"].__setitem__("max_bytes", 32769),
            lambda p: p["limits"].__setitem__("max_lines", 401),
            lambda p: p["limits"].__setitem__("timeout_seconds", 16),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                root = base / "root"
                root.mkdir()
                path = self._write_policy(base, root, mutate=mutate)
                with self.assertRaises(DiagnosticContractError):
                    DiagnosticPolicy.load(path)

    def test_policy_rejects_symlink_and_group_writable_config(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "root"
            root.mkdir()
            target = self._write_policy(base, root)
            link = base / "policy-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(DiagnosticContractError, "symlink"):
                DiagnosticPolicy.load(link)
            target.chmod(0o620)
            with self.assertRaisesRegex(DiagnosticContractError, "writable"):
                DiagnosticPolicy.load(target)

    def test_result_build_hashes_sanitized_payload(self):
        payload = {"branch": "main", "paths": ["README.md"]}
        result = ReadOnlyDiagnosticResultV1.build(
            request_id="REQ-1",
            correlation_id="CORR-1",
            project_id="P1",
            root_id="jarvis-assistant",
            operation_id="repo.snapshot",
            authorization_decision="ALLOW",
            captured_at="2026-09-23T00:00:00+00:00",
            freshness="FRESH",
            source_sha="a" * 40,
            runtime_sha="b" * 40,
            data_class="DIAG_SUMMARY",
            redaction_applied=False,
            truncated=False,
            status="OK",
            error_class="",
            payload=payload,
        )
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(result.payload_hash, expected)
        self.assertEqual(result.execution_owner, "NONE")
        self.assertEqual(result.to_dict()["payload"], payload)


if __name__ == "__main__":
    unittest.main()
