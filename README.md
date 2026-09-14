# Class notes tool — v0

One recording per class, turned into one set of notes for the whole class.

The differentiator is not transcription or summarisation. Those are commodity. The
differentiator is that the system knows the timetable, the syllabus, and who attended — so
it can prime you before a class, catch you up on a missed one, and resurface old topics
before exams.

**v0 is a pipeline, not an app.** A folder and a script. No login, no database, no UI. You
run it on a recording, you paste the markdown into the class WhatsApp group by hand. The
point is to find out whether people chase you for the next one. That is the only question
worth answering right now.

---

## Quickstart

```bash
# 1. System dependency
sudo apt install ffmpeg          # or: brew install ffmpeg

# 2. Python
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. Keys
cp .env.example .env             # fill in GROQ_API_KEY and one LLM key
```

Run it:

```bash
.venv/bin/python -m classnotes run \
    --audio lecture.m4a \
    --deck slides.pdf \
    --course "Marketing Management, Sem 3" \
    --topic "Segmentation and targeting" \
    --instructor "Prof. Kulkarni"
```

Output lands in `data/sessions/<session-id>/`:

```
transcript.json          raw ASR, kept so you never re-transcribe
aligned.md               transcript repaired against the deck  <- the valuable bit
master.v1.json           the single source of truth, versioned
master.latest.json
views/skim.md            paste this into WhatsApp
views/full.md
```

### Without any API keys

```bash
.venv/bin/python scripts/make_sample.py sample/
.venv/bin/python -m classnotes run --deck sample/deck.pptx \
    --transcript sample/transcript.json --provider fake --session-id sample
```

The `fake` provider runs the whole pipeline for free and produces a structurally valid
master artifact with placeholder content. It verifies the plumbing. It tells you nothing
about quality, and every file it writes is stamped so you cannot send it to a class by
accident.

---

## The pipeline

```
audio file + slide deck
        |
   [1] transcribe          Groq whisper-large-v3-turbo, ~$0.04/hr
        |
   [2] extract slide text  pypdf / python-pptx
        |
   [3] align to slides     <- this is where the quality comes from
        |
   [4] one master artifact  summary · Mermaid diagram · terms · videos
        |
   [5] render views        skim · full
        |
   [6] write markdown
```

**Step [2] runs before step [1].** The deck's vocabulary is fed into Whisper's decoder
prompt, so jargon is biased correctly *during* transcription rather than guessed at
afterwards. It is the cheapest accuracy win in the pipeline.

**Step [3] is the one that matters.** The deck gives you correct spelling, structure, and
the intended shape of the lecture. The audio gives you the explanation and what the
lecturer stressed. Feeding both to the model together, with instructions to correct the
transcript against the deck, is the difference between usable and garbage. If you improve
one thing in this repo, improve `prompts/align.md`.

### Hinglish

`LECTURE_LANGUAGE=en` is deliberate, not laziness. On auto-detect, Whisper will return
some passages in Devanagari and some in Latin script *within the same recording*, which is
unreadable and much harder to align against an English deck. Forcing `en` keeps everything
in Latin script; step [3] then normalises meaning into English while keeping Hindi phrasing
where the exact words carry something. Set `hi` only for a genuinely Hindi-medium class.

---

## Format views

The objection this answers: *"Everyone's notes are different. Archit writes differently
from Aditya. One set of notes can't work for both."*

Fair objection. The wrong fix is per-student generation — sixty personalised versions
destroys the one-recording-serves-sixty economics that makes this viable at all, and it
breaks corrections, because an error fixed in one person's version never reaches anyone
else.

The right fix: **one master artifact, five fixed views, user picks.**

| View | For | Status |
|---|---|---|
| Skim | Was there, mostly followed it | built |
| Full | Default | built |
| Catch-up | Missed the class | v1 — needs prior-session context |
| Diagram-first | Visual reference | v1 — reformatting only |
| Exam | Revision | v1 — reformatting only |

Four rules hold this together:

- **Formats, not personalities.** The variable is depth and shape, not prose voice. Nobody
  struggles with a summary because it doesn't sound like them.
- **User picks. No auto-detection.** The same student wants Full for the subject they're
  lost in and Skim for the one they're fine with. Detection needs behavioural data you
  don't have, to replace a dropdown.
- **Cost stays flat.** Skim, Diagram-first and Exam are reformatting — zero extra model
  calls. Only Catch-up needs a second pass, because it pulls context from previous sessions.
- **Corrections work.** Fix the master, every view regenerates. Views are never edited
  directly, and each rendered file says so.

Only two views are built on purpose. The build order says prove the master-to-view split
works before adding the rest — Skim exercises subtraction, Full exercises completeness, and
between them they establish the master carries enough for any view. The other three drop
into `classnotes/views/` as pure render functions.

Iterate on output quality without re-spending on ASR or alignment:

```bash
# edit prompts/master.md, then:
.venv/bin/python -m classnotes regenerate <session-id>   # one generation
.venv/bin/python -m classnotes views <session-id>        # free, no model call
```

Masters are versioned and never overwritten, so you can diff v1 against v2.

---

## Cost

Every run prints what it cost. You need this number before any pricing conversation.

```
Cost for this session
  ASR           90.0 min audio  (whisper-large-v3-turbo)       $0.0600
  Generation  48,000 in / 9,000 out tokens over 2 call(s)      $0.4650
  Total                                                        $0.5250  (~Rs 46.20)
  At 5 sessions/week, one section costs ~$10.50 (~Rs 924) a month.
```

Illustrative, not measured — **measure it on lecture one.** Rates in `classnotes/costs.py`
go stale; check them before quoting anyone. The number that matters is cost per *section*,
not per student: one recording serves sixty people, which is the entire economic argument.

Prompt caching is enabled on the Anthropic backend, so regenerating a master after a prompt
change re-reads the transcript at roughly a tenth of the input cost.

---

## Recording consent

**Get explicit permission from the lecturer before recording anything.** Not implied, not
assumed because a student already records. This is the fastest way to end the pilot, and it
will come up in ILS mentoring.

`schema.sql` carries a `consent_confirmed` flag on `recording` for when this stops being a
script. Until then it is a conversation you have before you press record.

`data/` is gitignored. Recordings of a real classroom do not belong in a repo — consent to
make notes for the class is not consent to publish the audio.

`DELETE_AUDIO_AFTER=true` (or `--delete-audio`) deletes the source recording once
transcribed. Less liability, less storage, and no loss: the transcript is always kept, so
regenerating notes never needs the audio again.

---

## Data model

`schema.sql` is written but **not wired up** — nothing reads it yet. It exists because
writing it down is what stops the project drifting into a generic note-taker. Every
differentiated feature traces to a table a transcription tool doesn't have:

| Table | Feature it powers |
|---|---|
| `section` | one recording serves sixty people |
| `timetable_slot` | pre-class recap |
| `attendance` | catch-up brief |
| `concept`, `concept_edge`, `student_concept_state` | exam resurfacing |
| `master_artifact` + `artifact_view` | five views at ~one generation's cost |
| `correction` | notes improve as more classmates use them |
| `annotation` | a personal layer that doesn't fragment the shared base |

Corrections are quietly the most important of these. It's what makes the notes get better
as the class uses them, and it's the thing a personal notebook structurally cannot do.

---

## Explicitly out of scope

Not oversights. Say so if asked:

- Online classes — Zoom and Meet already record and summarise. The gap is the offline room.
- Meetings, investor pitches, any non-classroom context.
- Mobile app.
- Live transcription — batch is fine and much cheaper.
- Multi-institution support.
- Per-student personalised generation. See Format Views: this is a trap, not a feature.

---

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

39 tests covering chunk stitching, vocabulary selection, Mermaid escaping, artifact
normalisation and view rendering — the logic that is easy to get quietly wrong.

**Step [2] has been tested against real files.** Deck parsing was run over 138 real-world
documents (70 PDFs and 68 PPTX files from the pypdf, pdfminer and python-pptx test
corpora — LaTeX output, OCR scans, multilingual documents, encrypted files, forms). That
found three bugs that a synthetic fixture never would:

- Encrypted PDFs crashed. Most "protected" lecture decks aren't password-locked at all —
  faculty export with copy/print restrictions, which encrypts the file with an *empty*
  password. 15 of 70 files crashed; now 0 do.
- Image-only decks parsed "successfully" with no text and degraded alignment silently.
  Now warned about loudly.
- ALL-CAPS slide titles — the norm in a lot of Indian university decks — flooded the ASR
  vocabulary budget with `THE`, `OF`, `AND` at the acronym weight bonus, crowding out the
  real jargon.

**Steps [1], [3] and [4] remain unverified.** No API keys existed in the build sandbox, so
transcription and generation have never run against anything. The tests cannot tell you
whether the notes are any *good* — only a real lecture does that. Run one real 90-minute
lecture end-to-end before trusting any of it.

### If a deck won't load

- *"is password-protected"* — genuinely locked. Ask for an unlocked copy.
- *"looks scanned or image-only"* — it's a picture of slides. Alignment will be weak;
  get a text PDF or the original `.pptx` if you can.
- *"Legacy .ppt is not supported"* — open and re-save as `.pptx`.

---

## Build order

Do not reverse this. Most student projects build the interface first and never reach step 2.

1. ~~Script: audio in → transcript out~~ ✅
2. ~~Deck parsing and alignment~~ ✅
3. ~~Master artifact generation~~ ✅
4. ~~YouTube lookup~~ ✅
5. ~~View rendering — Skim and Full only~~ ✅
6. Only now: schema and storage — *schema written, storage not built*
7. Only now: any interface — *not started*

v1 adds the differentiated layer, and only after v0 gets pulled out of your hands:
timetable-aware pre-class recap, catch-up brief, concept graph, spaced resurfacing.
