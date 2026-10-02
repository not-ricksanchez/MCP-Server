"""Connect to the running MCP server and call get_employee_info once."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp.client import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:3000/mcp")
EMPLOYEE_ID = os.environ.get("EMPLOYEE_ID", "E001")


async def main() -> None:
    async with Client(MCP_SERVER_URL) as client:
        listing = await client.list_tools()
        names = [tool.name for tool in listing.tools]
        print("tools:", names)
        if "get_employee_info" not in names:
            raise SystemExit("get_employee_info is not registered on the server")

        result = await client.call_tool(
            "get_employee_info", {"employee_id": EMPLOYEE_ID}
        )
        if result.is_error:
            raise SystemExit(f"tool error: {result}")

        payload = result.structured_content or {
            "content": [block.model_dump() for block in result.content]
        }
        print(json.dumps(payload, indent=2))

        record = payload.get("result", payload)
        if not record.get("found"):
            raise SystemExit(f"no employee record returned for {EMPLOYEE_ID}")
        print(f"ok: {record['employee_id']} role={record['role']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConnectionError as exc:
        print(f"could not connect to {MCP_SERVER_URL}: {exc}", file=sys.stderr)
        print("start the server first: PYTHONPATH=. python server/server.py", file=sys.stderr)
        raise SystemExit(1) from exc
