from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from runtime.orchestrator.full_mcp_backend_adapter import AdapterToolCall, FullMCPBackendAdapter
from runtime.orchestrator.production_execution_gateway import (
    GATEWAY_CONTRACT_VERSION, HOST_GATEWAY, UnixSocketGatewayTransport, UnixSocketHostRunner,
    build_gateway_request, validate_gateway_request,
)
from runtime.orchestrator.tool_authorization import TOOL_AUTH_CONTRACT_VERSION, ToolAuthorizationContract
from runtime.full_mcp.contracts import InvocationContext, scope_digest
from runtime.full_mcp.runtime import build_default_runtime, operation_definitions
from runtime.full_mcp.stdio_entrypoint import run_stdio
from runtime.full_mcp.validation_profiles import default_validation_catalog

PLAN_SHA = "a" * 64
REQ_SHA = "b" * 64
LOCK_SHA = "c" * 64


def initialize_repo(root: Path) -> None:
    subprocess.check_call(["git", "init", "-q"], cwd=root)
    subprocess.check_call(["git", "config", "user.email", "adapter@example.invalid"], cwd=root)
    subprocess.check_call(["git", "config", "user.name", "Full MCP Adapter Test"], cwd=root)
    (root / "owned").mkdir(exist_ok=True)
    (root / "read").mkdir(exist_ok=True)
    (root / "read/a.txt").write_text("adapter payload\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "read/a.txt"], cwd=root)
    subprocess.check_call(["git", "commit", "-qm", "baseline"], cwd=root)


def gateway_request(root: Path) -> dict:
    return build_gateway_request(
        project_id="GH-FULL-MCP-PH4", run_id="adapter-run", gate_id="GATE-002", lv_id="LV-ADAPTER", attempt=1,
        workspace_identity={"project_id": "GH-FULL-MCP-PH4", "workspace_root": root.as_posix()},
        package_manifest_sha256="d" * 64, preflight_evidence_sha256="e" * 64,
        runtime_prompt_artifact={"kind": "worker_runtime_prompt", "name": "adapter"},
        runtime_prompt_sha256="f" * 64, adapter_contract_version="SEM-025.v2",
        structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
        canonical_plan_sha256=PLAN_SHA,
    )


def invocation_fixture(root: Path, request_digest: str):
    catalog = default_validation_catalog()
    mutable = ("owned",)
    mutable_digest = scope_digest(mutable)
    contracts = []
    for operation in operation_definitions():
        contracts.append(ToolAuthorizationContract(
            contract_id="TAC-" + operation.operation_class_id.upper().replace("_", "-"),
            contract_version=TOOL_AUTH_CONTRACT_VERSION, contract_status="ACTIVE",
            worker_task_id="TASK-010", requirement_refs=("REQ-001",), plan_task_refs=("TASK-010",),
            operation_class_id=operation.operation_class_id, capability_class=operation.capability_class,
            operation_intent=operation.operation_intent, requirement_binding="REQUIRED", scope_binding="IN_SCOPE",
            scope_authorization_source="USER_DECISION", authorization_decision_ref="DEC-ADAPTER-TEST",
            validity_scope="TASK_ONLY", security_obligation_profile="SECRET_SCAN_REQUIRED", approval_authority="USER_DECISION",
            project_id="GH-FULL-MCP-PH4", gate_id="GATE-002", lv_id="LV-ADAPTER", run_id="adapter-run",
            canonical_plan_sha256=PLAN_SHA, requirement_digest=REQ_SHA, owned_scope_sha256=mutable_digest,
            package_binding_sha256=LOCK_SHA,
        ).sealed())
    context = InvocationContext(
        schema_version="gch.full-mcp.invocation-context.v1", project_id="GH-FULL-MCP-PH4",
        run_id="adapter-run", gate_id="GATE-002", lv_id="LV-ADAPTER", attempt=1,
        request_digest=request_digest, correlation_id="corr-adapter", workspace_root=root.resolve().as_posix(),
        canonical_plan_sha256=PLAN_SHA, dependency_lock_sha256=LOCK_SHA,
        authorization_contract_digests=tuple(c.contract_digest for c in contracts),
        read_scopes=(".",), mutable_scopes=mutable, read_scope_sha256=scope_digest((".",)),
        mutable_scope_sha256=mutable_digest, validation_profile_digests=catalog.digests(),
    ).sealed()
    return context, tuple(contracts), catalog


def build_adapter(root: Path, request: dict) -> FullMCPBackendAdapter:
    context, contracts, _ = invocation_fixture(root, request["request_digest"])
    repo = Path(__file__).resolve().parents[2]
    def params_factory(ctx, active_contracts):
        del ctx, active_contracts
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "tests.full_mcp.test_adapter_contract", "--serve", root.as_posix(), request["request_digest"]],
            cwd=repo,
            env=dict(os.environ),
        )
    return FullMCPBackendAdapter(
        context=context, contracts=contracts, server_params_factory=params_factory,
        tool_calls=(
            AdapterToolCall("filesystem_read", {"path": "read/a.txt"}, "adapter-read"),
            AdapterToolCall("execution_status", {"operation_request_id": "adapter-read"}, "adapter-status"),
            AdapterToolCall("validate", {"operation_request_id": "adapter-read", "expectations": ["RESULT_PRESENT", "AUDIT_PRESENT", "NO_SECURITY_BLOCK"]}, "adapter-validate"),
        ),
    )


class AdapterContractTests(unittest.TestCase):
    def test_gateway_wire_contract_is_unchanged_and_adapter_is_dependency_inverted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); initialize_repo(root)
            req = gateway_request(root)
            validated = validate_gateway_request(req)
            self.assertEqual(validated["gateway_contract_version"], "HOST-GATEWAY.v1")
            self.assertNotIn("full_mcp", validated)
        repo = Path(__file__).resolve().parents[2]
        gateway_source = (repo / "runtime/orchestrator/production_execution_gateway.py").read_text(encoding="utf-8")
        adapter_source = (repo / "runtime/orchestrator/full_mcp_backend_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("runtime.full_mcp", gateway_source)
        self.assertNotIn("full_mcp_backend_adapter", gateway_source)
        self.assertNotIn("provider_router", adapter_source)
        self.assertNotIn("production_execution_gateway", adapter_source)

    def test_stdio_adapter_status_validate_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); initialize_repo(root); req = gateway_request(root)
            adapter = build_adapter(root, req)
            outcome = adapter(
                req, prompt=b"approved runtime prompt", workspace_root=root,
                last_message=root / "last", timeout=30, cancel_path=root / "cancel",
            )
            self.assertEqual(outcome["execution_status"], "COMPLETED")
            self.assertEqual(outcome["exit_status_category"], "EXIT_0")
            self.assertEqual(outcome["adapter_evidence"]["transport"], "STDIO")
            self.assertEqual(outcome["structured_event_metadata"]["tool_call_count"], 3)

    def test_runtime_handler_uds_integration_preserves_gateway_result_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); initialize_repo(root); req = gateway_request(root)
            adapter = build_adapter(root, req)
            sock = root / "runtime" / "full-mcp.sock"; ledger = root / "ledger"
            runner = UnixSocketHostRunner(sock, ledger, runtime_handler=adapter)
            errors = []
            def serve():
                try: runner.serve_once(timeout=30)
                except BaseException as exc: errors.append(exc)
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            for _ in range(200):
                if sock.exists() or errors: break
                time.sleep(0.01)
            if errors: raise errors[0]
            result = UnixSocketGatewayTransport(sock, workspace_root=root)(
                req, prompt=b"approved runtime prompt", last_message=root / "last",
                timeout=30, cancel_path=root / "cancel",
            )
            thread.join(timeout=5)
            if errors: raise errors[0]
            self.assertEqual(result["process_evidence"]["exit_code"], 0)
            self.assertEqual(result["adapter_evidence"]["contract_only"], True)
            records = list(ledger.glob("*.json")); self.assertEqual(len(records), 1)
            self.assertIn('"state":"COMPLETED"', records[0].read_text(encoding="utf-8"))


async def _serve(root: Path, request_digest: str) -> None:
    context, contracts, catalog = invocation_fixture(root, request_digest)
    await run_stdio(build_default_runtime(context, contracts, catalog=catalog))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--serve":
        asyncio.run(_serve(Path(sys.argv[2]), sys.argv[3]))
    else:
        unittest.main()
