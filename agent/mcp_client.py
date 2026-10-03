"""MCP client wrapper. Tools come from the server via list_tools, not a client-side catalog."""

from __future__ import annotations

import os
from typing import Any

from mcp.client import Client

DEFAULT_URL = "http://127.0.0.1:3000/mcp"


def server_url() -> str:
    return os.environ.get("MCP_SERVER_URL", DEFAULT_URL)


def payload(result: Any) -> dict[str, Any]:
    if getattr(result, "is_error", False):
        return {"error": True, "raw": str(result)}
    data = result.structured_content or {}
    if isinstance(data, dict) and "result" in data and len(data) == 1 and isinstance(data["result"], dict):
        return data["result"]
    if isinstance(data, dict):
        return data
    return {"raw": str(result)}


def _tool_args(tool: Any) -> str:
    schema = getattr(tool, "input_schema", None) or {}
    if not isinstance(schema, dict):
        return ""
    props = schema.get("properties") or {}
    required = schema.get("required") or list(props)
    return ", ".join(str(name) for name in required)


class McpClient:
    """Async context manager. On connect, caches the server's advertised tools."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or server_url()
        self._inner = Client(self.url)
        self._tools: list[Any] = []

    async def __aenter__(self) -> McpClient:
        await self._inner.__aenter__()
        await self.fetch_tools()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._inner.__aexit__(*exc)

    async def fetch_tools(self) -> list[str]:
        listing = await self._inner.list_tools()
        self._tools = list(listing.tools)
        return self.tools_list

    @property
    def tools_list(self) -> list[str]:
        return [tool.name for tool in self._tools]

    def format_tools(self) -> str:
        if not self._tools:
            return "(none)"
        lines: list[str] = []
        for tool in self._tools:
            line = f"- {tool.name}({_tool_args(tool)})"
            desc = (getattr(tool, "description", None) or "").strip()
            if desc:
                line += f" — {desc}"
            lines.append(line)
        return "\n".join(lines)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.tools_list:
            return {"error": f"unknown_tool:{name}"}
        return payload(await self._inner.call_tool(name, arguments or {}))
