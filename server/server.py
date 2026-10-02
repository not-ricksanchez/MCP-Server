"""MCP server exposing get_employee_info over Streamable HTTP."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

_SERVER_DIR = Path(__file__).resolve().parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from logic import get_employee_info as lookup_employee_info

mcp = MCPServer("it-equipment")


@mcp.tool()
def get_employee_info(employee_id: str) -> dict[str, Any]:
    """Return role, tenure, and current equipment on file for an employee."""
    return lookup_employee_info(employee_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=3000)
