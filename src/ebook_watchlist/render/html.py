"""HTML Digest — written to ``data/digests/``.

Kept to a single self-contained document with inline styles so it also survives
being pasted into an HTML mail later. Phase 2's Dashboard will reuse the same
Digest model through shared partials (ADR 15).
"""

from __future__ import annotations

from html import escape

from ..digest import Digest, DigestEntry

_STYLE = """
body { font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 46rem;
       color: #1a1a1a; background: #fdfdfc; }
h1 { font-size: 1.35rem; margin-bottom: 0.2rem; }
p.since { color: #666; margin-top: 0; }
h2 { font-size: 1.05rem; margin: 2rem 0 0.5rem; border-bottom: 1px solid #ddd;
     padding-bottom: 0.3rem; }
ul { list-style: none; padding: 0; }
li { padding: 0.5rem 0; border-bottom: 1px solid #f0f0ee; }
.author { color: #555; }
.detail { color: #444; }
.gate { color: #555; background: #f4f4f1; border-left: 3px solid #ccc;
        padding: 0.4rem 0.7rem; font-size: 0.9rem; }
.judgement { color: #555; font-size: 0.9rem; margin-top: 0.2rem; }
.flag { display: inline-block; background: #1a6b3c; color: #fff; border-radius: 3px;
        padding: 0 0.4rem; font-size: 0.8rem; margin-left: 0.4rem; }
a { color: #1a4d8f; }
"""


def _entry_html(entry: DigestEntry) -> str:
    title = escape(entry.title)
    if entry.url:
        title = f'<a href="{escape(entry.url, quote=True)}">{title}</a>'
    bits = [f"<strong>{title}</strong>"]
    if entry.author:
        bits.append(f'<span class="author">{escape(entry.author)}</span>')
    if entry.detail:
        bits.append(f'<span class="detail">{escape(entry.detail)}</span>')
    bits.extend(f'<span class="flag">{escape(flag)}</span>' for flag in entry.flags)
    line = " · ".join(bits)
    if entry.judgement:
        line += f'<div class="judgement">{escape(entry.judgement)}</div>'
    if entry.pitch:
        line += f'<div class="judgement">{escape(entry.pitch)}</div>'
    return "<li>" + line + "</li>"


def render_html(digest: Digest) -> str:
    body = [
        f"<h1>{escape(digest.profile_name)}</h1>",
        f'<p class="since">{escape(digest.headline)}</p>',
    ]
    if digest.gate is not None and digest.gate.is_worth_saying:
        body.append(f'<p class="gate">{escape(digest.gate.text)}</p>')
    for section in digest.sections:
        body.append(f"<h2>{escape(section.title)}</h2>")
        body.append("<ul>")
        body.extend(_entry_html(entry) for entry in section.entries)
        body.append("</ul>")

    return (
        "<!doctype html>\n"
        '<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(digest.profile_name)} — Digest</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )
