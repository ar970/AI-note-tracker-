"""A test double, not a feature.

Lets the pipeline run end-to-end with no API keys so you can verify that
alignment plumbing, master-artifact shape and view rendering all work before
you spend a rupee. It derives a structurally valid master artifact from the
deck's real headings — the *shape* is real, the *insight* is not.

Never ship notes produced by this. The CLI stamps every file it touches.
"""

from __future__ import annotations

import json
import re

from classnotes.llm.base import Completion, LLMProvider

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you",
    "are", "was", "were", "will", "can", "has", "have", "not", "but", "its",
    "what", "when", "how", "why", "who", "all", "any", "our", "their", "then",
}


def _candidate_terms(text: str, limit: int = 12) -> list[str]:
    """Multi-word Title Case phrases are a decent proxy for jargon."""
    phrases = re.findall(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+)\b", text)
    seen: dict[str, int] = {}
    for phrase in phrases:
        if phrase.split()[0].lower() in STOPWORDS:
            continue
        seen[phrase] = seen.get(phrase, 0) + 1
    ranked = sorted(seen, key=lambda p: (-seen[p], p))
    return ranked[:limit]


class FakeProvider(LLMProvider):
    name = "fake"
    default_model = "fake-deterministic-v0"

    def __init__(self, api_key=None, model=""):
        super().__init__(api_key or "none", model)

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
        context = cached_context or user
        # The master call sees both the deck and the aligned transcript, and
        # both carry slide headings — dedupe so the placeholder isn't doubled.
        found: dict[int, str] = {}
        for num, title in re.findall(
            r"^#{2,3} .*?Slide (\d+)(?:\s*[—-]\s*(.*))?$", context, re.MULTILINE
        ):
            found.setdefault(int(num), (title or "").strip())
        slides = [(str(n), found[n]) for n in sorted(found)]

        if not json_mode:
            # The alignment step wants prose back.
            body = "\n\n".join(
                f"## Slide {num} — {title or 'Untitled'}\n"
                f"_[fake provider: no real alignment was performed]_"
                for num, title in slides[:40]
            )
            return self._wrap(body or "_[fake provider: nothing to align]_")

        sections = [
            {
                "heading": (title or f"Slide {num}").strip(),
                "slide_refs": [int(num)],
                "time_range": None,
                "points": [
                    "[fake provider] Placeholder point derived from the deck heading.",
                    "[fake provider] Run with real keys for actual content.",
                ],
                "lecturer_stress": None,
                "off_slide": None,
            }
            for num, title in slides[:12]
        ] or [
            {
                "heading": "No deck supplied",
                "slide_refs": [],
                "time_range": None,
                "points": ["[fake provider] Placeholder."],
                "lecturer_stress": None,
                "off_slide": None,
            }
        ]

        terms = _candidate_terms(context)
        nodes = [s["heading"][:38].replace('"', "'") for s in sections[:6]]
        mermaid_lines = ["flowchart TD"] + [
            f'    n{i}["{name}"] --> n{i + 1}' for i, name in enumerate(nodes[:-1])
        ]
        if len(nodes) == 1:
            mermaid_lines.append(f'    n0["{nodes[0]}"]')
        elif nodes:
            mermaid_lines.append(f'    n{len(nodes) - 1}["{nodes[-1]}"]')

        master = {
            "summary": {
                "headline": "[fake provider] Structurally valid placeholder artifact.",
                "sections": sections,
            },
            "diagram": {"mermaid": "\n".join(mermaid_lines)},
            "key_terms": [
                {
                    "term": t,
                    "definition": "[fake provider] No definition generated.",
                    "slide_ref": None,
                    "corrected_from": None,
                }
                for t in terms
            ],
            "concepts": [
                {
                    "name": s["heading"],
                    "weight": round(1.0 - (i * 0.1), 2),
                    "time_range": None,
                    "coverage": "rushed" if i % 3 == 2 else "normal",
                    "slide_refs": s["slide_refs"],
                }
                for i, s in enumerate(sections[:8])
            ],
            "exam_signals": {
                "stressed": ["[fake provider] No stress signals detected."],
                "likely_questions": ["[fake provider] No questions generated."],
            },
            "open_threads": [],
        }
        return self._wrap(json.dumps(master, indent=2))

    def _wrap(self, text: str) -> Completion:
        return Completion(
            text=text,
            input_tokens=0,
            output_tokens=0,
            model=self.model,
            provider=self.name,
        )
