"""Google Gemini backend, over the documented generateContent REST shape."""

from __future__ import annotations

import requests

from classnotes.llm.base import Completion, LLMProvider

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    name = "gemini"
    # See the note in openai_provider.py: set LLM_MODEL in .env.
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
                "LLM_PROVIDER=gemini requires LLM_MODEL to be set in .env "
                "(e.g. LLM_MODEL=gemini-2.5-pro)."
            )
        system_text = f"{cached_context}\n\n{system}" if cached_context else system
        generation_config: dict = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        resp = requests.post(
            f"{BASE}/{self.model}:generateContent",
            headers={
                "x-goog-api-key": self._require_key(),
                "Content-Type": "application/json",
            },
            json={
                "systemInstruction": {"parts": [{"text": system_text}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": generation_config,
            },
            timeout=900,
        )
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(
                f"Gemini returned no candidates: {data.get('promptFeedback')}"
            )
        candidate = candidates[0]
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise RuntimeError(
                "Gemini hit maxOutputTokens; the response is truncated. "
                "Raise --max-tokens or shorten the transcript."
            )
        text = "".join(
            part.get("text", "") for part in candidate.get("content", {}).get("parts", [])
        )
        usage = data.get("usageMetadata", {})
        return Completion(
            text=text,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            model=self.model,
            provider=self.name,
        )
