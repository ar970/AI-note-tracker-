"""Provider-agnostic LLM interface.

One method, `complete()`. Every provider returns the same `Completion` so
`align.py` and `master.py` never learn which vendor is behind them. Swapping
providers is a config change, not a code change.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""

    def json(self) -> dict:
        """Parse the response as JSON, tolerating fenced code blocks.

        Models wrap JSON in ```json fences often enough that handling it here
        is cheaper than re-running a 30k-token call because of three backticks.
        """
        text = self.text.strip()
        fence = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Last resort: grab the outermost brace-balanced object.
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise


class LLMProvider(ABC):
    name: str = "base"
    default_model: str = ""

    def __init__(self, api_key: str | None, model: str = ""):
        self.api_key = api_key
        self.model = model or self.default_model

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 8000,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> Completion:
        ...

    def _require_key(self) -> str:
        if not self.api_key:
            raise RuntimeError(
                f"{self.name} selected as LLM_PROVIDER but its API key is not set."
            )
        return self.api_key
