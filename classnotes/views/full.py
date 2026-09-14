"""Full view — the default. Complete structured notes.

Pure reformatting of the master artifact. No model call, so adding views
costs nothing beyond the one generation.
"""

from __future__ import annotations

from classnotes.views import common

LABEL = "Full notes"


def render(artifact: dict) -> str:
    lines = common.header(artifact, LABEL)
    lines += common.diagram_block(artifact)

    sections = (artifact.get("summary") or {}).get("sections") or []
    if sections:
        lines += ["## Notes", ""]
        for section in sections:
            lines.append(f"### {section['heading']}{common.section_meta(section)}")
            lines.append("")
            lines += [f"- {point}" for point in section.get("points") or []]
            if section.get("lecturer_stress"):
                lines += ["", f"**Stressed:** {section['lecturer_stress']}"]
            if section.get("off_slide"):
                lines += ["", f"**Said in class, not on the deck:** {section['off_slide']}"]
            lines.append("")

    terms = artifact.get("key_terms") or []
    if terms:
        lines += ["## Key terms", "", "| Term | Meaning | Slide |", "|---|---|---|"]
        for term in terms:
            slide = term.get("slide_ref")
            heard = (
                f" <br>_heard as \"{term['corrected_from']}\"_"
                if term.get("corrected_from")
                else ""
            )
            lines.append(
                f"| **{term['term']}** | {term['definition']}{heard} | {slide if slide else '—'} |"
            )
        lines.append("")

    lines += common.video_block(artifact, "## Where the class moved fast")

    exam = artifact.get("exam_signals") or {}
    if exam.get("stressed") or exam.get("likely_questions"):
        lines += ["## For revision", ""]
        if exam.get("stressed"):
            lines += ["**Flagged as important**", ""]
            lines += [f"- {item}" for item in exam["stressed"]]
            lines.append("")
        if exam.get("likely_questions"):
            lines += ["**Questions this lecture supports**", ""]
            lines += [f"- {item}" for item in exam["likely_questions"]]
            lines.append("")

    if artifact.get("open_threads"):
        lines += ["## Left open", ""]
        lines += [f"- {item}" for item in artifact["open_threads"]]
        lines.append("")

    lines += common.footer(artifact)
    return "\n".join(lines).rstrip() + "\n"
