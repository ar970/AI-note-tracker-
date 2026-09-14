"""Anthropic backend."""

from __future__ import annotations

from classnotes.llm.base import Completion, LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = "claude-opus-5"

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
        # `temperature` is accepted for interface symmetry and deliberately
        # unused: sampling parameters are not part of the SDK's Messages
        # surface at all, and the adaptive-thinking models reject them. Depth
        # is controlled by `effort` instead.
        del temperature

        import anthropic

        client = anthropic.Anthropic(api_key=self._require_key())

        # Cache the bulky, stable part (deck + transcript) so that regenerating
        # the master artifact with an improved prompt re-reads it at ~10% cost.
        # The spec assumes you will regenerate; this is what makes that cheap.
        system_blocks: list[dict] = []
        if cached_context:
            system_blocks.append(
                {
                    "type": "text",
                    "text": cached_context,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            )
        system_blocks.append({"type": "text", "text": system})

        # Stream: a full master artifact can run long, and a non-streaming
        # request at this max_tokens risks an HTTP timeout.
        with client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            detail = getattr(message, "stop_details", None)
            raise RuntimeError(
                "Claude declined this request"
                + (f" ({detail.category}): {detail.explanation}" if detail else ".")
            )

        text = "".join(b.text for b in message.content if b.type == "text")
        usage = message.usage
        return Completion(
            text=text,
            # Cache reads are billed at a tenth; count them separately from
            # fresh input so the cost line in the run summary stays honest.
            input_tokens=usage.input_tokens
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=usage.output_tokens,
            model=message.model,
            provider=self.name,
        )
