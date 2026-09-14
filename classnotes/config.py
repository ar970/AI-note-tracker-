"""Runtime configuration, loaded from environment / .env.

Nothing here is institution-specific. v0 is a script over a folder; the
only state that exists is files on disk under `data/sessions/<id>/`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CLASSNOTES_DATA_DIR", REPO_ROOT / "data" / "sessions"))
PROMPT_DIR = REPO_ROOT / "prompts"


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # --- [1] transcription -------------------------------------------------
    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    asr_model: str = field(
        default_factory=lambda: os.getenv("ASR_MODEL", "whisper-large-v3-turbo")
    )
    # Hinglish: force "en" so the lecturer's Hindi comes back romanised in
    # Latin script rather than Devanagari. Students read the Latin version;
    # a deck full of Devanagari asides is worse than useless. Set to "hi"
    # only if a lecture is genuinely Hindi-medium.
    lecture_language: str = field(
        default_factory=lambda: os.getenv("LECTURE_LANGUAGE", "en")
    )
    # Groq's upload ceiling. Free tier is 25MB; dev tier is higher. We chunk
    # below this regardless so a 90-minute lecture never bounces.
    max_chunk_mb: float = field(
        default_factory=lambda: float(os.getenv("MAX_CHUNK_MB", "20"))
    )
    chunk_seconds: int = field(
        default_factory=lambda: int(os.getenv("CHUNK_SECONDS", "600"))
    )
    chunk_overlap_seconds: int = field(
        default_factory=lambda: int(os.getenv("CHUNK_OVERLAP_SECONDS", "10"))
    )
    audio_bitrate: str = field(default_factory=lambda: os.getenv("AUDIO_BITRATE", "48k"))

    # --- [3][4] generation -------------------------------------------------
    # Provider-agnostic on purpose: you have not measured cost yet, so nothing
    # here should lock you to a vendor before you have that number.
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic")
    )
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    gemini_api_key: str | None = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY")
    )

    # --- [4] video lookup --------------------------------------------------
    youtube_api_key: str | None = field(
        default_factory=lambda: os.getenv("YOUTUBE_API_KEY")
    )

    # --- housekeeping ------------------------------------------------------
    # "Delete raw audio after processing unless you have a reason to keep it."
    # The transcript is kept either way, so regenerating the master artifact
    # with better prompts never needs the audio again.
    delete_audio_after: bool = field(
        default_factory=lambda: _flag("DELETE_AUDIO_AFTER", False)
    )

    def require_groq(self) -> str:
        if not self.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add it, "
                "or pass --transcript to skip step [1] and reuse an existing one."
            )
        return self.groq_api_key


CONFIG = Config()
