from __future__ import annotations

from mcp.server.stdio import stdio_server

from .mcp_server import build_mcp_server
from .runtime import FullMCPRuntime


async def run_stdio(runtime: FullMCPRuntime) -> None:
    server = build_mcp_server(runtime)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
