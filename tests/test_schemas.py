"""Pydantic schema tests for model outputs — no Ollama."""

import json

import pytest
from pydantic import ValidationError

from agent.schemas import (
    Outcome,
    ReactStep,
    ReflectionResult,
    Verdict,
    parse_json_object,
)


def test_react_action_step() -> None:
    step = ReactStep.from_output(
        json.dumps(
            {
                "thought": "Look up the employee.",
                "action": "get_employee_info",
                "action_input": {"employee_id": "E001"},
            }
        )
    )
    assert step.action == "get_employee_info"
    assert step.decision is None
    assert step.action_input["employee_id"] == "E001"


def test_react_finish_step() -> None:
    step = ReactStep.from_output(
        '{"thought": "Eligible.", "decision": "APPROVE", "draft": "Approved."}'
    )
    assert step.decision == Outcome.APPROVE
    assert step.draft == "Approved."
    assert step.action is None


def test_react_action_input_from_json_string() -> None:
    step = ReactStep.from_output(
        '{"thought": "x", "action": "get_policy_limits", "action_input": "{\\"role\\": \\"standard\\"}"}'
    )
    assert step.action_input == {"role": "standard"}


def test_react_rejects_empty_step() -> None:
    with pytest.raises(ValidationError):
        ReactStep(thought="no action or decision")


def test_json_object_from_fenced_block() -> None:
    data = parse_json_object('```json\n{"verdict": "AGREE", "decision": "DENY", "draft": "No.", "reason": "ineligible"}\n```')
    result = ReflectionResult.model_validate(data)
    assert result.verdict == Verdict.AGREE
    assert result.decision == Outcome.DENY
