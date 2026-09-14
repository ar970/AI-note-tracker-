"""[1] Transcribe audio via Groq's hosted Whisper.

Two things matter more than the model choice:

1. **Vocabulary biasing.** Whisper accepts a `prompt` that biases decoding.
   Seeding it with terms lifted from the slide deck is the cheapest accuracy
   win available — it fixes jargon *before* the transcript exists, rather than
   asking a language model to guess at it afterwards.

2. **Language forcing for Hinglish.** An ILS lecturer switching between English
   and Hindi mid-sentence will, on auto-detect, produce chunks in Devanagari
   and chunks in Latin script in the same file. Forcing `en` keeps everything
   in Latin script, which is both readable and far easier to align against an
   English deck. Set LECTURE_LANGUAGE=hi only for a genuinely Hindi-medium class.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from classnotes import audio
from classnotes.config import Config
from classnotes.costs import CostLedger

ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
# Whisper truncates the decoder prompt at 224 tokens; stay under it.
MAX_PROMPT_CHARS = 700


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[Segment]
    language: str
    duration_seconds: float
    model: str

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()

    def as_timestamped(self) -> str:
        """Timestamped lines. The alignment step needs these to place concepts
        in time — that's what drives 'the lecturer rushed this' later."""
        return "\n".join(f"[{_hhmmss(s.start)}] {s.text.strip()}" for s in self.segments)

    def to_json(self) -> str:
        return json.dumps(
            {
                "language": self.language,
                "duration_seconds": self.duration_seconds,
                "model": self.model,
                "segments": [asdict(s) for s in self.segments],
            },
            indent=2,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "Transcript":
        data = json.loads(raw)
        return cls(
            segments=[Segment(**s) for s in data["segments"]],
            language=data.get("language", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            model=data.get("model", ""),
        )


def _hhmmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def build_vocabulary_prompt(deck_terms: list[str]) -> str:
    """Pack deck vocabulary into Whisper's decoder prompt, longest first.

    Longest-first because multi-word technical phrases are the ones ASR
    mangles worst, and the budget is small enough to be worth spending well.
    """
    if not deck_terms:
        return ""
    ordered = sorted(dict.fromkeys(deck_terms), key=len, reverse=True)
    prompt, chosen = "This is a university lecture. Key terms:", []
    for term in ordered:
        candidate = f"{prompt} {', '.join(chosen + [term])}."
        if len(candidate) > MAX_PROMPT_CHARS:
            break
        chosen.append(term)
    return f"{prompt} {', '.join(chosen)}." if chosen else ""


def merge_chunk_segments(chunked: list[tuple[float, list[Segment]]]) -> list[Segment]:
    """Stitch per-chunk segments back into one timeline.

    Chunks overlap so no word is cut at a seam, which means the overlap region
    gets transcribed twice. The seam is resolved by giving the overlap to the
    earlier chunk: a segment is dropped when its midpoint falls inside the span
    the previous chunk already covered.

    Two details that matter more than they look:

    - **Midpoint, not start.** ASR segment boundaries drift by a second or two,
      so a start-time test throws away words that genuinely belong to the later
      chunk.
    - **Observed coverage, not the configured overlap.** Deduping against
      `CHUNK_OVERLAP_SECONDS` assumes every chunk really does overlap its
      predecessor by exactly that much. When that assumption breaks — a
      re-stitched run, a hand-assembled list, a future change to how chunks are
      cut — the rule silently deletes real speech. Notes quietly missing ten
      minutes are far harder to spot than a crash, so the seam is computed from
      where the previous chunk's audio actually ended.

    `chunked` is [(chunk_start_seconds, chunk_relative_segments)], in any order.
    """
    merged: list[Segment] = []
    covered_until: float | None = None

    for chunk_start, segments in sorted(chunked, key=lambda c: c[0]):
        chunk_end = covered_until
        for segment in segments:
            start = segment.start + chunk_start
            end = segment.end + chunk_start
            if covered_until is not None and (start + end) / 2 < covered_until:
                continue
            merged.append(Segment(start=start, end=end, text=segment.text))
            chunk_end = end if chunk_end is None else max(chunk_end, end)
        covered_until = chunk_end

    merged.sort(key=lambda s: s.start)
    return merged


def _transcribe_one(
    path: Path, config: Config, vocabulary_prompt: str
) -> tuple[list[Segment], str, float]:
    with path.open("rb") as handle:
        form = {
            "model": (None, config.asr_model),
            "response_format": (None, "verbose_json"),
            "temperature": (None, "0"),
            "file": (path.name, handle, "audio/mpeg"),
        }
        if config.lecture_language:
            form["language"] = (None, config.lecture_language)
        if vocabulary_prompt:
            form["prompt"] = (None, vocabulary_prompt)

        response = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {config.require_groq()}"},
            files=form,
            timeout=1800,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Groq ASR failed ({response.status_code}): {response.text[:800]}")

    data = response.json()
    segments = [
        Segment(start=float(s["start"]), end=float(s["end"]), text=s["text"])
        for s in data.get("segments", [])
    ]
    if not segments and data.get("text"):
        # verbose_json should always give segments, but never lose the text.
        segments = [Segment(start=0.0, end=float(data.get("duration", 0.0)), text=data["text"])]
    return segments, data.get("language", ""), float(data.get("duration", 0.0))


def transcribe(
    audio_path: Path,
    config: Config,
    ledger: CostLedger,
    *,
    work_dir: Path,
    deck_terms: list[str] | None = None,
) -> Transcript:
    prepared = audio.normalise(
        audio_path, work_dir / "normalised.mp3", bitrate=config.audio_bitrate
    )
    total_seconds = audio.duration_seconds(prepared)
    chunks = audio.split(
        prepared,
        work_dir / "chunks",
        chunk_seconds=config.chunk_seconds,
        overlap_seconds=config.chunk_overlap_seconds,
        bitrate=config.audio_bitrate,
        max_bytes=int(config.max_chunk_mb * 1024 * 1024),
    )

    vocabulary_prompt = build_vocabulary_prompt(deck_terms or [])
    if vocabulary_prompt:
        print(f"  seeding ASR vocabulary with {len(deck_terms or [])} deck terms")
    print(f"  transcribing {len(chunks)} chunk(s), {total_seconds / 60:.1f} min total")

    collected: list[tuple[float, list[Segment]]] = []
    language = ""
    for i, chunk in enumerate(chunks):
        segments, chunk_language, _ = _transcribe_one(chunk.path, config, vocabulary_prompt)
        language = language or chunk_language
        collected.append((chunk.start_seconds, segments))
        print(f"    chunk {i + 1}/{len(chunks)} done ({len(segments)} segments)")

    merged = merge_chunk_segments(collected)
    ledger.record_asr(total_seconds, config.asr_model)
    return Transcript(
        segments=merged,
        language=language,
        duration_seconds=total_seconds,
        model=config.asr_model,
    )
