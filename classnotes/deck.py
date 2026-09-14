"""[2] Slide extraction.

The deck is worth more than it looks. It gives you:

  - the correct spelling of every technical term (ASR will not get these right)
  - the lecture's intended structure, free — slide titles are section headers
  - an ordering to anchor the transcript against

So this module runs *before* transcription as well as after: its `terms()`
output seeds Whisper's decoder prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")
# Capitalised phrases, allowing the lowercase connectors that hold real terms
# together ("Points of Parity", "Return on Investment"). Capped at four words.
TITLE_PHRASE = re.compile(
    r"\b[A-Z][a-z]{2,}(?:\s+(?:of|on|in|and|for|the|to|per|vs)?\s*[A-Z][a-z]{2,}){0,3}\b"
)
STOPWORDS = {
    "The", "And", "For", "With", "That", "This", "From", "Into", "Your",
    "What", "When", "How", "Why", "Who", "All", "Any", "Our", "Their",
    "Slide", "Lecture", "Chapter", "Unit", "Page", "Introduction", "Agenda",
    "Note", "Example", "Summary", "Overview", "Today", "Next", "Recap",
}


@dataclass
class Slide:
    number: int
    title: str
    body: list[str]
    notes: str = ""

    def as_markdown(self) -> str:
        head = f"## Slide {self.number}" + (f" — {self.title}" if self.title else "")
        lines = [head]
        lines += [f"- {line}" for line in self.body]
        if self.notes:
            lines.append(f"> Speaker notes: {self.notes}")
        return "\n".join(lines)


@dataclass
class Deck:
    slides: list[Slide]
    source: str

    def as_markdown(self) -> str:
        return "\n\n".join(slide.as_markdown() for slide in self.slides)

    def terms(self, limit: int = 60) -> list[str]:
        """Candidate technical vocabulary, ranked by how deck-specific it looks.

        Whisper's decoder prompt is ~224 tokens, so this list is a small budget
        that has to be spent well. Two rules keep it clean:

        - **Single words only count from slide titles.** Every bullet begins
          with a capital letter, so matching single capitalised words anywhere
          fills the budget with "Four", "Dividing", "Harder" — words ASR was
          never going to get wrong, crowding out the terms it will.
        - **Multi-word phrases and acronyms count anywhere.** These are exactly
          what a distant mic mangles, and they are unambiguously deck-specific.
        """
        scores: dict[str, float] = {}

        def add(text: str, weight: float, allow_single: bool) -> None:
            for match in ACRONYM.findall(text):
                scores[match] = scores.get(match, 0.0) + weight * 1.5
            for match in TITLE_PHRASE.findall(text):
                match = " ".join(match.split())
                words = match.split()
                if len(match) < 4 or words[0] in STOPWORDS:
                    continue
                if len(words) == 1 and not allow_single:
                    continue
                scores[match] = scores.get(match, 0.0) + weight

        for slide in self.slides:
            add(slide.title, 3.0, allow_single=True)
            for line in slide.body:
                add(line, 1.0, allow_single=False)
            if slide.notes:
                add(slide.notes, 0.5, allow_single=False)

        ranked = sorted(scores, key=lambda t: (-scores[t], t))
        return ranked[:limit]


def _clean(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip(" \t•-–—·")
        if len(line) > 1:
            out.append(line)
    return out


def _from_pdf(path: Path) -> Deck:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    slides: list[Slide] = []
    for index, page in enumerate(reader.pages, start=1):
        lines = _clean((page.extract_text() or "").splitlines())
        title = lines[0] if lines else ""
        slides.append(Slide(number=index, title=title, body=lines[1:]))
    return Deck(slides=slides, source=path.name)


def _from_pptx(path: Path) -> Deck:
    from pptx import Presentation

    presentation = Presentation(str(path))
    slides: list[Slide] = []
    for index, slide in enumerate(presentation.slides, start=1):
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text.strip()

        body: list[str] = []
        for shape in slide.shapes:
            if shape is slide.shapes.title or not shape.has_text_frame:
                continue
            body.extend(p.text for p in shape.text_frame.paragraphs)

        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()

        slides.append(
            Slide(number=index, title=title, body=_clean(body), notes=" ".join(notes.split()))
        )
    return Deck(slides=slides, source=path.name)


def load(path: Path) -> Deck:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _from_pdf(path)
    if suffix in {".pptx", ".ppt"}:
        if suffix == ".ppt":
            raise ValueError(
                "Legacy .ppt is not supported. Open it and re-save as .pptx or export a PDF."
            )
        return _from_pptx(path)
    raise ValueError(f"Unsupported deck format: {path.suffix} (expected .pdf or .pptx)")
