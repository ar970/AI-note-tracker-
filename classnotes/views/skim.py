"""Skim view — for someone who was there and mostly followed it.

Target: five minutes. The discipline is subtraction — two points per section,
eight terms, one line each. If this grows past a screen or two it has stopped
being a skim and there is already a Full view for that.
"""

from __future__ import annotations

from classnotes.views import common

LABEL = "Skim · ~5 min"
POINTS_PER_SECTION = 2
MAX_TERMS = 8


def _one_line(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def render(artifact: dict) -> str:
    lines = common.header(artifact, LABEL)
    lines += common.diagram_block(artifact, "## The shape of it")

    sections = (artifact.get("summary") or {}).get("sections") or []
    if sections:
        lines += ["## The short version", ""]
        for section in sections:
            lines.append(f"**{section['heading']}**{common.section_meta(section)}")
            for point in (section.get("points") or [])[:POINTS_PER_SECTION]:
                lines.append(f"- {_one_line(point)}")
            if section.get("lecturer_stress"):
                lines.append(f"- ⭐ {_one_line(section['lecturer_stress'])}")
            lines.append("")

    terms = artifact.get("key_terms") or []
    if terms:
        lines += ["## Terms", ""]
        for term in terms[:MAX_TERMS]:
            lines.append(f"- **{term['term']}** — {_one_line(term['definition'], 90)}")
        if len(terms) > MAX_TERMS:
            lines.append(f"- _…and {len(terms) - MAX_TERMS} more in the full notes._")
        lines.append("")

    lines += common.video_block(artifact, "## If you got lost")
    lines += common.footer(artifact)
    return "\n".join(lines).rstrip() + "\n"
