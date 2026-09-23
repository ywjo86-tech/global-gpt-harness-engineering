from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1
from runtime.orchestrator.host_inspection_port import HostInspectionError, HostInspectionPort
from runtime.orchestrator.project_onboarding import OnboardingRegistry


class HostInspectionPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "demo-project"
        self.project.mkdir()
        (self.project / "IMPLEMENTATION_PLAN.md").write_text("# plan\n", encoding="utf-8")
        (self.project / "safe.txt").write_text("alpha beta gamma\nsecond alpha\n", encoding="utf-8")
        (self.project / ".env").write_text("SECRET=value\n", encoding="utf-8")
        (self.project / ".gitignore").write_text(".env\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.project), "add", "IMPLEMENTATION_PLAN.md", "safe.txt", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "baseline"], check=True)
        self.registry_root = self.base / "registry"
        OnboardingRegistry(self.registry_root / "aliases").register(self.project, "demo")
        self.port = HostInspectionPort(registry_root=self.registry_root, read_scopes=(".",))

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def request(operation: str, arguments=None) -> HostInspectionRequestV1:
        return HostInspectionRequestV1.from_mapping({
            "schema_version": "orchestration.host-inspection-request.v1",
            "request_id": "INSP-1", "correlation_id": "CORR-1",
            "project_alias": "demo", "operation": operation,
            "arguments": {} if arguments is None else arguments,
            "state_change_required": False,
        })

    def test_git_branch_status_and_diff_use_safe_git_service(self) -> None:
        branch = self.port.inspect(self.request("git.branch"))
        self.assertEqual(branch.status, "OK")
        self.assertEqual(branch.data["branch"], "main")
        status = self.port.inspect(self.request("git.status"))
        self.assertTrue(status.data["clean"])
        (self.project / "safe.txt").write_text("changed\n", encoding="utf-8")
        diff = self.port.inspect(self.request("git.diff", {"paths": ["safe.txt"], "max_bytes": 4096}))
        self.assertEqual(diff.status, "OK")
        self.assertIn("changed", diff.data["diff"])

    def test_filesystem_read_search_and_metadata(self) -> None:
        read = self.port.inspect(self.request("filesystem.read", {"path": "safe.txt", "max_bytes": 4096}))
        self.assertEqual(read.status, "OK")
        self.assertIn("alpha beta", read.data["text"])
        search = self.port.inspect(self.request("filesystem.search", {
            "root": ".", "query": "alpha", "mode": "LITERAL", "glob": "*.txt",
            "max_matches": 10, "max_file_bytes": 4096,
        }))
        self.assertEqual(search.status, "OK")
        self.assertEqual(search.data["match_count"], 2)
        metadata = self.port.inspect(self.request("filesystem.metadata", {"path": "safe.txt"}))
        self.assertEqual(metadata.data["kind"], "REGULAR_FILE")
        self.assertEqual(len(metadata.data["sha256"]), 64)

    def test_sensitive_symlink_and_output_bounds_are_blocked(self) -> None:
        outside = self.base / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (self.project / "link.txt").symlink_to(outside)
        cases = (
            self.request("filesystem.read", {"path": ".env"}),
            self.request("filesystem.read", {"path": "link.txt"}),
            self.request("filesystem.read", {"path": "safe.txt", "max_bytes": 4}),
        )
        for req in cases:
            with self.subTest(arguments=dict(req.arguments)):
                result = self.port.inspect(req)
                self.assertEqual(result.status, "BLOCKED")
                self.assertTrue(result.error_code)

    def test_tampered_or_missing_project_binding_fails_closed(self) -> None:
        entry = self.registry_root / "aliases" / "demo.json"
        original = entry.read_text(encoding="utf-8")
        payload = json.loads(original)
        payload["project_root"] = str(self.base / "moved")
        entry.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(HostInspectionError, "PROJECT_BINDING_INVALID"):
            self.port.inspect(self.request("git.status"))
        entry.write_text(original, encoding="utf-8")

        missing = HostInspectionRequestV1.from_mapping({
            **self.request("git.status").to_dict(),
            "request_id": "INSP-2", "project_alias": "unknown",
        })
        with self.assertRaisesRegex(HostInspectionError, "PROJECT_NOT_REGISTERED"):
            self.port.inspect(missing)

    def test_user_service_properties_uses_only_configured_unit_and_fixed_runner(self) -> None:
        calls = []
        def runner(argv):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="ActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\n", stderr="")
        port = HostInspectionPort(
            registry_root=self.registry_root, read_scopes=(".",),
            allowed_service_units=frozenset({"ocpv2.service"}), service_runner=runner,
        )
        result = port.inspect(self.request("user_service.properties", {"unit_id": "ocpv2.service"}))
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data["ActiveState"], "active")
        blocked = port.inspect(self.request("user_service.properties", {"unit_id": "ssh.service"}))
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertEqual(len(calls), 1)

    def test_harness_attention_uses_server_configured_search_root(self) -> None:
        port = HostInspectionPort(
            registry_root=self.registry_root, read_scopes=("."), attention_search_root=self.base,
        )
        result = port.inspect(self.request("harness.attention"))
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data, {"pending": []})

    def test_port_source_has_no_execution_or_mutation_imports(self) -> None:
        import inspect
        import runtime.orchestrator.host_inspection_port as module
        source = inspect.getsource(module)
        for forbidden in (
            "ProcessService", "FullMCPRuntime", "subprocess", "filesystem.write",
            "git.restore", "git.commit", "git.push", "provider_router",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
