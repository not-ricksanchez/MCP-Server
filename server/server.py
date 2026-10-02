"""Trivial MCP server: one dummy tool to confirm registration and HTTP transport."""

from mcp.server import MCPServer

mcp = MCPServer("it-equipment")


@mcp.tool()
def ping() -> str:
    """Return pong. Used to confirm the server is up and tools register."""
    return "pong"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=3000)
