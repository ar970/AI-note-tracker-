"""LLM provider registry.

`LLM_PROVIDER` in .env picks the backend. Nothing above this package knows
which one is in use, so measuring cost on a real lecture and then switching
vendors is a one-line change.
"""

from __future__ import annotations

from classnotes.config import Config
from classnotes.llm.base import Completion, LLMProvider


def get_provider(config: Config) -> LLMProvider:
    name = (config.llm_provider or "").strip().lower()

    if name == "anthropic":
        from classnotes.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config.anthropic_api_key, config.llm_model)
    if name == "openai":
        from classnotes.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(config.openai_api_key, config.llm_model)
    if name == "gemini":
        from classnotes.llm.gemini_provider import GeminiProvider

        return GeminiProvider(config.gemini_api_key, config.llm_model)
    if name == "fake":
        from classnotes.llm.fake_provider import FakeProvider

        return FakeProvider(None, config.llm_model)

    raise RuntimeError(
        f"Unknown LLM_PROVIDER={config.llm_provider!r}. "
        "Expected one of: anthropic, openai, gemini, fake."
    )


__all__ = ["Completion", "LLMProvider", "get_provider"]
