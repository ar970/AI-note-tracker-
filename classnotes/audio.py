"""Audio preparation: normalise, then chunk if the file is too big to upload.

A 90-minute lecture off a phone is typically 80-150MB and well past any ASR
API's upload ceiling. We downmix to 16kHz mono (what Whisper resamples to
anyway) and split into overlapping windows so no word is lost at a seam.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegMissing(RuntimeError):
    pass


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise FFmpegMissing(
            "ffmpeg and ffprobe are required to prepare audio.\n"
            "  Ubuntu/Debian: sudo apt install ffmpeg\n"
            "  macOS:         brew install ffmpeg"
        )


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} failed:\n{result.stderr.strip()[-2000:]}"
        )
    return result


def duration_seconds(path: Path) -> float:
    _require_ffmpeg()
    result = _run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(result.stdout.strip())


def normalise(src: Path, dest: Path, bitrate: str = "48k") -> Path:
    """Downmix to 16kHz mono MP3. Strips video if handed a lecture recording."""
    _require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "libmp3lame", "-b:a", bitrate,
            str(dest),
        ]
    )
    return dest


@dataclass
class Chunk:
    path: Path
    start_seconds: float


def split(
    src: Path,
    out_dir: Path,
    *,
    chunk_seconds: int = 600,
    overlap_seconds: int = 10,
    bitrate: str = "48k",
    max_bytes: int = 20 * 1024 * 1024,
) -> list[Chunk]:
    """Split into overlapping chunks, or return the file as-is if it fits."""
    _require_ffmpeg()
    total = duration_seconds(src)

    if src.stat().st_size <= max_bytes:
        return [Chunk(path=src, start_seconds=0.0)]

    out_dir.mkdir(parents=True, exist_ok=True)
    stride = max(1, chunk_seconds - overlap_seconds)
    chunks: list[Chunk] = []
    index, start = 0, 0.0

    while start < total:
        dest = out_dir / f"chunk_{index:03d}.mp3"
        _run(
            [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}", "-i", str(src),
                "-t", str(chunk_seconds),
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "libmp3lame", "-b:a", bitrate,
                str(dest),
            ]
        )
        # ffmpeg writes a valid but empty file when seeking past the end.
        if dest.stat().st_size < 1024:
            dest.unlink(missing_ok=True)
            break
        chunks.append(Chunk(path=dest, start_seconds=start))
        index += 1
        start += stride

    return chunks
