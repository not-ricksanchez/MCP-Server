"""Reflection tests — fake model, no Ollama."""

import json

from agent.reflection import apply_reflection, reflect
from agent.schemas import Outcome, ReflectionResult, Verdict


class FakeAdapter:
    def complete(self, messages: list[dict[str, str]], schema=None) -> str:
        return json.dumps(
            {
                "verdict": "AGREE",
                "decision": "APPROVE",
                "draft": "Your laptop replacement is approved under the 4-year policy.",
                "reason": "Decision matches eligible; tightened wording.",
            }
        )


class DisagreeAdapter:
    def complete(self, messages: list[dict[str, str]], schema=None) -> str:
        return json.dumps(
            {
                "verdict": "DISAGREE",
                "decision": "DENY",
                "draft": "A human reviewer will look at this request.",
                "reason": "APPROVE contradicts ineligible status.",
            }
        )


def test_parse_agree() -> None:
    result = ReflectionResult.from_output(
        json.dumps(
            {
                "verdict": "AGREE",
                "decision": "APPROVE",
                "draft": "Approved.",
                "reason": "ok",
            }
        )
    )
    assert result.verdict == Verdict.AGREE
    assert result.decision == Outcome.APPROVE
    assert result.draft.startswith("Approved.")


def test_reflect_agree_keeps_decision() -> None:
    result = reflect(
        FakeAdapter(),
        request="E001: laptop",
        observations=['{"status": "eligible"}'],
        decision="APPROVE",
        draft="Approved forever, never again an outage.",
    )
    assert result.verdict == Verdict.AGREE
    assert result.decision == Outcome.APPROVE
    assert apply_reflection("APPROVE", result.verdict, result.decision) == "APPROVE"
    assert "4-year policy" in result.draft


def test_reflect_disagree_escalates() -> None:
    result = reflect(
        DisagreeAdapter(),
        request="E002: monitor",
        observations=['{"status": "ineligible"}'],
        decision="APPROVE",
        draft="Your extra monitor is approved.",
    )
    assert result.verdict == Verdict.DISAGREE
    assert result.decision == Outcome.DENY
    assert apply_reflection("APPROVE", result.verdict, result.decision) == "ESCALATE"
    assert "human" in result.draft.lower()


def test_apply_reflection_mismatched_decision_escalates() -> None:
    assert apply_reflection("APPROVE", "AGREE", "DENY") == "ESCALATE"
    assert apply_reflection("DENY", "AGREE", "DENY") == "DENY"
