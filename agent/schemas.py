"""Pydantic schemas for LLM turns. Ollama is asked to emit JSON matching these."""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Outcome(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class Verdict(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"


def parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output was not a JSON object")
    return data


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_output(cls, text: str) -> Self:
        return cls.model_validate(parse_json_object(text))


class ReactStep(ModelOutput):
    """One ReAct turn: either call a tool or finish with a decision."""

    thought: str = Field(description="One sentence of reasoning")
    action: str | None = Field(
        default=None,
        description="MCP tool name when more facts are needed; null when deciding",
    )
    action_input: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON arguments for the tool; empty object when deciding",
    )
    decision: Outcome | None = Field(
        default=None,
        description="APPROVE, DENY, or ESCALATE when finished; null when calling a tool",
    )
    draft: str | None = Field(
        default=None,
        description="Employee-facing reply when deciding; null when calling a tool",
    )

    @field_validator("action_input", mode="before")
    @classmethod
    def _coerce_action_input(cls, value: Any) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {"_unparsed": value}
            if isinstance(parsed, dict):
                return parsed
            return {"_unparsed": value}
        return {"_unparsed": str(value)}

    @field_validator("action", "draft", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("decision", mode="before")
    @classmethod
    def _upper_decision(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return value.upper()
        return value

    @model_validator(mode="after")
    def _action_or_decision(self) -> ReactStep:
        if self.action:
            return self
        if self.decision:
            return self
        raise ValueError("set action (tool call) or decision (finish), not neither")


class ReflectionResult(ModelOutput):
    """Critic view of the ReAct Decision and Draft."""

    verdict: Verdict = Field(description="AGREE if Decision matches Observations, else DISAGREE")
    decision: Outcome = Field(description="Your view of the correct Decision")
    draft: str = Field(description="Employee-facing text; if DISAGREE, say a human will review")
    reason: str = Field(description="One sentence")

    @field_validator("verdict", "decision", mode="before")
    @classmethod
    def _upper_enums(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.upper()
        return value
