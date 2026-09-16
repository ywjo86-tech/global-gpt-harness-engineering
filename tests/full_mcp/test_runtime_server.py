from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from runtime.orchestrator.tool_authorization import TOOL_AUTH_CONTRACT_VERSION, ToolAuthorizationContract
from runtime.full_mcp.contracts import InvocationContext, MCPMetaBinding, scope_digest
from runtime.full_mcp.runtime import build_default_runtime, operation_definitions
from runtime.full_mcp.validation_profiles import default_validation_catalog
from runtime.full_mcp.stdio_entrypoint import run_stdio

SHA_A="a"*64
SHA_B="b"*64
SHA_C="c"*64


def initialize_repo(root: Path) -> None:
    subprocess.check_call(["git","init","-q"],cwd=root)
    subprocess.check_call(["git","config","user.email","full-mcp@example.invalid"],cwd=root)
    subprocess.check_call(["git","config","user.name","Full MCP Runtime Test"],cwd=root)
    (root/"owned").mkdir(exist_ok=True); (root/"read").mkdir(exist_ok=True)
    (root/"read/a.txt").write_text("hello runtime\n",encoding="utf-8")
    (root/"owned/base.txt").write_text("base\n",encoding="utf-8")
    subprocess.check_call(["git","add","read/a.txt","owned/base.txt"],cwd=root)
    subprocess.check_call(["git","commit","-qm","baseline"],cwd=root)


def fixture(root: Path):
    catalog=default_validation_catalog()
    mutable=("owned",); mutable_digest=scope_digest(mutable)
    contracts=[]
    for operation in operation_definitions():
        contracts.append(ToolAuthorizationContract(
            contract_id="TAC-"+operation.operation_class_id.upper().replace("_","-"),
            contract_version=TOOL_AUTH_CONTRACT_VERSION,contract_status="ACTIVE",
            worker_task_id="TASK-009",requirement_refs=("REQ-001",),plan_task_refs=("TASK-009",),
            operation_class_id=operation.operation_class_id,capability_class=operation.capability_class,
            operation_intent=operation.operation_intent,requirement_binding="REQUIRED",scope_binding="IN_SCOPE",
            scope_authorization_source="USER_DECISION",authorization_decision_ref="DEC-RUNTIME-TEST",
            validity_scope="TASK_ONLY",security_obligation_profile="SECRET_SCAN_REQUIRED",approval_authority="USER_DECISION",
            project_id="GH-FULL-MCP-PH4",gate_id="GATE-002",lv_id="LV-RUNTIME",run_id="runtime-test",
            canonical_plan_sha256=SHA_A,requirement_digest=SHA_B,owned_scope_sha256=mutable_digest,
            package_binding_sha256=SHA_C,
        ).sealed())
    context=InvocationContext(
        schema_version="gch.full-mcp.invocation-context.v1",project_id="GH-FULL-MCP-PH4",run_id="runtime-test",
        gate_id="GATE-002",lv_id="LV-RUNTIME",attempt=1,request_digest=SHA_C,correlation_id="corr-runtime",
        workspace_root=root.resolve().as_posix(),canonical_plan_sha256=SHA_A,dependency_lock_sha256=SHA_C,
        authorization_contract_digests=tuple(c.contract_digest for c in contracts),read_scopes=(".",),mutable_scopes=mutable,
        read_scope_sha256=scope_digest((".",)),mutable_scope_sha256=mutable_digest,
        validation_profile_digests=catalog.digests(),
    ).sealed()
    return context,tuple(contracts),catalog


def meta(context: InvocationContext, request_id: str) -> dict[str,str]:
    return {
        "gch/full-mcp/invocation_context_id":context.invocation_context_id,
        "gch/full-mcp/request_digest":context.request_digest,
        "gch/full-mcp/correlation_id":context.correlation_id,
        "gch/full-mcp/operation_request_id":request_id,
    }


class RuntimeCompositionTests(unittest.TestCase):
    def setUp(self)->None:
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); initialize_repo(self.root)
        self.context,self.contracts,self.catalog=fixture(self.root)
        self.runtime=build_default_runtime(self.context,self.contracts,catalog=self.catalog)
    def tearDown(self)->None:self.temp.cleanup()

    def test_closed_catalog_exact_and_unknown_blocked(self)->None:
        expected={op.operation_class_id for op in operation_definitions()}
        specs=self.runtime.tool_specs(); self.assertEqual({s["name"] for s in specs},expected); self.assertEqual(len(specs),14)
        self.assertTrue(all(s["inputSchema"]["additionalProperties"] is False for s in specs))
        result=self.runtime.call("unknown_operation",{},meta(self.context,"op-unknown"))
        self.assertEqual(result["status"],"BLOCKED"); self.assertEqual(result["error"]["code"],"INPUT_SCHEMA_INVALID")

    def test_authorized_read_roundtrip_and_replay_guard(self)->None:
        binding=meta(self.context,"op-read-1")
        result=self.runtime.call("filesystem_read",{"path":"read/a.txt"},binding)
        self.assertEqual(result["status"],"COMPLETED"); self.assertEqual(result["data"]["text"],"hello runtime\n")
        self.assertEqual(result["correlation_id"],self.context.correlation_id); self.assertEqual(len(result["result_digest"]),64)
        replay=self.runtime.call("filesystem_read",{"path":"read/a.txt"},binding)
        self.assertEqual(replay["status"],"BLOCKED"); self.assertEqual(replay["error"]["code"],"EFFECT_REPLAY_BLOCKED")

    def test_unauthorized_metadata_binding_fails_before_dispatch(self)->None:
        bad=meta(self.context,"op-bad-meta"); bad["gch/full-mcp/request_digest"]="0"*64
        result=self.runtime.call("filesystem_read",{"path":"read/a.txt"},bad)
        self.assertEqual(result["status"],"BLOCKED"); self.assertEqual(result["error"]["code"],"AUTHORIZATION_DENIED")


class MCPStdioSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_2026_07_28_closed_catalog_and_authorized_call(self)->None:
        with tempfile.TemporaryDirectory() as td:
            fixture_root=Path(td); initialize_repo(fixture_root); context,_,_=fixture(fixture_root)
            repo=Path(__file__).resolve().parents[2]
            env=dict(os.environ)
            params=StdioServerParameters(
                command=sys.executable,
                args=["-m","tests.full_mcp.test_runtime_server","--serve",str(fixture_root)],
                cwd=repo,
                env=env,
            )
            async with Client(params, mode="2026-07-28") as client:
                self.assertEqual(client.protocol_version,"2026-07-28")
                listed=await client.list_tools(); names={tool.name for tool in listed.tools}
                self.assertEqual(names,{op.operation_class_id for op in operation_definitions()})
                result=await client.call_tool("filesystem_read",{"path":"read/a.txt"},meta=meta(context,"op-stdio-read"))
                self.assertFalse(result.is_error); self.assertEqual(result.structured_content["status"],"COMPLETED")
                self.assertEqual(result.structured_content["data"]["text"],"hello runtime\n")
                self.assertEqual(result.meta["gch/full-mcp/correlation_id"],context.correlation_id)

    def test_product_runtime_has_no_http_sse_listener_surface(self)->None:
        repo=Path(__file__).resolve().parents[2]
        text="\n".join((repo/rel).read_text(encoding="utf-8") for rel in (
            "runtime/full_mcp/runtime.py","runtime/full_mcp/mcp_server.py","runtime/full_mcp/stdio_entrypoint.py"))
        for forbidden in ("streamable_http","sse_server","FastMCP","uvicorn","Starlette","listen(","socket.socket"):
            with self.subTest(forbidden=forbidden): self.assertNotIn(forbidden,text)
        self.assertIn("stdio_server",text)


async def _serve(root: Path) -> None:
    context,contracts,catalog=fixture(root)
    runtime=build_default_runtime(context,contracts,catalog=catalog)
    await run_stdio(runtime)


if __name__ == "__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--serve":
        asyncio.run(_serve(Path(sys.argv[2])))
    else:
        unittest.main()
