from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from runtime.orchestrator.tool_authorization import ToolAuthorizationContract
from runtime.orchestrator.public_execution_contract import PublicExecutionRequestV1, public_execution_tool_call
from runtime.full_mcp.contracts import InvocationContext, MCPMetaBinding, validate_invocation_context

PROTOCOL_VERSION = "2026-07-28"


class FullMCPBackendAdapterError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdapterToolCall:
    operation: str
    arguments: Mapping[str, Any]
    operation_request_id: str

    @classmethod
    def from_public_execution_request(cls, request: PublicExecutionRequestV1) -> "AdapterToolCall":
        projected = public_execution_tool_call(request)
        return cls(
            operation=str(projected["operation"]), arguments=dict(projected["arguments"]),
            operation_request_id=str(projected["operation_request_id"]),
        )

    def validate(self) -> None:
        if not isinstance(self.operation, str) or not self.operation:
            raise FullMCPBackendAdapterError("adapter operation is invalid")
        if not isinstance(self.arguments, Mapping):
            raise FullMCPBackendAdapterError("adapter arguments are invalid")
        MCPMetaBinding(
            invocation_context_id="ctx-" + "0" * 64,
            request_digest="0" * 64,
            correlation_id="adapter-validation",
            operation_request_id=self.operation_request_id,
        ).validate()


ServerParamsFactory = Callable[[InvocationContext, Sequence[ToolAuthorizationContract]], StdioServerParameters]


class FullMCPBackendAdapter:
    """ExecutionRuntimeHandler implementation using MCP 2026-07-28 over stdio.

    Runtime selection and tool-call planning are injected configuration.  The
    adapter never imports Provider Router or the concrete HostExecutionGateway.
    """

    def __init__(
        self,
        *,
        context: InvocationContext,
        contracts: Sequence[ToolAuthorizationContract],
        tool_calls: Sequence[AdapterToolCall],
        server_params_factory: ServerParamsFactory,
    ) -> None:
        validate_invocation_context(context)
        calls = tuple(tool_calls)
        if not calls:
            raise FullMCPBackendAdapterError("adapter tool-call sequence is empty")
        for call in calls:
            call.validate()
        if len({call.operation_request_id for call in calls}) != len(calls):
            raise FullMCPBackendAdapterError("adapter operation request ids must be unique")
        self.context = context
        self.contracts = tuple(contracts)
        self.tool_calls = calls
        self.server_params_factory = server_params_factory

    def _validate_invocation_binding(self, request: Mapping[str, Any], workspace_root: Path) -> None:
        required = ("project_id", "run_id", "gate_id", "lv_id", "attempt", "request_digest")
        if not isinstance(request, Mapping) or any(key not in request for key in required):
            raise FullMCPBackendAdapterError("gateway request binding is incomplete")
        expected = {
            "project_id": self.context.project_id,
            "run_id": self.context.run_id,
            "gate_id": self.context.gate_id,
            "lv_id": self.context.lv_id,
            "attempt": self.context.attempt,
            "request_digest": self.context.request_digest,
        }
        if any(request.get(key) != value for key, value in expected.items()):
            raise FullMCPBackendAdapterError("gateway request and InvocationContext binding mismatch")
        if workspace_root.resolve(strict=True).as_posix() != self.context.workspace_root:
            raise FullMCPBackendAdapterError("gateway workspace and InvocationContext root mismatch")

    def _meta(self, operation_request_id: str) -> dict[str, str]:
        return {
            "gch/full-mcp/invocation_context_id": self.context.invocation_context_id,
            "gch/full-mcp/request_digest": self.context.request_digest,
            "gch/full-mcp/correlation_id": self.context.correlation_id,
            "gch/full-mcp/operation_request_id": operation_request_id,
        }

    async def execute(
        self,
        request: Mapping[str, Any],
        *,
        prompt: bytes,
        workspace_root: Path,
        last_message: Path,
        timeout: int,
        cancel_path: Path,
    ) -> dict[str, Any]:
        del prompt, last_message, cancel_path
        self._validate_invocation_binding(request, workspace_root)
        if not isinstance(timeout, int) or timeout < 1:
            raise FullMCPBackendAdapterError("adapter timeout is invalid")
        params = self.server_params_factory(self.context, self.contracts)
        if not isinstance(params, StdioServerParameters):
            raise FullMCPBackendAdapterError("stdio server parameters are invalid")
        results: list[Mapping[str, Any]] = []
        terminal_status = "COMPLETED"
        last_error: Mapping[str, Any] | None = None
        async with Client(params, mode=PROTOCOL_VERSION, read_timeout_seconds=float(timeout)) as client:
            if client.protocol_version != PROTOCOL_VERSION:
                raise FullMCPBackendAdapterError("MCP protocol pin mismatch")
            catalog = await client.list_tools()
            names = {tool.name for tool in catalog.tools}
            if any(call.operation not in names for call in self.tool_calls):
                raise FullMCPBackendAdapterError("adapter requested operation outside closed catalog")
            for call in self.tool_calls:
                result = await client.call_tool(
                    call.operation,
                    dict(call.arguments),
                    meta=self._meta(call.operation_request_id),
                )
                structured = result.structured_content
                if not isinstance(structured, Mapping):
                    raise FullMCPBackendAdapterError("MCP tool result is not structured")
                results.append(structured)
                status = structured.get("status")
                if status != "COMPLETED":
                    terminal_status = "BLOCKED" if status == "BLOCKED" else "FAILED"
                    error = structured.get("error")
                    last_error = error if isinstance(error, Mapping) else None
                    break
        last = results[-1]
        last_digest = str(last.get("result_digest", ""))
        return {
            "execution_status": terminal_status,
            "process_termination_category": "EXITED",
            "exit_status_category": "EXIT_0" if terminal_status == "COMPLETED" else "NONZERO",
            "structured_event_metadata": {
                "protocol_version": PROTOCOL_VERSION,
                "tool_call_count": len(results),
                "terminal_status": terminal_status,
                "last_result_digest": last_digest,
            },
            "stderr_security_metadata": {
                "status": "PASS" if terminal_status == "COMPLETED" else "BLOCK",
                "error_code": None if last_error is None else last_error.get("code"),
            },
            "final_message_metadata": {
                "exists": True,
                "nonempty": True,
                "security": "PASS" if terminal_status == "COMPLETED" else "BLOCK",
            },
            "worker_result_identity": {
                "protocol_version": PROTOCOL_VERSION,
                "request_digest": self.context.request_digest,
                "last_result_digest": last_digest,
            },
            "stdout": b"",
            "stderr": b"",
            "final_message": (
                b"execution runtime completed" if terminal_status == "COMPLETED"
                else b"execution runtime blocked"
            ),
            "process_evidence": {
                "exit_code": 0 if terminal_status == "COMPLETED" else 1,
                "termination": "EXITED",
                "tool_call_count": len(results),
            },
            "adapter_evidence": {
                "protocol_version": PROTOCOL_VERSION,
                "transport": "STDIO",
                "contract_only": True,
            },
        }

    def __call__(self, request: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(request, **kwargs))
        raise FullMCPBackendAdapterError("synchronous runtime handler cannot run inside an active event loop")
