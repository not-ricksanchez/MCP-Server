"""Interactive IT equipment request loop.

Needs the MCP server and Ollama. Type quit to stop.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.agent import (
    MCP_SERVER_URL,
    OLLAMA_HOST,
    REACT_MODEL,
    REFLECT_MODEL,
    default_react_model,
    default_reflect_model,
    run_react,
)


def read_request() -> str | None:
    """Return the next request, or None when the user wants to stop."""
    try:
        line = input("\nRequest (quit to stop): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if line.lower() == "quit":
        return None
    return line


async def main() -> None:
    print("OLLAMA_HOST=", OLLAMA_HOST)
    print("REACT_MODEL=", REACT_MODEL.strip(), "(think=False)")
    print("REFLECT_MODEL=", REFLECT_MODEL.strip())
    print("MCP_SERVER_URL=", MCP_SERVER_URL)
    print("Type an equipment request. Type quit to stop.")
    react = default_react_model()
    critic = default_reflect_model()

    while True:
        request = read_request()
        if request is None:
            break
        if not request:
            continue
        try:
            run = await run_react(request, model=react, reflect_model=critic)
        except ConnectionError as exc:
            print(f"could not connect: {exc}", file=sys.stderr)
            print("start the server first: PYTHONPATH=. python server/server.py", file=sys.stderr)
            raise SystemExit(1) from exc
        print("\n--- response ---")
        print("Decision:", run.decision)
        print("Reply:", run.draft)
        if run.ticket:
            print("Ticket:", run.ticket)


if __name__ == "__main__":
    asyncio.run(main())
