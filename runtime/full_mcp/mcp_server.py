from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server import Server

from .runtime import FullMCPRuntime


def build_mcp_server(runtime: FullMCPRuntime) -> Server:
    async def on_list_tools(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        tools = [
            types.Tool(
                name=str(spec["name"]),
                description=str(spec["description"]),
                inputSchema=dict(spec["inputSchema"]),
            )
            for spec in runtime.tool_specs()
        ]
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        meta = params.meta or {}
        result = runtime.call(params.name, params.arguments or {}, meta)
        correlation_id = result.get("correlation_id")
        operation_request_id = result.get("operation_request_id")
        response_meta = {
            "gch/full-mcp/correlation_id": correlation_id,
            "gch/full-mcp/operation_request_id": operation_request_id,
        }
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))],
            structuredContent=result,
            isError=result.get("status") != "COMPLETED",
            _meta=response_meta,
        )

    return Server(
        "gch-full-mcp",
        version="PHASE-4",
        description="Closed Full MCP execution runtime over stdio only.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
