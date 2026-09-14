"""[3] Align the transcript to the deck.

This is where the quality comes from. Everything downstream reads the aligned
text, not the raw transcript, so an hour spent on `prompts/align.md` is worth
more than any amount of work on the steps after it.
"""

from __future__ import annotations

from classnotes.config import PROMPT_DIR
from classnotes.costs import CostLedger
from classnotes.deck import Deck
from classnotes.llm import LLMProvider
from classnotes.transcribe import Transcript


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def build_context(deck: Deck | None, transcript_text: str) -> str:
    """The bulky, stable half of the request — cached where the provider can."""
    parts = []
    if deck and deck.slides:
        parts.append(
            f"# SLIDE DECK ({deck.source}, {len(deck.slides)} slides)\n\n"
            f"{deck.as_markdown()}"
        )
    else:
        parts.append(
            "# SLIDE DECK\n\n_No deck was supplied for this session._\n\n"
            "Work from the transcript alone. Do not invent slide numbers — use "
            "`Off-deck` headings throughout and flag uncertain terminology as "
            "`[unclear]` rather than guessing at spellings you cannot verify."
        )
    parts.append(f"# RAW TRANSCRIPT (timestamped, unedited ASR)\n\n{transcript_text}")
    return "\n\n---\n\n".join(parts)


def align(
    deck: Deck | None,
    transcript: Transcript,
    provider: LLMProvider,
    ledger: CostLedger,
) -> str:
    context = build_context(deck, transcript.as_timestamped())
    completion = provider.complete(
        system=load_prompt("align.md"),
        user=(
            "Align the transcript above against the deck now. Repair the terminology, "
            "normalise to English, preserve emphasis, and do not summarise."
        ),
        cached_context=context,
        max_tokens=32000,
        json_mode=False,
    )
    ledger.record_llm(completion.model, completion.input_tokens, completion.output_tokens)
    return completion.text.strip()
