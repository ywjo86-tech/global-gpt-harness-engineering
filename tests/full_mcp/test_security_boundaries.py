from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.tool_authorization import (
    TOOL_AUTH_CONTRACT_VERSION,
    ToolAuthorizationContract,
)
from runtime.full_mcp.authorization import FullMCPAuthorizationError
from runtime.full_mcp.contracts import InvocationContext, scope_digest
from runtime.full_mcp.path_policy import PathPolicyError, WorkspacePathPolicy
from runtime.full_mcp.process_service import ProcessService, ProcessServiceError, ShellPolicy
from runtime.full_mcp.runtime import build_default_runtime, operation_definitions
from runtime.full_mcp.validation_profiles import default_validation_catalog

PLAN_SHA = "a" * 64
REQ_SHA = "b" * 64
LOCK_SHA = "c" * 64

def initialize_repo(root: Path) -> None:
    subprocess.check_call(["git", "init", "-q"], cwd=root)
    subprocess.check_call(["git", "config", "user.email", "security@example.invalid"], cwd=root)
    subprocess.check_call(["git", "config", "user.name", "Full MCP Security Test"], cwd=root)
    (root / "owned").mkdir()
    (root / "read").mkdir()
    (root / "read/public.txt").write_text("NVIDIA_API_KEY=TOPSECRET\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "read/public.txt"], cwd=root)
    subprocess.check_call(["git", "commit", "-qm", "baseline"], cwd=root)


def fixture(root: Path):
    catalog = default_validation_catalog()
    mutable = ("owned",)
    mutable_digest = scope_digest(mutable)
    contracts = []
    for operation in operation_definitions():
        contracts.append(ToolAuthorizationContract(
            contract_id="TAC-" + operation.operation_class_id.upper().replace("_", "-"),
            contract_version=TOOL_AUTH_CONTRACT_VERSION,
            contract_status="ACTIVE",
            worker_task_id="TASK-012",
            requirement_refs=("SEC-001",),
            plan_task_refs=("TASK-012",),
            operation_class_id=operation.operation_class_id,
            capability_class=operation.capability_class,
            operation_intent=operation.operation_intent,
            requirement_binding="REQUIRED",
            scope_binding="IN_SCOPE",
            scope_authorization_source="USER_DECISION",
            authorization_decision_ref="DEC-SECURITY-TEST",
            validity_scope="TASK_ONLY",
            security_obligation_profile="SECRET_SCAN_REQUIRED",
            approval_authority="USER_DECISION",
            project_id="GH-FULL-MCP-PH4",
            gate_id="GATE-003",
            lv_id="LV-SECURITY",
            run_id="security-run",
            canonical_plan_sha256=PLAN_SHA,
            requirement_digest=REQ_SHA,
            owned_scope_sha256=mutable_digest,
            package_binding_sha256=LOCK_SHA,
        ).sealed())
    context = InvocationContext(
        schema_version="gch.full-mcp.invocation-context.v1",
        project_id="GH-FULL-MCP-PH4", run_id="security-run", gate_id="GATE-003",
        lv_id="LV-SECURITY", attempt=1, request_digest=LOCK_SHA,
        correlation_id="corr-security", workspace_root=root.resolve().as_posix(),
        canonical_plan_sha256=PLAN_SHA,
        dependency_lock_sha256=LOCK_SHA,
        authorization_contract_digests=tuple(c.contract_digest for c in contracts),
        read_scopes=(".",), mutable_scopes=mutable,
        read_scope_sha256=scope_digest((".",)),
        mutable_scope_sha256=mutable_digest,
        validation_profile_digests=catalog.digests(),
    ).sealed()
    return context, tuple(contracts), catalog


def meta(context: InvocationContext, request_id: str) -> dict[str, str]:
    return {
        "gch/full-mcp/invocation_context_id": context.invocation_context_id,
        "gch/full-mcp/request_digest": context.request_digest,
        "gch/full-mcp/correlation_id": context.correlation_id,
        "gch/full-mcp/operation_request_id": request_id,
    }


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize_repo(self.root)
        self.context, self.contracts, self.catalog = fixture(self.root)
        self.runtime = build_default_runtime(self.context, self.contracts, catalog=self.catalog)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_workspace_path_sensitive_and_symlink_escape_fail_closed(self) -> None:
        (self.root / "read/.env").write_text("SECRET=x", encoding="utf-8")
        (self.root / "read/link").symlink_to("/etc/passwd")
        policy = WorkspacePathPolicy(self.root, read_scopes=(".",), mutable_scopes=("owned",))
        for target in ("../outside", "/etc/passwd", "read/link", "read/.env"):
            with self.subTest(target=target), self.assertRaises(PathPolicyError):
                policy.resolve_read(target)
        with self.assertRaises(PathPolicyError):
            policy.resolve_mutable("read/public.txt")
        with self.assertRaises(PathPolicyError):
            policy.resolve_mutable("owned/.env")

    def test_shell_isolation_blocks_wrappers_env_and_inheritance(self) -> None:
        policy = WorkspacePathPolicy(self.root, read_scopes=(".",), mutable_scopes=("owned",))
        service = ProcessService(policy, shell_policy=ShellPolicy(
            env_allowlist=("SAFE",), allowed_executables=(sys.executable, Path(sys.executable).name)))
        with self.assertRaises(ProcessServiceError):
            service.execute(argv=["bash", "-c", "echo x"], cwd="owned", timeout_seconds=2)
        result = service.execute(
            argv=[sys.executable, "-c", "import os; print(os.getenv('SAFE')); print(os.getenv('HOME'))"],
            cwd="owned", timeout_seconds=2, env={"SAFE": "yes"},
        )
        self.assertEqual(result["stdout"].splitlines(), ["yes", "None"])
        with self.assertRaises(ProcessServiceError):
            service.execute(
                argv=[sys.executable, "-c", "print(1)"], cwd="owned", timeout_seconds=2,
                env={"PATH": "/tmp"},
            )

    def test_integrated_auth_metadata_and_permission_fail_closed(self) -> None:
        bad = meta(self.context, "security-bad-meta")
        bad["gch/full-mcp/request_digest"] = "0" * 64
        blocked = self.runtime.call("filesystem_read", {"path": "read/public.txt"}, bad)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["error"]["code"], "AUTHORIZATION_DENIED")
        unknown = self.runtime.call("jarvis_execute", {}, meta(self.context, "security-unknown"))
        self.assertEqual(unknown["status"], "BLOCKED")
        self.assertEqual(unknown["error"]["code"], "INPUT_SCHEMA_INVALID")
        with self.assertRaises(FullMCPAuthorizationError):
            build_default_runtime(self.context, self.contracts[:-1], catalog=self.catalog)

    def test_sensitive_payload_is_not_written_to_durable_observability(self) -> None:
        result = self.runtime.call(
            "filesystem_read", {"path": "read/public.txt"}, meta(self.context, "security-secret-read"))
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("TOPSECRET", result["data"]["text"])
        durable_root = self.root / "_workspace" / "full-mcp" / "security-run"
        durable_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in durable_root.rglob("*") if path.is_file()
        )
        self.assertNotIn("TOPSECRET", durable_text)
        self.assertNotIn("NVIDIA_API_KEY", durable_text)
        self.assertNotIn("stdout", durable_text)
        self.assertNotIn("stderr", durable_text)

    def test_no_memory_jarvis_provider_or_network_bypass_surface(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        targets = list((repo / "runtime/full_mcp").glob("*.py"))
        targets.append(repo / "runtime/orchestrator/full_mcp_backend_adapter.py")
        forbidden_import_fragments = ("project_memory", "jarvis", "provider_router")
        forbidden_transport_fragments = ("streamable_http", "sse_server", "fastmcp", "uvicorn", "starlette")
        for path in targets:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            modules = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom): modules.append(node.module or "")
            lowered = "\n".join(modules).lower()
            with self.subTest(path=path.name):
                self.assertFalse(any(fragment in lowered for fragment in forbidden_import_fragments))
                self.assertFalse(any(fragment in text.lower() for fragment in forbidden_transport_fragments))
        names = {spec["name"] for spec in self.runtime.tool_specs()}
        self.assertTrue(all("jarvis" not in name.lower() and "memory" not in name.lower() for name in names))


if __name__ == "__main__":
    unittest.main()
