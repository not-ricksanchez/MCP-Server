"""Part 6: four live agent demos — approve, deny, two different escalations.

Needs the MCP server and Ollama. Not part of CI.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.agent import (  # noqa: E402
    MCP_SERVER_URL,
    OLLAMA_HOST,
    REACT_MODEL,
    REFLECT_MODEL,
    default_react_model,
    default_reflect_model,
    run_react,
)


@dataclass(frozen=True)
class DemoCase:
    name: str
    request: str
    expected: str
    why: str


CASES = (
    DemoCase(
        name="approve",
        request="E001: my laptop is 4 years old and slow, can I get a replacement?",
        expected="APPROVE",
        why="standard employee, laptop older than 4-year refresh",
    ),
    DemoCase(
        name="deny",
        request="E002: I would like a second monitor for my desk.",
        expected="DENY",
        why="standard employee already has a recent monitor; second is over the cap",
    ),
    DemoCase(
        name="escalate-contractor",
        request="E005: I need a laptop for this contract.",
        expected="ESCALATE",
        why="contractor has no equipment policy",
    ),
    DemoCase(
        name="escalate-unknown-item",
        request="E001: my back hurts, can I get a standing desk?",
        expected="ESCALATE",
        why="standing desk is out of catalog (also medical language)",
    ),
)


async def main() -> None:
    print("OLLAMA_HOST=", OLLAMA_HOST)
    print("REACT_MODEL=", REACT_MODEL.strip(), "(think=False)")
    print("REFLECT_MODEL=", REFLECT_MODEL.strip())
    print("MCP_SERVER_URL=", MCP_SERVER_URL)
    react = default_react_model()
    critic = default_reflect_model()
    rows: list[tuple[DemoCase, str, bool]] = []

    for i, case in enumerate(CASES, start=1):
        print("\n" + "=" * 72)
        print(f"DEMO {i}/{len(CASES)}  {case.name}  expected={case.expected}")
        print(f"Why: {case.why}")
        print("Request:", case.request)
        print("=" * 72)
        run = await run_react(case.request, model=react, reflect_model=critic)
        ok = run.decision == case.expected
        rows.append((case, run.decision, ok))
        if run.ticket:
            print("Ticket:", run.ticket)
        print(f"Result: {run.decision}  flagged={run.flagged}  match={ok}")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    failed = False
    for case, got, ok in rows:
        mark = "ok" if ok else "MISMATCH"
        print(f"  {case.name:22} expected={case.expected:8} got={got:8} {mark}")
        failed = failed or not ok
    if failed:
        raise SystemExit("one or more demos did not match the expected path")
    print("ok: approve, deny, and two escalate reasons")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConnectionError as exc:
        print(f"could not connect: {exc}", file=sys.stderr)
        print("start the server first: PYTHONPATH=. python server/server.py", file=sys.stderr)
        raise SystemExit(1) from exc
