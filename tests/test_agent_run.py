"""run_react with fake models and a fake MCP client — no Ollama, no server."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Self

import pytest

from agent import agent
from agent.agent import ESCALATED_DRAFT, run_react

REQUEST = "E011: my doctor says I need a lighter laptop because of a wrist injury."
ELIGIBILITY = {"status": "ineligible", "reason": "refresh_interval_not_met", "item": "laptop"}


class FakeMcp:
    def __init__(self, url: str | None = None) -> None:
        self.tools_list = ["check_request_eligibility", "flag_for_human_review"]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def format_tools(self) -> str:
        return "\n".join(f"- {name}" for name in self.tools_list)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        self.calls.append((name, args))
        if name == "flag_for_human_review":
            return {"ticket_id": "ESC-test", "escalated": True, **args}
        return ELIGIBILITY


class ScriptedModel:
    def __init__(self, *outputs: dict[str, Any]) -> None:
        self._outputs = [json.dumps(output) for output in outputs]

    def complete(self, messages: list[dict[str, str]], schema: Any = None) -> str:
        return self._outputs.pop(0)


def react_model(decision: str, draft: str) -> ScriptedModel:
    return ScriptedModel(
        {
            "thought": "Check eligibility.",
            "action": "check_request_eligibility",
            "action_input": {"employee_id": "E011", "item": "laptop"},
            "decision": None,
            "draft": None,
        },
        {"thought": "Decide.", "action": None, "action_input": {}, "decision": decision, "draft": draft},
    )


def reflection(verdict: str, decision: str, draft: str, reason: str) -> ScriptedModel:
    return ScriptedModel({"verdict": verdict, "decision": decision, "draft": draft, "reason": reason})


@pytest.fixture
def fake_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "McpClient", FakeMcp)


def test_reflection_escalate_uses_reflected_draft_and_reason(fake_mcp: None) -> None:
    reflected = "Your request for a lighter laptop was escalated because of a medical need."
    run = asyncio.run(
        run_react(
            REQUEST,
            model=react_model("DENY", "Denied: refresh interval not met."),
            reflect_model=reflection("DISAGREE", "ESCALATE", reflected, "Medical need (doctor, injury)"),
        )
    )
    assert run.decision == "ESCALATE"
    assert run.draft == reflected
    assert run.flagged is True
    assert run.ticket is not None
    assert run.ticket["reason"] == "Medical need (doctor, injury)"


def test_reflection_escalate_draft_with_invented_number_falls_back(fake_mcp: None) -> None:
    run = asyncio.run(
        run_react(
            REQUEST,
            model=react_model("DENY", "Denied: refresh interval not met."),
            reflect_model=reflection(
                "DISAGREE", "ESCALATE", "A reviewer will reply within 48 hours.", "Medical need"
            ),
        )
    )
    assert run.decision == "ESCALATE"
    assert run.draft == ESCALATED_DRAFT


def test_reflection_disagree_with_deny_keeps_generic_draft(fake_mcp: None) -> None:
    run = asyncio.run(
        run_react(
            "E011: my laptop is slow, can I get a new one?",
            model=react_model("APPROVE", "Approved."),
            reflect_model=reflection("DISAGREE", "DENY", "Your request is denied.", "Status is ineligible"),
        )
    )
    assert run.decision == "ESCALATE"
    assert run.draft == ESCALATED_DRAFT
    assert run.ticket is not None
    assert run.ticket["reason"] == "Status is ineligible"


def test_reflection_empty_reason_uses_fallback_ticket_reason(fake_mcp: None) -> None:
    run = asyncio.run(
        run_react(
            "E011: my laptop is slow, can I get a new one?",
            model=react_model("APPROVE", "Approved."),
            reflect_model=reflection("DISAGREE", "DENY", "Denied.", "  "),
        )
    )
    assert run.ticket is not None
    assert run.ticket["reason"] == "reflection_disagreement"
