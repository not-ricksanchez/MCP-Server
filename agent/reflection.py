"""Isolated review of ReAct Decision + Draft. No tools, no ReAct history."""

from __future__ import annotations

import re

from pydantic import ValidationError

from agent.model_adapter import ModelAdapter
from agent.schemas import Outcome, ReflectionResult, Verdict

REFLECT_SYSTEM = """You review the ReAct agent's Decision AND Draft against tool Observations.

This is not a new eligibility pass. Do not DISAGREE because policy interval_years (e.g. 4) differs from equipment age_years (e.g. 7.34). Those are different facts; both can be true.

AGREE when the Decision matches Observations:
- APPROVE only if a tool status is eligible and the reason is ordinary
- DENY only if a tool status is ineligible and the reason is ordinary
- ESCALATE if status is unknown or the case is ambiguous
and the Draft addresses the request without invented dates, SLAs, or promises.

Special circumstances override the tool status. If the Request mentions medical needs (doctor, injury, disability), accessibility, ergonomics, legal, security, an executive or policy exception, or claims a role or promotion, the only correct Decision is ESCALATE, even when status is eligible or ineligible. An APPROVE or DENY in that case is wrong: DISAGREE, set decision to ESCALATE, and give the special circumstance as the reason.

If the Decision is correct but the Draft wording is weak, still AGREE and rewrite the Draft.

DISAGREE when the Decision contradicts Observations (APPROVE vs ineligible/unknown, DENY vs eligible), when it ignores special circumstances, or when you would choose a different Decision.

Respond with a JSON object only, matching the schema: verdict, decision, draft, reason.
"""


def _as_outcome(value: str | Outcome | None) -> str | None:
    if value is None:
        return None
    return value.value if isinstance(value, Outcome) else str(value).upper()


def _as_verdict(value: str | Verdict) -> str:
    raw = value.value if isinstance(value, Verdict) else str(value).upper()
    if raw in {"DISAGREE", "ESCALATE"}:
        return Verdict.DISAGREE.value
    return Verdict.AGREE.value


def decisions_disagree(
    react_decision: str,
    verdict: str | Verdict,
    reflected_decision: str | Outcome | None,
) -> bool:
    if _as_verdict(verdict) == Verdict.DISAGREE.value:
        return True
    reflected = _as_outcome(reflected_decision)
    return bool(reflected) and reflected != str(react_decision).upper()


def apply_reflection(
    react_decision: str,
    verdict: str | Verdict,
    reflected_decision: str | Outcome | None,
) -> str:
    """Keep ReAct's decision on AGREE; ESCALATE when they disagree."""
    if decisions_disagree(react_decision, verdict, reflected_decision):
        return Outcome.ESCALATE.value
    return str(react_decision).upper()


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Numeric tokens with leading zeros dropped, so 2019-06-01 also supports "June 1, 2019"."""
    return {token.lstrip("0") or "0" for token in _NUMBER_RE.findall(text)}


def unsupported_numbers(draft: str, sources: list[str]) -> set[str]:
    """Numbers or date parts in the draft that appear in none of the sources."""
    supported: set[str] = set()
    for source in sources:
        supported |= _numbers(source)
    return _numbers(draft) - supported


def choose_draft(original: str, reflected: str, request: str, observations: list[str]) -> str:
    """Use the critic's rewrite only when it adds no numbers or dates the tools did not return."""
    if not reflected.strip():
        print("Reflected draft is empty; keeping the ReAct draft.")
        return original
    unsupported = unsupported_numbers(reflected, [request, *observations])
    if unsupported:
        print(f"Reflected draft cites {sorted(unsupported)} not found in Observations; keeping the ReAct draft.")
        return original
    return reflected


def reflect(
    model: ModelAdapter,
    request: str,
    observations: list[str],
    decision: str,
    draft: str,
) -> ReflectionResult:
    """Review Decision and Draft. Returns a structured ReflectionResult."""
    print("\n--- reflection ---")
    joined = "\n\n".join(observations) if observations else "(none)"
    text = model.complete(
        [
            {"role": "system", "content": REFLECT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Request: {request}\nDecision: {decision}\nDraft: {draft}\n\n"
                    f"Observations:\n{joined}"
                ),
            },
        ],
        schema=ReflectionResult,
    )
    print(text)
    try:
        result = ReflectionResult.from_output(text)
    except (TypeError, ValueError, ValidationError) as exc:
        print(f"reflection JSON invalid ({exc}); treating as AGREE with original draft")
        try:
            fallback_decision = Outcome(str(decision).upper())
        except ValueError:
            fallback_decision = Outcome.ESCALATE
        result = ReflectionResult(
            verdict=Verdict.AGREE,
            decision=fallback_decision,
            draft=draft,
            reason="Could not parse structured reflection output.",
        )
    return result
