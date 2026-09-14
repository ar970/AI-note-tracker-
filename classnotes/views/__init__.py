"""View registry.

Five views are specified. Two are built.

The build order is deliberate: prove the master-to-view split works with Skim
and Full before adding the rest. Skim exercises subtraction, Full exercises
completeness — between them they establish that the master carries enough for
any view. The remaining three then drop in here as pure render functions:

  diagram_first — reformatting only, no model call
  exam          — reformatting only, no model call
  catch_up      — the one exception; needs a second pass because it pulls
                  context from previous sessions, which requires the session
                  history that v0 does not have yet

Views are never edited directly. A correction goes into the master and every
view regenerates from it — that is the whole point of the split.
"""

from __future__ import annotations

from typing import Callable

from classnotes.views import full, skim

RENDERERS: dict[str, Callable[[dict], str]] = {
    "full": full.render,
    "skim": skim.render,
}

PLANNED = {
    "diagram_first": "reformatting only — not built yet (v0 ships skim + full)",
    "exam": "reformatting only — not built yet (v0 ships skim + full)",
    "catch_up": "needs prior-session context — arrives with the session history in v1",
}

ALL_VIEWS = list(RENDERERS) + list(PLANNED)


def render(name: str, artifact: dict) -> str:
    if name in RENDERERS:
        return RENDERERS[name](artifact)
    if name in PLANNED:
        raise NotImplementedError(f"View '{name}': {PLANNED[name]}")
    raise ValueError(f"Unknown view '{name}'. Available now: {', '.join(RENDERERS)}")
