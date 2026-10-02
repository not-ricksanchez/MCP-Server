"""Connect to the running MCP server and call each tool once."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp.client import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:3000/mcp")
REQUIRED_TOOLS = (
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "flag_for_human_review",
)


def _payload(result) -> dict:
    if result.is_error:
        raise SystemExit(f"tool error: {result}")
    data = result.structured_content or {
        "content": [block.model_dump() for block in result.content]
    }
    if isinstance(data, dict) and "result" in data and len(data) == 1:
        inner = data["result"]
        if isinstance(inner, dict):
            return inner
    return data


async def main() -> None:
    async with Client(MCP_SERVER_URL) as client:
        listing = await client.list_tools()
        names = [tool.name for tool in listing.tools]
        print("tools:", names)
        missing = [name for name in REQUIRED_TOOLS if name not in names]
        if missing:
            raise SystemExit(f"missing tools: {missing}")

        employee = _payload(
            await client.call_tool("get_employee_info", {"employee_id": "E001"})
        )
        print("get_employee_info:", json.dumps(employee, indent=2))
        if not employee.get("found"):
            raise SystemExit("get_employee_info did not return E001")

        policy = _payload(
            await client.call_tool("get_policy_limits", {"role": employee["role"]})
        )
        print("get_policy_limits:", json.dumps(policy, indent=2))
        if not policy.get("found"):
            raise SystemExit("get_policy_limits did not return standard policy")

        eligibility = _payload(
            await client.call_tool(
                "check_request_eligibility",
                {"employee_id": "E001", "item": "laptop"},
            )
        )
        print("check_request_eligibility:", json.dumps(eligibility, indent=2))
        if eligibility.get("status") != "eligible":
            raise SystemExit("E001 laptop should be eligible")

        ticket = _payload(
            await client.call_tool(
                "flag_for_human_review",
                {
                    "employee_id": "E005",
                    "request": "I need a laptop for this contract",
                    "reason": "contractor_role",
                },
            )
        )
        print("flag_for_human_review:", json.dumps(ticket, indent=2))
        if not ticket.get("escalated"):
            raise SystemExit("flag_for_human_review did not escalate")

        print("ok: all four tools returned real responses")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConnectionError as exc:
        print(f"could not connect to {MCP_SERVER_URL}: {exc}", file=sys.stderr)
        print("start the server first: PYTHONPATH=. python server/server.py", file=sys.stderr)
        raise SystemExit(1) from exc
