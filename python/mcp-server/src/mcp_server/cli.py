"""mcp-server command line.

Usage:

    mcp-server serve                 the MCP endpoint on :8000 (/mcp)
    mcp-server health                exit 0 if /healthz answers
    mcp-server tools                 list the tools (through MCP)
    mcp-server call TOOL [JSON]      call one tool, print its answer

``tools`` and ``call`` are an MCP client (the same protocol Claude
Desktop or the MCP Inspector speak), for ``make -C python mcp-call``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.request

from mcp_server import config

_URL = "http://127.0.0.1:8000"


def _health() -> int:
    try:
        with urllib.request.urlopen(f"{_URL}/healthz", timeout=2) as response:
            return 0 if response.status == 200 else 1
    except OSError as error:
        print(f"health check failed: {error}", file=sys.stderr)
        return 1


async def _client(tool: str | None, arguments: dict) -> int:
    from mcp.client import session as mcp_session  # noqa: PLC0415
    from mcp.client import streamable_http  # noqa: PLC0415

    token = os.environ.get("MCP_SERVICE_TOKEN", "")
    url = os.environ.get("MCP_URL", f"{_URL}/mcp")
    async with (
        streamable_http.streamablehttp_client(
            url, headers={"Authorization": f"Bearer {token}"}
        ) as (read, write, _),
        mcp_session.ClientSession(read, write) as session,
    ):
        await session.initialize()
        if tool is None:
            listed = await session.list_tools()
            for entry in listed.tools:
                summary = (entry.description or "").strip().split("\n")[0]
                print(f"{entry.name:<24} {summary}")
            return 0
        result = await session.call_tool(tool, arguments)
        if result.structuredContent is not None:
            print(json.dumps(result.structuredContent, indent=2))
        else:
            for content in result.content:
                print(getattr(content, "text", content))
        return 1 if result.isError else 0


def main(argv: list[str] | None = None) -> int:
    """Runs one mcp-server command.

    Args:
        argv: The arguments after the program name. None means
            ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(prog="mcp-server")
    parser.add_argument("command", choices=("serve", "health", "tools", "call"))
    parser.add_argument("tool", nargs="?")
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args(argv)
    if args.command == "health":
        return _health()
    if args.command == "tools":
        return asyncio.run(_client(None, {}))
    if args.command == "call":
        if not args.tool:
            parser.error("call needs a tool name")
        return asyncio.run(_client(args.tool, json.loads(args.arguments)))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = config.Settings.from_env(os.environ)
    except config.ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    import uvicorn  # noqa: PLC0415

    from mcp_server import server  # noqa: PLC0415

    uvicorn.run(
        server.create_app(settings),
        host="0.0.0.0",  # noqa: S104 - inside the container network.
        port=8000,
        server_header=False,
        proxy_headers=False,
        timeout_keep_alive=15,
        limit_concurrency=100,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
