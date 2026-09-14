-- =============================================================================
-- Class notes tool — v1 data model
--
-- NOT WIRED UP. v0 is a script over a folder; nothing reads this file yet.
-- It exists because writing it down is what stops the project drifting into a
-- generic note-taker. Every differentiated feature traces to a table here that
-- a transcription tool does not have:
--
--   timetable_slot          -> pre-class recap
--   attendance              -> catch-up brief
--   concept + edges + state -> exam resurfacing across the semester
--   master_artifact + view  -> five formats at ~one generation's cost
--   correction              -> notes improve as more of the class uses them
--   annotation              -> a personal layer that doesn't fragment the base
--   section                 -> one recording serves sixty people
--
-- Postgres dialect.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Core: who, what, and when
-- -----------------------------------------------------------------------------

CREATE TABLE institution (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A subject. "Marketing Management, Sem 3."
CREATE TABLE course (
    id              BIGSERIAL PRIMARY KEY,
    institution_id  BIGINT NOT NULL REFERENCES institution(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    code            TEXT,
    term            TEXT,
    UNIQUE (institution_id, code, term)
);

-- The actual cohort of ~60 people. THIS is the unit the product is built
-- around: one recording, one generation, sixty readers. Per-student generation
-- would destroy that ratio, which is why it is explicitly out of scope.
CREATE TABLE section (
    id              BIGSERIAL PRIMARY KEY,
    course_id       BIGINT NOT NULL REFERENCES course(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    instructor_name TEXT
);

CREATE TABLE student (
    id              BIGSERIAL PRIMARY KEY,
    institution_id  BIGINT NOT NULL REFERENCES institution(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    phone           TEXT UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Many-to-many: a student sits in several sections.
CREATE TABLE enrollment (
    student_id  BIGINT NOT NULL REFERENCES student(id) ON DELETE CASCADE,
    section_id  BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, section_id)
);

-- Powers the pre-class recap. Without this table you cannot build the feature
-- that makes you different from a transcription tool.
CREATE TABLE timetable_slot (
    id          BIGSERIAL PRIMARY KEY,
    section_id  BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    weekday     SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    room        TEXT,
    CHECK (end_time > start_time)
);

-- One lecture instance. The hub of the model — everything hangs off it.
CREATE TABLE session (
    id                 BIGSERIAL PRIMARY KEY,
    section_id         BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    timetable_slot_id  BIGINT REFERENCES timetable_slot(id) ON DELETE SET NULL,
    date               DATE NOT NULL,
    topic              TEXT,
    status             TEXT NOT NULL DEFAULT 'scheduled'
                       CHECK (status IN ('scheduled','recorded','processing','published','cancelled')),
    UNIQUE (section_id, date, timetable_slot_id)
);
CREATE INDEX session_section_date_idx ON session (section_id, date DESC);

-- -----------------------------------------------------------------------------
-- Inputs
-- -----------------------------------------------------------------------------

CREATE TABLE recording (
    id                    BIGSERIAL PRIMARY KEY,
    session_id            BIGINT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    file_path             TEXT NOT NULL,
    duration_seconds      INTEGER,
    uploaded_by_student_id BIGINT REFERENCES student(id) ON DELETE SET NULL,
    uploaded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Recording consent is taken from the lecturer, per session, before the fact.
    -- Keep the record. This is the fastest way to end a pilot if you get it wrong.
    consent_confirmed     BOOLEAN NOT NULL DEFAULT FALSE,
    -- Raw audio is deleted after processing unless there is a reason to keep it.
    deleted_at            TIMESTAMPTZ
);

CREATE TABLE source_material (
    id                     BIGSERIAL PRIMARY KEY,
    session_id             BIGINT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    type                   TEXT NOT NULL CHECK (type IN ('slides','pdf','handout')),
    file_path              TEXT NOT NULL,
    uploaded_by_student_id BIGINT REFERENCES student(id) ON DELETE SET NULL,
    uploaded_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Keep both texts. You will want to compare quality as alignment improves,
-- and raw_text is what you re-align against after a prompt change — it means
-- you never have to re-run ASR, and never have to keep the audio.
CREATE TABLE transcript (
    id            BIGSERIAL PRIMARY KEY,
    recording_id  BIGINT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    raw_text      TEXT NOT NULL,
    aligned_text  TEXT,
    asr_model     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- The artifact and its views
-- -----------------------------------------------------------------------------

-- The single source of truth for a session. Versioned, never overwritten:
-- you will regenerate as prompts improve and you want to compare.
CREATE TABLE master_artifact (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    content     JSONB NOT NULL,   -- summary, diagram, terms, videos, concepts
    version     INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, version)
);

-- Rendered from the master. NEVER edited directly — regenerate instead.
-- Cached so a read doesn't re-render; a master version bump invalidates these.
CREATE TABLE artifact_view (
    id                  BIGSERIAL PRIMARY KEY,
    master_artifact_id  BIGINT NOT NULL REFERENCES master_artifact(id) ON DELETE CASCADE,
    format              TEXT NOT NULL
                        CHECK (format IN ('skim','full','catch_up','diagram_first','exam')),
    content             TEXT NOT NULL,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (master_artifact_id, format)
);

-- Which view a student sees by default. Overridable per session — the same
-- student wants Full for the subject they're lost in and Skim for the one
-- they're fine with. A dropdown, not auto-detection.
CREATE TABLE student_preference (
    student_id     BIGINT NOT NULL REFERENCES student(id) ON DELETE CASCADE,
    section_id     BIGINT NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    default_format TEXT NOT NULL DEFAULT 'full'
                   CHECK (default_format IN ('skim','full','catch_up','diagram_first','exam')),
    PRIMARY KEY (student_id, section_id)
);

-- -----------------------------------------------------------------------------
-- The personal and collective layers
-- -----------------------------------------------------------------------------

-- Private to the student. Attaches to the MASTER, not to a view, so it
-- survives a format switch. This is the real answer to "everyone's notes are
-- different": nobody's personal notes get replaced, they get something to
-- attach to instead of a blank page.
CREATE TABLE annotation (
    id                  BIGSERIAL PRIMARY KEY,
    student_id          BIGINT NOT NULL REFERENCES student(id) ON DELETE CASCADE,
    master_artifact_id  BIGINT NOT NULL REFERENCES master_artifact(id) ON DELETE CASCADE,
    anchor              TEXT NOT NULL,   -- section / paragraph reference
    body                TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX annotation_student_artifact_idx ON annotation (student_id, master_artifact_id);

-- Anyone in the section can flag an error. An applied correction bumps the
-- master version, which regenerates every view. This is the feature a personal
-- notebook structurally cannot have, and the reason the notes get better as
-- more of the class uses them.
CREATE TABLE correction (
    id                  BIGSERIAL PRIMARY KEY,
    master_artifact_id  BIGINT NOT NULL REFERENCES master_artifact(id) ON DELETE CASCADE,
    student_id          BIGINT REFERENCES student(id) ON DELETE SET NULL,
    anchor              TEXT NOT NULL,
    suggested_text      TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','applied','rejected')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);
CREATE INDEX correction_pending_idx ON correction (master_artifact_id)
    WHERE status = 'pending';

-- Powers catch-up mode. Self-reported is fine to start — a student marks
-- "I missed this" and gets the catch-up view instead of the full one.
CREATE TABLE attendance (
    session_id  BIGINT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    student_id  BIGINT NOT NULL REFERENCES student(id) ON DELETE CASCADE,
    attended    BOOLEAN NOT NULL,
    source      TEXT NOT NULL DEFAULT 'self_reported'
                CHECK (source IN ('self_reported','official')),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, student_id)
);

-- -----------------------------------------------------------------------------
-- The concept layer — what generic tools don't have and can't easily add
-- -----------------------------------------------------------------------------

-- A topic that appears across the course. Deduplicated within a course, not
-- globally: "segmentation" in Marketing is not "segmentation" in Networks.
CREATE TABLE concept (
    id                   BIGSERIAL PRIMARY KEY,
    course_id            BIGINT NOT NULL REFERENCES course(id) ON DELETE CASCADE,
    name                 TEXT NOT NULL,
    aliases              TEXT[] NOT NULL DEFAULT '{}',
    first_seen_session_id BIGINT REFERENCES session(id) ON DELETE SET NULL,
    UNIQUE (course_id, name)
);

-- Which concepts appeared in which lecture, and how central they were.
CREATE TABLE session_concept (
    session_id  BIGINT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    concept_id  BIGINT NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
    weight      REAL NOT NULL DEFAULT 0.5 CHECK (weight BETWEEN 0 AND 1),
    time_range  TEXT,
    -- 'rushed' is what drives video recommendations. See classnotes/videos.py.
    coverage    TEXT NOT NULL DEFAULT 'normal'
                CHECK (coverage IN ('rushed','normal','deep')),
    PRIMARY KEY (session_id, concept_id)
);

-- The graph. Powers "you need to understand X before Thursday."
CREATE TABLE concept_edge (
    from_concept_id BIGINT NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
    to_concept_id   BIGINT NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
    relation        TEXT NOT NULL
                    CHECK (relation IN ('prerequisite','example_of','contrasts_with')),
    PRIMARY KEY (from_concept_id, to_concept_id, relation),
    CHECK (from_concept_id <> to_concept_id)
);

-- Spaced repetition state. Standard SM-2-ish interval logic is fine here.
-- Do not invent an algorithm.
CREATE TABLE student_concept_state (
    student_id      BIGINT NOT NULL REFERENCES student(id) ON DELETE CASCADE,
    concept_id      BIGINT NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
    last_surfaced_at TIMESTAMPTZ,
    strength        REAL NOT NULL DEFAULT 0.0 CHECK (strength BETWEEN 0 AND 1),
    next_due_at     TIMESTAMPTZ,
    PRIMARY KEY (student_id, concept_id)
);
-- The query behind exam resurfacing: what is due, for whom, soonest.
CREATE INDEX student_concept_due_idx ON student_concept_state (student_id, next_due_at)
    WHERE next_due_at IS NOT NULL;
