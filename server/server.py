"""MCP server exposing IT equipment tools over Streamable HTTP."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server import logic

mcp = MCPServer("it-equipment")


@mcp.tool()
def get_employee_info(employee_id: str) -> dict[str, Any]:
    """Return role, tenure, and current equipment on file for an employee."""
    return logic.get_employee_info(employee_id)


@mcp.tool()
def get_policy_limits(role: str) -> dict[str, Any]:
    """Return what that role is eligible for and how often (laptop, monitor, peripherals)."""
    return logic.get_policy_limits(role)


@mcp.tool()
def check_request_eligibility(employee_id: str, item: str) -> dict[str, Any]:
    """Return whether the request falls within policy: eligible, ineligible, or unknown."""
    return logic.check_request_eligibility(employee_id, item)


@mcp.tool()
def flag_for_human_review(employee_id: str, request: str, reason: str) -> dict[str, Any]:
    """Escalate a request to a human reviewer. Writes a ticket; do not use for a clear policy denial."""
    return logic.flag_for_human_review(employee_id, request, reason)


if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "3000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
