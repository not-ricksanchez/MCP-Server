"""Part 6: live agent demos — approve, deny, and escalations for different reasons.

Needs the MCP server and Ollama. Not part of CI. Writes the full trace and latencies to demo_output.md.
"""

from __future__ import annotations

import asyncio
import io
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.agent import (
    MCP_SERVER_URL,
    OLLAMA_HOST,
    REACT_MODEL,
    REFLECT_MODEL,
    AgentRun,
    default_react_model,
    default_reflect_model,
    run_react,
)

OUTPUT_PATH = ROOT / "demo_output.md"


class Tee(io.StringIO):
    """Keeps everything written while still echoing it to the terminal."""

    def __init__(self, terminal: TextIO) -> None:
        super().__init__()
        self._terminal = terminal

    def write(self, text: str) -> int:
        self._terminal.write(text)
        return super().write(text)

    def flush(self) -> None:
        self._terminal.flush()


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
        why="standard employee's only monitor was issued under 3 years ago (refresh interval not met)",
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
    DemoCase(
        name="escalate-missing-date",
        request="E006: my monitor flickers constantly, can I get a replacement?",
        expected="ESCALATE",
        why="monitor on file has no issue date, so eligibility is unknown",
    ),
    DemoCase(
        name="escalate-special",
        request="E011: my doctor says I need a lighter laptop because of a wrist injury.",
        expected="ESCALATE",
        why="laptop is ineligible (recent issue) but the reason is medical",
    ),
)


async def run_cases(rows: list[tuple[DemoCase, AgentRun]]) -> None:
    print("OLLAMA_HOST=", OLLAMA_HOST)
    print("REACT_MODEL=", REACT_MODEL.strip(), "(think=False)")
    print("REFLECT_MODEL=", REFLECT_MODEL.strip())
    print("MCP_SERVER_URL=", MCP_SERVER_URL)
    react = default_react_model()
    critic = default_reflect_model()

    for i, case in enumerate(CASES, start=1):
        print("\n" + "=" * 72)
        print(f"DEMO {i}/{len(CASES)}  {case.name}  expected={case.expected}")
        print(f"Why: {case.why}")
        print("Request:", case.request)
        print("=" * 72)
        run = await run_react(case.request, model=react, reflect_model=critic)
        rows.append((case, run))
        if run.ticket:
            print("Ticket:", run.ticket)
        print(f"Result: {run.decision}  flagged={run.flagged}  match={run.decision == case.expected}")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for case, run in rows:
        mark = "ok" if run.decision == case.expected else "MISMATCH"
        print(
            f"  {case.name:22} expected={case.expected:8} got={run.decision:8} {mark}  "
            f"react={run.react_seconds:6.2f}s reflection={run.reflect_seconds:6.2f}s "
            f"combined={run.total_seconds:6.2f}s"
        )


def render_markdown(rows: list[tuple[DemoCase, AgentRun]], log: str) -> str:
    lines = [
        "# Demo output",
        "",
        f"Run at {datetime.now().astimezone().isoformat(timespec='seconds')}  ",
        f"ReAct model: `{REACT_MODEL.strip()}` · Reflection model: `{REFLECT_MODEL.strip()}`",
        "",
        "## Summary",
        "",
        "| # | Case | Expected | Got | Match | Flagged | ReAct (s) | Reflection (s) | Combined (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, (case, run) in enumerate(rows, start=1):
        match = "yes" if run.decision == case.expected else "**no**"
        lines.append(
            f"| {i} | {case.name} | {case.expected} | {run.decision} | {match} | {run.flagged} | "
            f"{run.react_seconds:.2f} | {run.reflect_seconds:.2f} | {run.total_seconds:.2f} |"
        )
    if rows:
        react = sum(run.react_seconds for _, run in rows)
        reflection = sum(run.reflect_seconds for _, run in rows)
        combined = sum(run.total_seconds for _, run in rows)
        n = len(rows)
        lines += [
            f"| | **total** | | | | | {react:.2f} | {reflection:.2f} | {combined:.2f} |",
            f"| | **mean** | | | | | {react / n:.2f} | {reflection / n:.2f} | {combined / n:.2f} |",
        ]
    lines += [
        "",
        (
            "ReAct latency covers the MCP connection, every model step, and every tool call. "
            "Reflection latency is the reflection model call only. Combined is the whole request end to end."
        ),
        "",
        "## Cases",
        "",
    ]
    for i, (case, run) in enumerate(rows, start=1):
        lines += [
            f"### {i}. {case.name}",
            "",
            f"- Request: {case.request}",
            f"- Why: {case.why}",
            f"- Decision: {run.decision} (expected {case.expected})",
            f"- Final draft: {run.draft}",
        ]
        if run.ticket:
            lines.append(f"- Ticket: `{run.ticket.get('ticket_id')}` reason `{run.ticket.get('reason')}`")
        lines.append("")
    lines += ["## Full trace", "", "```text", log.rstrip(), "```", ""]
    return "\n".join(lines)


def main() -> None:
    tee = Tee(sys.stdout)
    rows: list[tuple[DemoCase, AgentRun]] = []
    try:
        with redirect_stdout(tee):
            asyncio.run(run_cases(rows))
    finally:
        OUTPUT_PATH.write_text(render_markdown(rows, tee.getvalue()), encoding="utf-8")
        print(f"\nwrote {OUTPUT_PATH}")
    if any(run.decision != case.expected for case, run in rows):
        raise SystemExit("one or more demos did not match the expected path")
    print("ok: approve, deny, and four escalate reasons")


if __name__ == "__main__":
    try:
        main()
    except ConnectionError as exc:
        print(f"could not connect: {exc}", file=sys.stderr)
        print("start the server first: PYTHONPATH=. python server/server.py", file=sys.stderr)
        raise SystemExit(1) from exc
