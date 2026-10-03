"""Parser tests for structured ReAct JSON — no Ollama, no MCP."""

from agent.agent import parse_action, parse_decision


def test_parse_tool_action() -> None:
    text = """{
      "thought": "Need the employee record.",
      "action": "get_employee_info",
      "action_input": {"employee_id": "E001"},
      "decision": null,
      "draft": null
    }"""
    name, args = parse_action(text)
    assert name == "get_employee_info"
    assert args["employee_id"] == "E001"


def test_parse_decision() -> None:
    text = """{
      "thought": "Policy allows this refresh.",
      "action": null,
      "action_input": {},
      "decision": "APPROVE",
      "draft": "Your laptop replacement is approved."
    }"""
    name, args = parse_action(text)
    assert name == "finish"
    assert args["decision"] == "APPROVE"
    decision, draft = parse_decision(text)
    assert decision == "APPROVE"
    assert "approved" in draft.lower()
