"""Connect to the running MCP server and call each tool once."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.mcp_client import McpClient, server_url

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MCP_SERVER_URL = server_url()

# Lab fixture: smoke checks the server advertised these. The client does not hardcode them.
LAB_TOOLS = (
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "flag_for_human_review",
)


async def main() -> None:
    async with McpClient(MCP_SERVER_URL) as client:
        names = client.tools_list
        print("tools:", names)
        missing = [name for name in LAB_TOOLS if name not in names]
        if missing:
            raise SystemExit(f"server did not advertise: {missing}")

        employee = await client.call_tool("get_employee_info", {"employee_id": "E001"})
        print("get_employee_info:", json.dumps(employee, indent=2))
        if employee.get("error") or not employee.get("found"):
            raise SystemExit("get_employee_info did not return E001")

        policy = await client.call_tool("get_policy_limits", {"role": employee["role"]})
        print("get_policy_limits:", json.dumps(policy, indent=2))
        if policy.get("error") or not policy.get("found"):
            raise SystemExit("get_policy_limits did not return standard policy")

        eligibility = await client.call_tool(
            "check_request_eligibility",
            {"employee_id": "E001", "item": "laptop"},
        )
        print("check_request_eligibility:", json.dumps(eligibility, indent=2))
        if eligibility.get("status") != "eligible":
            raise SystemExit("E001 laptop should be eligible")

        ticket = await client.call_tool(
            "flag_for_human_review",
            {
                "employee_id": "E005",
                "request": "I need a laptop for this contract",
                "reason": "contractor_role",
            },
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
