"""v0 entry point. A folder and a script — no database, no server, no login.

    python -m classnotes run --audio lecture.m4a --deck slides.pdf \
        --course "Marketing Management" --topic "Segmentation" --date 2026-09-14

Everything lands in data/sessions/<session-id>/. You paste the markdown into
the class WhatsApp group by hand. That is the whole delivery mechanism, and it
is enough to answer the only question that matters right now: does anyone chase
you for the next one?
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date as date_cls
from pathlib import Path

from classnotes import align as align_step
from classnotes import deck as deck_step
from classnotes import master as master_step
from classnotes import transcribe as transcribe_step
from classnotes import videos as videos_step
from classnotes import views as views_step
from classnotes.config import CONFIG, DATA_DIR
from classnotes.costs import CostLedger
from classnotes.llm import get_provider


def _say(stage: str, message: str) -> None:
    print(f"[{stage}] {message}", flush=True)


def _session_dir(session_id: str) -> Path:
    path = DATA_DIR / session_id
    (path / "views").mkdir(parents=True, exist_ok=True)
    (path / "work").mkdir(parents=True, exist_ok=True)
    return path


def _default_session_id(args) -> str:
    stem = Path(args.audio).stem if args.audio else "session"
    when = args.date or date_cls.today().isoformat()
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in stem).strip("-").lower()
    return f"{when}-{slug}"[:80]


def _render_views(artifact: dict, session_dir: Path, names: list[str]) -> list[Path]:
    written = []
    for name in names:
        try:
            content = views_step.render(name, artifact)
        except NotImplementedError as exc:
            _say("5/6", f"skipping '{name}': {exc}")
            continue
        path = session_dir / "views" / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def cmd_run(args: argparse.Namespace) -> int:
    if not args.audio and not args.transcript:
        print("error: pass --audio, or --transcript to reuse an existing one.", file=sys.stderr)
        return 2

    if args.provider:
        CONFIG.llm_provider = args.provider
    if args.model:
        CONFIG.llm_model = args.model

    session_id = args.session_id or _default_session_id(args)
    session_dir = _session_dir(session_id)
    ledger = CostLedger()

    # --- [2] deck first: its vocabulary improves the transcription ---------
    parsed_deck = None
    if args.deck:
        parsed_deck = deck_step.load(Path(args.deck))
        _say("2/6", f"deck: {len(parsed_deck.slides)} slides from {parsed_deck.source}")
        if parsed_deck.looks_scanned:
            _say(
                "2/6",
                f"WARNING: only {parsed_deck.text_characters} characters of text across "
                f"{len(parsed_deck.slides)} slides — this deck looks scanned or "
                "image-only. Terminology correction and slide anchoring will barely "
                "work. Get a text-based PDF or the original .pptx if you can.",
            )
        (session_dir / "deck.md").write_text(parsed_deck.as_markdown(), encoding="utf-8")
    else:
        _say("2/6", "no deck supplied — alignment will be much weaker (see README)")

    # --- [1] transcribe ----------------------------------------------------
    transcript_path = session_dir / "transcript.json"
    if args.transcript:
        transcript = transcribe_step.Transcript.from_json(
            Path(args.transcript).read_text(encoding="utf-8")
        )
        _say("1/6", f"reusing transcript ({len(transcript.segments)} segments)")
    elif transcript_path.exists() and not args.force:
        transcript = transcribe_step.Transcript.from_json(
            transcript_path.read_text(encoding="utf-8")
        )
        _say("1/6", f"reusing cached transcript ({len(transcript.segments)} segments)")
    else:
        _say("1/6", "transcribing")
        transcript = transcribe_step.transcribe(
            Path(args.audio),
            CONFIG,
            ledger,
            work_dir=session_dir / "work",
            deck_terms=parsed_deck.terms() if parsed_deck else None,
        )
        transcript_path.write_text(transcript.to_json(), encoding="utf-8")
        (session_dir / "transcript.raw.txt").write_text(transcript.text, encoding="utf-8")

    provider = get_provider(CONFIG)
    _say("3/6", f"using {provider.name}/{provider.model or '(model unset)'}")

    # --- [3] align ---------------------------------------------------------
    aligned_path = session_dir / "aligned.md"
    if aligned_path.exists() and not args.force:
        aligned = aligned_path.read_text(encoding="utf-8")
        _say("3/6", "reusing cached alignment (--force to redo)")
    else:
        _say("3/6", "aligning transcript to deck")
        aligned = align_step.align(parsed_deck, transcript, provider, ledger)
        aligned_path.write_text(aligned, encoding="utf-8")

    # --- [4] master artifact ----------------------------------------------
    _say("4/6", "generating master artifact")
    session_meta = {
        "session_id": session_id,
        "course": args.course,
        "topic": args.topic,
        "date": args.date or date_cls.today().isoformat(),
        "instructor": args.instructor,
        "duration_seconds": transcript.duration_seconds,
        "deck_slides": len(parsed_deck.slides) if parsed_deck else 0,
    }
    artifact = master_step.generate(session_meta, parsed_deck, aligned, provider, ledger)

    _say("4/6", "looking up videos for rushed concepts")
    videos_step.attach(artifact, CONFIG.youtube_api_key)
    rushed = len(artifact.get("videos") or [])
    _say("4/6", f"{rushed} concept(s) flagged as rushed" if rushed else
         "nothing flagged as rushed — no videos, which is the right answer")

    master_path = master_step.save(artifact, session_dir)
    _say("4/6", f"master v{artifact['version']} -> {master_path.name}")

    # --- [5][6] views ------------------------------------------------------
    written = _render_views(artifact, session_dir, args.views.split(","))
    for path in written:
        _say("6/6", f"wrote {path}")

    # --- housekeeping ------------------------------------------------------
    shutil.rmtree(session_dir / "work", ignore_errors=True)
    if args.delete_audio or CONFIG.delete_audio_after:
        if args.audio and Path(args.audio).exists():
            Path(args.audio).unlink()
            _say("6/6", f"deleted source audio {args.audio} (transcript retained)")

    print()
    print(ledger.summary())
    print()
    print(f"Session folder: {session_dir}")
    return 0


def cmd_regenerate(args: argparse.Namespace) -> int:
    """Re-run steps [4]-[6] from the stored alignment.

    This is the loop you will actually live in: improve prompts/master.md, run
    this, diff the new version against the old. It never re-transcribes and
    never re-aligns, so iterating on output quality costs one generation.
    """
    if args.provider:
        CONFIG.llm_provider = args.provider
    if args.model:
        CONFIG.llm_model = args.model

    session_dir = DATA_DIR / args.session_id
    aligned_path = session_dir / "aligned.md"
    if not aligned_path.exists():
        print(f"error: no aligned.md in {session_dir}", file=sys.stderr)
        return 2

    previous = json.loads((session_dir / "master.latest.json").read_text(encoding="utf-8"))
    parsed_deck = None
    if args.deck:
        parsed_deck = deck_step.load(Path(args.deck))

    ledger = CostLedger()
    provider = get_provider(CONFIG)
    _say("4/6", f"regenerating master from stored alignment ({provider.name})")

    artifact = master_step.generate(
        previous.get("session", {}),
        parsed_deck,
        aligned_path.read_text(encoding="utf-8"),
        provider,
        ledger,
    )
    videos_step.attach(artifact, CONFIG.youtube_api_key)
    master_path = master_step.save(artifact, session_dir)
    _say("4/6", f"master v{artifact['version']} -> {master_path.name} "
                f"(v{previous.get('version')} kept for comparison)")

    for path in _render_views(artifact, session_dir, args.views.split(",")):
        _say("6/6", f"wrote {path}")

    print()
    print(ledger.summary())
    return 0


def cmd_views(args: argparse.Namespace) -> int:
    """Re-render views from a stored master. No model call, no cost."""
    session_dir = DATA_DIR / args.session_id
    master_file = session_dir / "master.latest.json"
    if not master_file.exists():
        print(f"error: no master.latest.json in {session_dir}", file=sys.stderr)
        return 2
    artifact = json.loads(master_file.read_text(encoding="utf-8"))
    for path in _render_views(artifact, session_dir, args.views.split(",")):
        _say("6/6", f"wrote {path}")
    print("\nNo model call — views are reformatting, not generation.")
    return 0


def cmd_site(args: argparse.Namespace) -> int:
    """Build a static site from generated sessions. No model call, no cost."""
    from classnotes import site as site_step

    out_dir = Path(args.out)
    written = site_step.build(DATA_DIR, out_dir, args.course)
    sessions = len(written) - 1

    _say("site", f"{sessions} session(s) -> {out_dir}/")
    if sessions:
        print()
        print(
            "  These are notes from a real class. Consent to make notes for the\n"
            "  section is not consent to publish them on the open internet — check\n"
            "  before you point a public domain at this."
        )
    print(f"\nPreview locally:  python -m http.server -d {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="classnotes",
        description="Turn one class recording into one set of notes for the whole class.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="full pipeline: audio + deck -> markdown")
    run.add_argument("--audio", help="lecture recording (any format ffmpeg reads)")
    run.add_argument("--deck", help="slide deck (.pdf or .pptx)")
    run.add_argument("--transcript", help="reuse a transcript.json instead of transcribing")
    run.add_argument("--session-id", help="defaults to <date>-<audio filename>")
    run.add_argument("--course", help='e.g. "Marketing Management, Sem 3"')
    run.add_argument("--topic", help='e.g. "Segmentation and targeting"')
    run.add_argument("--date", help="YYYY-MM-DD, defaults to today")
    run.add_argument("--instructor")
    run.add_argument("--views", default="skim,full", help="comma-separated (default: skim,full)")
    run.add_argument("--provider", help="override LLM_PROVIDER (anthropic/openai/gemini/fake)")
    run.add_argument("--model", help="override LLM_MODEL")
    run.add_argument("--force", action="store_true", help="redo cached transcript and alignment")
    run.add_argument(
        "--delete-audio",
        action="store_true",
        help="delete the source recording once transcribed (less liability, less storage)",
    )
    run.set_defaults(func=cmd_run)

    regen = sub.add_parser("regenerate", help="re-run generation from a stored alignment")
    regen.add_argument("session_id")
    regen.add_argument("--deck")
    regen.add_argument("--views", default="skim,full")
    regen.add_argument("--provider")
    regen.add_argument("--model")
    regen.set_defaults(func=cmd_regenerate)

    render = sub.add_parser("views", help="re-render views from a stored master (free)")
    render.add_argument("session_id")
    render.add_argument("--views", default="skim,full")
    render.set_defaults(func=cmd_views)

    web = sub.add_parser("site", help="build a static site from all sessions (free)")
    web.add_argument("--out", default="public", help="output directory (default: public)")
    web.add_argument("--course", help='heading for the index page, e.g. "Marketing, Sem 3"')
    web.set_defaults(func=cmd_site)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
