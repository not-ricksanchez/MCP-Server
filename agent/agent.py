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
from agent.reflection import apply_reflection, decisions_disagree, reflect
from agent.schemas import ReactStep

load_dotenv(ROOT / ".env")

MCP_SERVER_URL = server_url()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
REACT_MODEL = os.environ.get("REACT_MODEL") or os.environ.get("OLLAMA_MODEL", "qwen3:8b")
REFLECT_MODEL = os.environ.get("REFLECT_MODEL", "gemma3:12b")
MAX_STEPS = 6

CATALOG = ("laptop", "monitor", "keyboard", "mouse", "headset")
SPECIAL_RE = re.compile(
    r"\b(accessib|medical|doctor|injury|legal|security|executive|exception|ada|ergonomic)\w*\b",
    re.IGNORECASE,
)
EMPLOYEE_RE = re.compile(r"\bE\d{3}\b", re.IGNORECASE)


@dataclass
class AgentRun:
    decision: str
    draft: str
    flagged: bool
    ticket: dict[str, Any] | None = None

SYSTEM = """You handle internal IT equipment requests. You are a ReAct agent.

You MUST use MCP tools for all facts. Never invent role, tenure, equipment dates, or policy numbers.

Tools (from the MCP server):
<<TOOLS_FROM_SERVER>>

Typical order: get_employee_info, then get_policy_limits, then check_request_eligibility.
Call flag_for_human_review when the case is ambiguous or needs a human. Do NOT call it for a clear policy denial.

Rules:
- Approve only if check_request_eligibility status is eligible and the reason is ordinary.
- Deny only if status is ineligible and the reason is ordinary. Do not flag a clear deny.
- Escalate (call flag_for_human_review) if: unknown employee, item not in catalog (laptop, monitor, keyboard, mouse, headset), contractor, status unknown, medical/accessibility/legal/security/exception language, missing employee id, two different items in one request, or ineligible plus special circumstances.

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


def catalog_items_in(text: str) -> list[str]:
    found: list[str] = []
    lower = text.lower()
    for item in CATALOG:
        if re.search(rf"\b{item}\b", lower) and item not in found:
            found.append(item)
    if "desk" in lower and "standing" in lower and "monitor" not in found:
        found.append("standing desk")
    return found


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
    model = model or default_react_model()
    reflect_model = reflect_model or default_reflect_model()
    items = catalog_items_in(request)
    employee_match = EMPLOYEE_RE.search(request)
    trace: list[str] = []
    decision: str | None = None
    draft = ""
    ticket: dict[str, Any] | None = None
    flagged = False

    async with McpClient(MCP_SERVER_URL) as mcp:
        print("MCP tools:", mcp.tools_list)
        observations: list[str] = []
        messages = [
            {"role": "system", "content": system_prompt(mcp)},
            {"role": "user", "content": f"Request: {request}"},
        ]

        catalog_hits = [item for item in items if item in CATALOG]
        out_of_catalog = [item for item in items if item not in CATALOG]
        if not employee_match or len(catalog_hits) > 1 or out_of_catalog:
            if not employee_match:
                reason = "missing_employee_id"
            elif out_of_catalog:
                reason = "unknown_item"
            else:
                reason = "multiple_items"
            employee_id = employee_match.group(0).upper() if employee_match else "UNKNOWN"
            ticket = await mcp.call_tool(
                "flag_for_human_review",
                {"employee_id": employee_id, "request": request, "reason": reason},
            )
            decision = "ESCALATE"
            draft = (
                "This request was sent to a human reviewer because it cannot be decided from policy tools alone."
            )
            print("Thought: The request is missing an id, lists multiple items, or is out of catalog.")
            print("Action: flag_for_human_review")
            print("Observation:", json.dumps(ticket, indent=2))
            print("Decision: ESCALATE")
            print("Draft:", draft)
            result = reflect(reflect_model, request, [json.dumps(ticket)], decision, draft)
            print("Final draft:", result.draft)
            return AgentRun(decision=decision, draft=result.draft, flagged=True, ticket=ticket)

        for step in range(MAX_STEPS):
            text = model.complete(messages, schema=ReactStep)
            print(f"\n--- step {step + 1} ---")
            print(text)
            trace.append(text)
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
            decision, draft = "ESCALATE", "Could not finish the ReAct loop; sent to a reviewer."
            if not flagged:
                ticket = await mcp.call_tool(
                    "flag_for_human_review",
                    {
                        "employee_id": employee_match.group(0).upper(),
                        "request": request,
                        "reason": "react_loop_exhausted",
                    },
                )
                print("Action: flag_for_human_review")
                print("Observation:", json.dumps(ticket, indent=2))
                observations.append(json.dumps(ticket))
                flagged = True

        if decision == "ESCALATE" and not flagged:
            ticket = await mcp.call_tool(
                "flag_for_human_review",
                {
                    "employee_id": employee_match.group(0).upper(),
                    "request": request,
                    "reason": "agent_escalation",
                },
            )
            print("Action: flag_for_human_review")
            print("Observation:", json.dumps(ticket, indent=2))
            observations.append(json.dumps(ticket))
            flagged = True

        print("\nDecision:", decision)
        print("Draft:", draft)
        react_decision = decision or "ESCALATE"
        result = reflect(reflect_model, request, observations, react_decision, draft)
        draft = result.draft
        if decisions_disagree(react_decision, result.verdict, result.decision):
            print(
                "Reflection disagrees "
                f"(verdict={result.verdict.value}, reflected={result.decision.value}); escalating."
            )
            if not flagged:
                ticket = await mcp.call_tool(
                    "flag_for_human_review",
                    {
                        "employee_id": employee_match.group(0).upper(),
                        "request": request,
                        "reason": "reflection_disagreement",
                    },
                )
                print("Action: flag_for_human_review")
                print("Observation:", json.dumps(ticket, indent=2))
                flagged = True
            decision = "ESCALATE"
        else:
            decision = apply_reflection(react_decision, result.verdict, result.decision)
            print("Reflection agrees; keeping Decision:", decision)
        print("Final decision:", decision)
        print("Final draft:", draft)
        return AgentRun(decision=decision or "ESCALATE", draft=draft, flagged=flagged, ticket=ticket)


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
