"""Build a static site from generated sessions.

v0's delivery step is "paste it into the class WhatsApp group by hand".
Pasting eight thousand characters of markdown into WhatsApp is worse than
sending one link, so this turns `data/sessions/` into a folder of static HTML
you can host anywhere. That is the whole scope: no upload form, no accounts,
no database. Those are step [7], and they are still step [7].

The pages are built by converting the markdown the views already emit, rather
than by rendering the master artifact a second time. It means the web page and
the file you paste can never drift apart, and a change to `views/skim.py`
shows up here automatically.

PRIVACY: this writes notes from a real class to a folder you will probably
put on the public internet. Consent to make notes for the class is not consent
to publish them. Publish deliberately.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from classnotes.views import full, skim

INLINE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])_([^_]+)_(?![\w*])")
TABLE_DIVIDER = re.compile(r"^\|[\s:|-]+\|$")


SAFE_SCHEMES = ("http://", "https://", "mailto:")


def _safe_href(url: str) -> str | None:
    """Allow only schemes a notes page has any business linking to.

    Link targets reach this from model output. A `javascript:` or `data:` URL
    in a generated term would otherwise become a live script on a page the
    whole section opens.
    """
    cleaned = url.strip()
    if cleaned.lower().startswith(SAFE_SCHEMES):
        return html.escape(cleaned, quote=True)
    return None


def _link(match: re.Match) -> str:
    label, href = match.group(1), _safe_href(match.group(2))
    if href is None:
        return label
    return f'<a href="{href}" target="_blank" rel="noopener">{label}</a>'


def _inline(text: str) -> str:
    """Escape, then re-enable the small set of markup the views emit."""
    out = html.escape(text, quote=False)
    out = out.replace("&lt;br&gt;", "<br>")
    out = INLINE_LINK.sub(_link, out)
    out = BOLD.sub(r"<strong>\1</strong>", out)
    out = ITALIC.sub(r"<em>\1</em>", out)
    return out


def markdown_to_html(source: str, *, skip_h1: bool = True, strip_header: bool = True) -> str:
    """Convert the narrow markdown subset the views produce.

    Deliberately not a general markdown parser. The input is machine-generated
    from renderers in this repo, so the set of constructs is known and closed:
    headings, bullets, blockquotes, one table shape, mermaid fences, links,
    bold and italic. A general parser would be a dependency and a bigger
    surface for no benefit.
    """
    lines = source.splitlines()
    out: list[str] = []
    index = 0

    def close(tag: str, buffer: list[str]) -> None:
        if buffer:
            out.append(f"<{tag}>" + "".join(buffer) + f"</{tag}>")
            buffer.clear()

    bullets: list[str] = []

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            close("ul", bullets)
            language = stripped[3:].strip()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            body = html.escape("\n".join(block), quote=False)
            css = "mermaid" if language == "mermaid" else "code"
            out.append(f'<pre class="{css}">{body}</pre>')
            continue

        if not stripped:
            close("ul", bullets)
            index += 1
            continue

        if stripped.startswith("|"):
            close("ul", bullets)
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = lines[index].strip()
                if not TABLE_DIVIDER.match(row):
                    rows.append([c.strip() for c in row.strip("|").split("|")])
                index += 1
            if rows:
                head = "".join(f"<th>{_inline(c)}</th>" for c in rows[0])
                body = "".join(
                    "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                    for r in rows[1:]
                )
                out.append(
                    f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                    f"<tbody>{body}</tbody></table></div>"
                )
            continue

        if stripped.startswith("- "):
            bullets.append(f"<li>{_inline(stripped[2:])}</li>")
            index += 1
            continue

        close("ul", bullets)

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if not (level == 1 and skip_h1):
                out.append(f"<h{level}>{_inline(text)}</h{level}>")
        elif stripped.startswith("> "):
            out.append(f'<blockquote>{_inline(stripped[2:])}</blockquote>')
        elif stripped == "---":
            out.append("<hr>")
        elif strip_header and not out:
            # The views open with "date · instructor · duration · view name".
            # The surrounding page already shows all of that in its own header
            # and on the tab, so rendering it again just prints it twice.
            pass
        else:
            out.append(f"<p>{_inline(stripped)}</p>")
        index += 1

    close("ul", bullets)
    return "\n".join(out)


STYLE = """
:root{--ground:#F6F7F9;--surface:#FFF;--sunk:#EFF2F5;--ink:#16202B;--muted:#5C6B7A;
--faint:#8695A4;--rule:#DCE2E9;--accent:#A8600C;--accent-soft:#F6EBDA;--flag:#0F6E6E;
--serif:"Newsreader",Georgia,serif;--sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#10151B;--surface:#19202A;
--sunk:#141A22;--ink:#E4EBF2;--muted:#98A6B4;--faint:#71808F;--rule:#29323D;--accent:#E5A244;
--accent-soft:#2E2417;--flag:#5FBEBE}}
:root[data-theme="dark"]{--ground:#10151B;--surface:#19202A;--sunk:#141A22;--ink:#E4EBF2;
--muted:#98A6B4;--faint:#71808F;--rule:#29323D;--accent:#E5A244;--accent-soft:#2E2417;--flag:#5FBEBE}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:720px;margin:0 auto;padding-inline:20px;padding-block:32px 64px}
a{color:var(--accent);text-underline-offset:2px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.11em;text-transform:uppercase;color:var(--faint)}
h1{font-family:var(--serif);font-weight:500;font-size:clamp(25px,5vw,33px);line-height:1.2;
margin:10px 0 6px;text-wrap:balance}
.meta{font-family:var(--mono);font-size:12px;color:var(--faint);margin-bottom:26px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:4px;overflow:hidden;
box-shadow:0 1px 2px rgba(22,32,43,.05),0 8px 24px -12px rgba(22,32,43,.16)}
.tabs{display:flex;flex-wrap:wrap;gap:7px;padding:18px 24px;border-bottom:1px solid var(--rule)}
.tab{font:500 13.5px var(--sans);padding:7px 14px;border-radius:3px;border:1px solid var(--rule);
background:var(--surface);color:var(--muted);cursor:pointer}
.tab[aria-selected="true"]{background:var(--ink);border-color:var(--ink);color:var(--surface)}
.tab:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.view{padding:24px 26px 28px}
.view h2{font-family:var(--mono);font-size:11px;letter-spacing:.11em;text-transform:uppercase;
color:var(--faint);font-weight:500;margin:30px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--rule)}
.view h2:first-child{margin-top:0}
.view h3{font-family:var(--serif);font-size:19px;font-weight:600;margin:22px 0 8px;line-height:1.3}
.view p{margin:0 0 11px;text-wrap:pretty}
.view ul{margin:0 0 14px;padding-left:20px}
.view li{margin-bottom:6px;text-wrap:pretty}
blockquote{margin:0 0 16px;padding-left:14px;border-left:2px solid var(--accent);
font-family:var(--serif);font-style:italic;font-size:17px}
/* Left-aligned so that if the mermaid script is blocked or fails, the raw
   source degrades to a readable code block instead of centred gibberish.
   The rendered SVG is centred on its own. */
pre.mermaid{margin:0 0 18px;padding:18px;background:var(--sunk);border-radius:3px;
overflow-x:auto;text-align:left;font-family:var(--mono);font-size:12.5px;
line-height:1.5;color:var(--muted)}
pre.mermaid svg{display:block;margin:0 auto;max-width:100%;height:auto}
.scroll{overflow-x:auto;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:14.5px}
th{text-align:left;font-family:var(--mono);font-size:10.5px;letter-spacing:.07em;
text-transform:uppercase;color:var(--faint);font-weight:500;padding:8px 10px 8px 0;
border-bottom:1px solid var(--rule)}
td{padding:10px 10px 10px 0;border-bottom:1px solid var(--rule);vertical-align:top;color:var(--muted)}
td:first-child{color:var(--ink)}
td em{font-family:var(--mono);font-style:normal;font-size:11px;color:var(--flag)}
hr{border:none;border-top:1px solid var(--rule);margin:24px 0 14px}
.view hr ~ p{font-size:12.5px;color:var(--faint)}
.index-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.index-list a{display:block;padding:16px 0;border-bottom:1px solid var(--rule);
text-decoration:none;color:inherit}
.index-list a:hover .t{color:var(--accent)}
.index-list .t{font-family:var(--serif);font-size:19px;font-weight:600}
.index-list .s{font-family:var(--mono);font-size:11.5px;color:var(--faint);margin-top:3px}
.warn{background:var(--accent-soft);border-left:3px solid var(--accent);border-radius:3px;
padding:13px 15px;font-size:13.5px;color:var(--muted);margin-bottom:26px}
@media (max-width:480px){.view,.tabs{padding-inline:18px}}
"""

HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{style}</style></head><body><div class="wrap">
"""

TAIL = """</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<script>
(function(){
  var dark = matchMedia('(prefers-color-scheme: dark)').matches;
  if (window.mermaid) mermaid.initialize({startOnLoad:true, theme: dark ? 'dark' : 'neutral'});
  var tabs = [].slice.call(document.querySelectorAll('.tab'));
  var views = [].slice.call(document.querySelectorAll('.view'));
  tabs.forEach(function(tab, i){
    tab.addEventListener('click', function(){
      tabs.forEach(function(t, j){ t.setAttribute('aria-selected', i===j ? 'true':'false'); });
      views.forEach(function(v, j){ v.hidden = i!==j; });
    });
  });
})();
</script>
</body></html>
"""


@dataclass
class Session:
    session_id: str
    artifact: dict

    @property
    def meta(self) -> dict:
        return self.artifact.get("session") or {}

    @property
    def title(self) -> str:
        parts = [self.meta.get("course"), self.meta.get("topic")]
        return " — ".join(p for p in parts if p) or self.session_id

    @property
    def date(self) -> str:
        return self.meta.get("date") or ""


def _page(title: str, body: str) -> str:
    return HEAD.format(title=html.escape(title, quote=True), style=STYLE) + body + TAIL


def render_session(session: Session) -> str:
    meta = session.meta
    bits = [
        session.date,
        meta.get("instructor"),
        f"{meta.get('duration_seconds', 0) / 60:.0f} min" if meta.get("duration_seconds") else None,
        f"v{session.artifact.get('version', '?')}",
    ]
    body = [
        '<p class="eyebrow"><a href="../index.html">← All sessions</a></p>',
        f"<h1>{html.escape(session.title)}</h1>",
        f'<p class="meta">{html.escape(" · ".join(b for b in bits if b))}</p>',
    ]
    # A demo page on a public URL reads as a real record of a real class unless
    # it says otherwise. Set "sample": true on the session to mark it.
    if meta.get("sample"):
        body.append(
            '<div class="warn"><strong>Sample content.</strong> This is not a real '
            "lecture. The layout and both views come from the actual renderers; the "
            "course, the instructor and everything said in class are invented to show "
            "the format.</div>"
        )
    body += [
        '<div class="card"><div class="tabs" role="tablist">',
        '<button class="tab" role="tab" aria-selected="true">Skim · ~5 min</button>',
        '<button class="tab" role="tab" aria-selected="false">Full notes</button>',
        "</div>",
        f'<div class="view" role="tabpanel">{markdown_to_html(skim.render(session.artifact))}</div>',
        f'<div class="view" role="tabpanel" hidden>{markdown_to_html(full.render(session.artifact))}</div>',
        "</div>",
    ]
    return _page(session.title, "\n".join(body))


def render_index(sessions: list[Session], course: str | None = None) -> str:
    if sessions:
        items = "".join(
            f'<li><a href="{html.escape(s.session_id, quote=True)}/index.html">'
            f'<div class="t">{html.escape(s.meta.get("topic") or s.title)}</div>'
            f'<div class="s">{html.escape(" · ".join(x for x in [s.date, s.meta.get("course") or ""] if x))}'
            f"</div></a></li>"
            for s in sessions
        )
        listing = f'<ul class="index-list">{items}</ul>'
    else:
        listing = (
            '<div class="warn">No sessions built yet. Run the pipeline on a lecture, '
            "then <code>python -m classnotes site</code>.</div>"
        )
    body = [
        '<p class="eyebrow">Class notes</p>',
        f"<h1>{html.escape(course or 'Lecture notes')}</h1>",
        f'<p class="meta">{len(sessions)} session{"" if len(sessions) == 1 else "s"}</p>',
        listing,
    ]
    return _page(course or "Lecture notes", "\n".join(body))


def load_sessions(data_dir: Path) -> list[Session]:
    sessions: list[Session] = []
    for master in sorted(data_dir.glob("*/master.latest.json")):
        artifact = json.loads(master.read_text(encoding="utf-8"))
        sessions.append(Session(session_id=master.parent.name, artifact=artifact))
    sessions.sort(key=lambda s: s.date, reverse=True)
    return sessions


def build(data_dir: Path, out_dir: Path, course: str | None = None) -> list[Path]:
    sessions = load_sessions(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = [out_dir / "index.html"]
    (out_dir / "index.html").write_text(render_index(sessions, course), encoding="utf-8")

    for session in sessions:
        folder = out_dir / session.session_id
        folder.mkdir(parents=True, exist_ok=True)
        page = folder / "index.html"
        page.write_text(render_session(session), encoding="utf-8")
        written.append(page)
    return written
