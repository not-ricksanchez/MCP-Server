"""ReAct agent: Qwen3:8b (no thinking) for the loop, Gemma3:12b for reflection.

Does not reimplement eligibility. Tools on the MCP server are the source of truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.mcp_client import McpClient, server_url
from agent.model_adapter import ModelAdapter, OllamaAdapter
from agent.reflection import apply_reflection, choose_draft, decisions_disagree, reflect
from agent.schemas import Outcome, ReactStep

load_dotenv(ROOT / ".env")

MCP_SERVER_URL = server_url()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
REACT_MODEL = os.environ.get("REACT_MODEL") or os.environ.get("OLLAMA_MODEL", "qwen3:8b")
REFLECT_MODEL = os.environ.get("REFLECT_MODEL", "gemma3:12b")
MAX_STEPS = 6

EMPLOYEE_RE = re.compile(r"\bE\d{3}\b", re.IGNORECASE)

ESCALATED_DRAFT = "Your request was sent to a human reviewer."


@dataclass
class AgentRun:
    decision: str
    draft: str
    flagged: bool
    ticket: dict[str, Any] | None = None
    react_seconds: float = 0.0
    reflect_seconds: float = 0.0
    total_seconds: float = 0.0

SYSTEM = """You handle internal IT equipment requests. You are a ReAct agent.

You MUST use MCP tools for all facts. Never invent role, tenure, equipment dates, or policy numbers.

Tools (from the MCP server):
<<TOOLS_FROM_SERVER>>

Typical order: get_employee_info, then get_policy_limits, then check_request_eligibility.
Call flag_for_human_review when the case is ambiguous or needs a human. Do NOT call it for a clear policy denial.

Rules:
- Approve only if check_request_eligibility status is eligible and the reason is ordinary.
- Deny only if status is ineligible and the reason is ordinary. Do not flag a clear deny.
- Escalate (call flag_for_human_review) if: unknown employee, item not in catalog (laptop, monitor, keyboard, mouse, headset), contractor, status unknown, medical/accessibility/legal/security/exception language, missing employee id, two different items in one request, ineligible plus special circumstances, or the employee claims a role or promotion (trust tool data, then escalate).
- When you call flag_for_human_review, finish next with decision ESCALATE.

Each turn respond with a JSON object only:
{"thought": "<one sentence>", "action": "<tool name>", "action_input": {<args>}, "decision": null, "draft": null}

When you have enough observations to decide:
{"thought": "<one sentence>", "action": null, "action_input": {}, "decision": "APPROVE|DENY|ESCALATE", "draft": "<short reply citing only Observations>"}
"""


def parse_action(text: str) -> tuple[str | None, dict[str, Any]]:
    try:
        step = ReactStep.from_output(text)
    except (TypeError, ValueError, ValidationError):
        return None, {}
    if step.action:
        return step.action, step.action_input
    if step.decision:
        return "finish", {"decision": step.decision.value, "draft": step.draft or ""}
    return None, {}


def parse_decision(text: str) -> tuple[str | None, str]:
    try:
        step = ReactStep.from_output(text)
    except (TypeError, ValueError, ValidationError):
        return None, ""
    if step.decision:
        return step.decision.value, step.draft or ""
    return None, step.draft or ""


def default_react_model() -> OllamaAdapter:
    return OllamaAdapter(host=OLLAMA_HOST, model=REACT_MODEL, think=False)


def default_reflect_model() -> OllamaAdapter:
    return OllamaAdapter(host=OLLAMA_HOST, model=REFLECT_MODEL)


def system_prompt(mcp: McpClient) -> str:
    return SYSTEM.replace("<<TOOLS_FROM_SERVER>>", mcp.format_tools())


async def run_one_shot(request: str) -> None:
    """Lab stepping-stone: one hardcoded tool call, no ReAct loop."""
    match = EMPLOYEE_RE.search(request)
    employee_id = match.group(0).upper() if match else "E001"
    print(f"Thought: Look up employee {employee_id} before judging the request.")
    print("Action: get_employee_info")
    print(f"Action Input: {json.dumps({'employee_id': employee_id})}")
    async with McpClient(MCP_SERVER_URL) as client:
        print("MCP tools:", client.tools_list)
        observation = await client.call_tool("get_employee_info", {"employee_id": employee_id})
    print("Observation:", json.dumps(observation, indent=2))


async def run_react(
    request: str,
    model: ModelAdapter | None = None,
    reflect_model: ModelAdapter | None = None,
) -> AgentRun:
    started = time.perf_counter()
    model = model or default_react_model()
    reflect_model = reflect_model or default_reflect_model()
    employee_match = EMPLOYEE_RE.search(request)
    employee_id = employee_match.group(0).upper() if employee_match else "UNKNOWN"
    decision: str | None = None
    draft = ""
    ticket: dict[str, Any] | None = None
    flagged = False
    observations: list[str] = []

    async with McpClient(MCP_SERVER_URL) as mcp:
        print("MCP tools:", mcp.tools_list)

        async def escalate(reason: str) -> None:
            nonlocal ticket, flagged
            if flagged:
                return
            args = {"employee_id": employee_id, "request": request, "reason": reason}
            print("Action: flag_for_human_review")
            print(f"Action Input: {json.dumps(args)}")
            ticket = await mcp.call_tool("flag_for_human_review", args)
            blob = json.dumps(ticket, indent=2)
            observations.append(blob)
            print("Observation:", blob)
            flagged = True

        messages = [
            {"role": "system", "content": system_prompt(mcp)},
            {"role": "user", "content": f"Request: {request}"},
        ]
        for step in range(MAX_STEPS):
            text = model.complete(messages, schema=ReactStep)
            print(f"\n--- step {step + 1} ---")
            print(text)
            name, args = parse_action(text)
            if name is None:
                messages.append({"role": "assistant", "content": text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Observation: format error. Return a JSON object with "
                            "thought plus either action/action_input or decision/draft."
                        ),
                    }
                )
                continue
            if name == "finish":
                raw_decision = args.get("decision")
                decision = raw_decision if isinstance(raw_decision, str) else None
                raw_draft = args.get("draft")
                draft = raw_draft if isinstance(raw_draft, str) else ""
                break
            if name == "flag_for_human_review":
                args = {**args, "request": request}
            observation = await mcp.call_tool(name, args)
            if name == "flag_for_human_review":
                flagged = True
                ticket = observation
            blob = json.dumps(observation, indent=2)
            observations.append(blob)
            print("Observation:", blob)
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"Observation:\n{blob}"})

        if decision is None:
            print("Thought: The ReAct loop ran out of steps without a decision.")
            decision, draft = "ESCALATE", ESCALATED_DRAFT
            await escalate("react_loop_exhausted")

        if flagged and decision != "ESCALATE":
            print(f"Thought: A review ticket was already filed, so {decision} cannot stand.")
            decision, draft = "ESCALATE", ESCALATED_DRAFT

        if decision == "ESCALATE":
            await escalate("agent_escalation")

        print("\nDecision:", decision)
        print("Draft:", draft)
        reflect_started = time.perf_counter()
        result = reflect(reflect_model, request, observations, decision, draft)
        reflect_ended = time.perf_counter()
        if decisions_disagree(decision, result.verdict, result.decision):
            print(
                "Reflection disagrees "
                f"(verdict={result.verdict.value}, reflected={result.decision.value}); escalating."
            )
            await escalate(result.reason.strip() or "reflection_disagreement")
            decision, draft = "ESCALATE", ESCALATED_DRAFT
            if result.decision == Outcome.ESCALATE:
                draft = choose_draft(ESCALATED_DRAFT, result.draft, request, observations)
        else:
            decision = apply_reflection(decision, result.verdict, result.decision)
            print("Reflection agrees; keeping Decision:", decision)
            draft = choose_draft(draft, result.draft, request, observations)
        print("Final decision:", decision)
        print("Final draft:", draft)
        return _finish_run(
            AgentRun(decision=decision, draft=draft, flagged=flagged, ticket=ticket),
            started,
            reflect_started,
            reflect_ended,
        )


def _finish_run(run: AgentRun, started: float, reflect_started: float, reflect_ended: float) -> AgentRun:
    """Fill latencies. ReAct covers everything except the reflection model call."""
    run.total_seconds = time.perf_counter() - started
    run.reflect_seconds = reflect_ended - reflect_started
    run.react_seconds = run.total_seconds - run.reflect_seconds
    print(
        f"Latency: react={run.react_seconds:.2f}s  reflection={run.reflect_seconds:.2f}s  "
        f"combined={run.total_seconds:.2f}s"
    )
    return run


async def main() -> None:
    parser = argparse.ArgumentParser(description="IT equipment ReAct agent")
    parser.add_argument("request", nargs="?", help="Natural-language equipment request")
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Only call get_employee_info once (no ReAct loop)",
    )
    args = parser.parse_args()
    request = args.request or "E001: my laptop is 4 years old and slow, can I get a replacement?"
    print("OLLAMA_HOST=", OLLAMA_HOST)
    print("REACT_MODEL=", REACT_MODEL.strip(), "(think=False)")
    print("REFLECT_MODEL=", REFLECT_MODEL.strip())
    print("MCP_SERVER_URL=", MCP_SERVER_URL)
    print("Request:", request)
    try:
        if args.one_shot:
            await run_one_shot(request)
        else:
            await run_react(request)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        print("Is the MCP server running? PYTHONPATH=. python server/server.py", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    asyncio.run(main())
