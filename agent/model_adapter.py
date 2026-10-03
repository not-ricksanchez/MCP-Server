"""LLM adapters. The agent calls ModelAdapter.complete; it does not import ollama."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class ModelAdapter(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel] | None = None,
    ) -> str:
        """Return assistant text. If schema is set, text is JSON for that model."""


class OllamaAdapter:
    def __init__(self, host: str, model: str, think: bool | None = None) -> None:
        from ollama import Client

        self._client = Client(host=host)
        self._model = model.strip()
        self._think = think

    def complete(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {}
        if self._think is not None:
            kwargs["think"] = self._think
        if schema is not None:
            kwargs["format"] = schema.model_json_schema()
        response = self._client.chat(model=self._model, messages=messages, **kwargs)
        message = response["message"] if isinstance(response, dict) else response.message
        content = message["content"] if isinstance(message, dict) else message.content
        return str(content).strip()
