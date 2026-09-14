"""OpenAI backend, over the documented Chat Completions REST shape."""

from __future__ import annotations

import requests

from classnotes.llm.base import Completion, LLMProvider

ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    name = "openai"
    # Deliberately unset: model IDs move faster than this file does. Set
    # LLM_MODEL in .env so you pick a model that exists today rather than one
    # that was current whenever this was written.
    default_model = ""

    def complete(
        self,
        system: str,
        user: str,
        *,
        cached_context: str | None = None,
        max_tokens: int = 16000,
        temperature: float = 0.2,
        json_mode: bool = False,
        effort: str = "high",
    ) -> Completion:
        if not self.model:
            raise RuntimeError(
                "LLM_PROVIDER=openai requires LLM_MODEL to be set in .env "
                "(e.g. LLM_MODEL=gpt-4.1)."
            )
        system_text = f"{cached_context}\n\n{system}" if cached_context else system
        body: dict = {
            "model": self.model,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        resp = requests.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._require_key()}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=900,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return Completion(
            text=data["choices"][0]["message"]["content"] or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
            provider=self.name,
        )
