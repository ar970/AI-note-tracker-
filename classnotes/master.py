"""[4] Generate the master artifact.

One artifact per session, versioned, never overwritten. Every view renders
from this; corrections are applied here and regenerate all of them. If a view
ever needs something this file doesn't carry, the fix belongs here — not in
the view.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from classnotes.align import load_prompt
from classnotes.costs import CostLedger
from classnotes.deck import Deck
from classnotes.llm import LLMProvider

SCHEMA_VERSION = 1
# Mermaid chokes on these inside a label; the prompt forbids them, this
# enforces it. A diagram that doesn't render is worse than a plain list.
LABEL_FORBIDDEN = re.compile(r'[()\[\]{}#;"`]')


def sanitise_mermaid(source: str) -> str:
    """Strip label-breaking characters and guarantee a flowchart header."""
    if not source or not source.strip():
        return ""

    def scrub(match: re.Match) -> str:
        return f'["{LABEL_FORBIDDEN.sub("", match.group(1)).strip()}"]'

    cleaned = re.sub(r'\["([^"]*)"\]', scrub, source.strip())
    # Bare labels the model wrote without quotes: n1[Some label]
    cleaned = re.sub(
        r"\[([^\"\]\n]+)\]",
        lambda m: f'["{LABEL_FORBIDDEN.sub("", m.group(1)).strip()}"]',
        cleaned,
    )
    first = cleaned.splitlines()[0].strip().lower()
    if not first.startswith(("flowchart", "graph", "sequencediagram", "mindmap")):
        cleaned = "flowchart TD\n" + cleaned
    return cleaned


def _normalise(payload: dict) -> dict:
    """Fill in anything the model omitted so views never crash on a missing key."""
    summary = payload.get("summary") or {}
    sections = []
    for raw in summary.get("sections") or []:
        sections.append(
            {
                "heading": (raw.get("heading") or "Untitled section").strip(),
                "slide_refs": [s for s in (raw.get("slide_refs") or []) if isinstance(s, int)],
                "time_range": raw.get("time_range"),
                "points": [p for p in (raw.get("points") or []) if isinstance(p, str) and p.strip()],
                "lecturer_stress": raw.get("lecturer_stress"),
                "off_slide": raw.get("off_slide"),
            }
        )

    exam = payload.get("exam_signals") or {}
    return {
        "summary": {
            "headline": (summary.get("headline") or "").strip(),
            "sections": sections,
        },
        "diagram": {"mermaid": sanitise_mermaid((payload.get("diagram") or {}).get("mermaid", ""))},
        "key_terms": [
            {
                "term": (t.get("term") or "").strip(),
                "definition": (t.get("definition") or "").strip(),
                "slide_ref": t.get("slide_ref"),
                "corrected_from": t.get("corrected_from"),
            }
            for t in (payload.get("key_terms") or [])
            if (t.get("term") or "").strip()
        ],
        "concepts": [
            {
                "name": (c.get("name") or "").strip(),
                "weight": float(c.get("weight") or 0.0),
                "time_range": c.get("time_range"),
                "coverage": c.get("coverage") if c.get("coverage") in
                {"rushed", "normal", "deep"} else "normal",
                "slide_refs": [s for s in (c.get("slide_refs") or []) if isinstance(s, int)],
            }
            for c in (payload.get("concepts") or [])
            if (c.get("name") or "").strip()
        ],
        "exam_signals": {
            "stressed": [s for s in (exam.get("stressed") or []) if isinstance(s, str)],
            "likely_questions": [
                q for q in (exam.get("likely_questions") or []) if isinstance(q, str)
            ],
        },
        "open_threads": [t for t in (payload.get("open_threads") or []) if isinstance(t, str)],
        "videos": [],  # filled by videos.py
    }


def generate(
    session: dict,
    deck: Deck | None,
    aligned_text: str,
    provider: LLMProvider,
    ledger: CostLedger,
) -> dict:
    context_parts = []
    if deck and deck.slides:
        context_parts.append(
            f"# SLIDE DECK ({deck.source}, {len(deck.slides)} slides)\n\n{deck.as_markdown()}"
        )
    context_parts.append(f"# ALIGNED TRANSCRIPT\n\n{aligned_text}")

    completion = provider.complete(
        system=load_prompt("master.md"),
        user=(
            f"Session: {session.get('course') or 'Unknown course'} — "
            f"{session.get('topic') or 'topic not given'} "
            f"({session.get('date') or 'date not given'}).\n\n"
            "Produce the master artifact JSON for the lecture above. Output JSON only."
        ),
        cached_context="\n\n---\n\n".join(context_parts),
        max_tokens=16000,
        json_mode=True,
    )
    ledger.record_llm(completion.model, completion.input_tokens, completion.output_tokens)

    artifact = _normalise(completion.json())
    artifact["schema_version"] = SCHEMA_VERSION
    artifact["session"] = session
    artifact["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    artifact["generated_by"] = {"provider": completion.provider, "model": completion.model}
    return artifact


def next_version(session_dir: Path) -> int:
    """Masters are versioned and never overwritten — you will regenerate these
    as the prompts improve, and you want to be able to compare."""
    existing = sorted(session_dir.glob("master.v*.json"))
    versions = [
        int(m.group(1))
        for path in existing
        if (m := re.match(r"master\.v(\d+)\.json$", path.name))
    ]
    return max(versions, default=0) + 1


def save(artifact: dict, session_dir: Path) -> Path:
    version = next_version(session_dir)
    artifact["version"] = version
    path = session_dir / f"master.v{version}.json"
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = session_dir / "master.latest.json"
    latest.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
