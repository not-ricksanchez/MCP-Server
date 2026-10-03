"""Model adapter tests — no Ollama."""

from agent.model_adapter import OllamaAdapter


class FakeAdapter:
    def complete(self, messages: list[dict[str, str]], schema=None) -> str:
        return f"echo:{messages[-1]['content']}"


def test_fake_adapter_complete() -> None:
    model = FakeAdapter()
    assert model.complete([{"role": "user", "content": "hello"}]) == "echo:hello"


def test_ollama_adapter_stores_model() -> None:
    adapter = OllamaAdapter(host="http://example.invalid:11434", model=" gemma3:12b ")
    assert adapter._model == "gemma3:12b"
    assert adapter._think is None


def test_ollama_adapter_think_off() -> None:
    adapter = OllamaAdapter(host="http://example.invalid:11434", model="qwen3:8b", think=False)
    assert adapter._model == "qwen3:8b"
    assert adapter._think is False
