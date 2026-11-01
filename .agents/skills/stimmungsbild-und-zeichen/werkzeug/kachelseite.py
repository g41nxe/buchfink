"""Übersichtsseite aller Erstaufnahme-Kacheln zum Bewerten (#55).

Rendert die echte Karte (`family_card` aus `_family_pill.html`) für alle 38
Familien, gewählt und nicht gewählt, mit dem gebauten app.css. Schalter oben:
hell/dunkel und Papier-Kärtchen gegen durchsichtigen Grund. Durchsichtig wird
nur das Papier, das vom Bildrand her zusammenhängt; dunkel liegt Papier dahinter.

Aufruf (aus dem Repo):
    uv run --with numpy --with scipy --with pillow python \
        .agents/skills/stimmungsbild-und-zeichen/werkzeug/kachelseite.py
Ergebnis: .scratch/frontend/kacheln/index.html (Server „prototyp“, Port 8438)
"""
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
from scipy import ndimage

from ebook_watchlist.judging.portrait import load_vocabulary
from ebook_watchlist.web import family_art
from ebook_watchlist.web.app import TEMPLATES

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / ".scratch" / "frontend" / "kacheln"
WEB = ROOT / "src" / "ebook_watchlist" / "web"
CREAM = np.array((244, 236, 221), dtype=float)

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "img").mkdir(exist_ok=True)
for name in ("app.css", "fraunces.woff2"):
    shutil.copy(WEB / "static" / name, OUT / name)


def transparent(src: Path, dst: Path) -> None:
    """Papier vom Rand her durchsichtig, weiche Kante zwischen 16 und 30."""
    a = np.array(Image.open(src).convert("RGB")).astype(float)
    dist = np.linalg.norm(a - CREAM, axis=2)
    labels, _ = ndimage.label(dist <= 30)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
    edge.discard(0)
    outer = np.isin(labels, list(edge))
    alpha = np.full(dist.shape, 255.0)
    alpha[outer] = np.clip((dist[outer] - 16) / 14 * 255, 0, 255)
    rgba = np.dstack([a, alpha]).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(dst)


# Alle Karten: Familien, Merkmale ohne Familie (ihre eigene) und Erzählmuster.
vocab = load_vocabulary()
families = []
for fid in sorted({vocab.family_of(t).id for t in vocab.terms}):
    fam = vocab.family(fid)
    families.append((fid, fam.name, fam.description, vocab.is_pattern(fid)))

# Die Bilder der geltenden Fassung des Vokabulars (``family_art`` kennt den Ordner).
for fid, *_ in families:
    shutil.copy(family_art.PICTURES_DIR / f"{fid}.jpg", OUT / "img" / f"{fid}.jpg")
    transparent(family_art.PICTURES_DIR / f"{fid}.jpg", OUT / "img" / f"{fid}.png")

art = family_art.load()
TEMPLATES.env.globals["family_art"] = art
macro = TEMPLATES.env.from_string(
    '{% from "_family_pill.html" import family_card %}{{ family_card(k, 3, True) }}')


def card(fid, name, text, pattern, on):
    pill = SimpleNamespace(family_id=fid, name=name, on=on, boosted=False,
                           frequent=False, pattern=pattern)
    k = SimpleNamespace(pill=pill, description=text, strength="stark", level=3, evidence=[])
    html = macro.render(k=k).replace(f'src="/familien/{fid}.jpg"',
                                     f'src="img/{fid}.jpg" data-png="img/{fid}.png"')
    return html


base = (WEB / "templates" / "base.html").read_text(encoding="utf-8")
icons = "\n".join(re.findall(r'<symbol id="ic-(?:heart|ban|star)".*?</symbol>', base))
cards = {on: "\n".join(card(*f, on) for f in families) for on in (True, False)}

page = f"""<!doctype html>
<html lang="de" data-look="a2" data-theme="light">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kacheln der Erstaufnahme</title>
<link rel="stylesheet" href="app.css">
<style>
  .bar {{ position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap; gap: .5rem 1rem;
          align-items: center; padding: .75rem 1rem; background: var(--color-paper, Canvas);
          border-bottom: 1px solid oklch(0.5 0 0 / .2); font-size: .875rem; }}
  .bar button {{ padding: .25rem .75rem; border: 1px solid oklch(0.5 0 0 / .4);
                 border-radius: 999px; }}
  .bar button[aria-pressed="true"] {{ background: oklch(0.5 0.08 200 / .2); font-weight: 600; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
           gap: .75rem; list-style: none; padding: 1rem; margin: 0; }}
  [data-state="on"] .off, [data-state="off"] .on {{ display: none; }}
  /* Durchsichtig: kein Kärtchen hell; dunkel liegt das Papier dahinter. */
  [data-bg="clear"] .family-pic {{ outline: none; box-shadow: none; filter: none; }}
  /* Gewählt-Grund: bg-accent/10 (heute) gegen das Token accent-bg der Knöpfe. */
  [data-sel="token"] .bg-accent\\/10 {{ background-color: var(--color-accent-bg); }}
  [data-bg="clear"][data-theme="dark"] .family-pic {{ background: #F4ECDD;
          filter: brightness(0.72) saturate(0.9); outline: 1px solid oklch(1 0 0 / .1); }}
</style>
</head>
<body class="m-0 font-sans text-base antialiased" data-state="on" data-bg="paper" data-sel="tint">
<svg class="hidden" aria-hidden="true">{icons}{art.sprite}</svg>
<div class="bar">
  <strong>{len(families)} Kacheln</strong>
  <span>Farbe: <button data-set="theme" data-val="light">hell</button>
               <button data-set="theme" data-val="dark">dunkel</button></span>
  <span>Grund: <button data-set="bg" data-val="paper">Papier</button>
               <button data-set="bg" data-val="clear">durchsichtig</button></span>
  <span>Zustand: <button data-set="state" data-val="on">gewählt</button>
                 <button data-set="state" data-val="off">nicht gewählt</button></span>
  <span>Kartengrund gewählt: <button data-set="sel" data-val="tint">heute (accent/10)</button>
                 <button data-set="sel" data-val="token">wie „Jetzt prüfen“</button></span>
</div>
<ul class="grid on">{cards[True]}</ul>
<ul class="grid off">{cards[False]}</ul>
<script>
  const root = document.documentElement, body = document.body;
  const target = {{ theme: root, bg: body, state: body, sel: body }};
  function sync() {{
    document.querySelectorAll(".bar button").forEach(b =>
      b.setAttribute("aria-pressed",
                     target[b.dataset.set].dataset[b.dataset.set] === b.dataset.val));
    const clear = body.dataset.bg === "clear";
    document.querySelectorAll("img[data-png]").forEach(i => {{
      i.src = clear ? i.dataset.png : i.dataset.png.replace(".png", ".jpg"); }});
  }}
  document.querySelector(".bar").addEventListener("click", e => {{
    const b = e.target.closest("button"); if (!b) return;
    target[b.dataset.set].dataset[b.dataset.set] = b.dataset.val; sync(); }});
  document.querySelectorAll("form").forEach(f =>
    f.addEventListener("submit", e => e.preventDefault()));
  sync();
</script>
</body></html>
"""
(OUT / "index.html").write_text(page, encoding="utf-8")
print(OUT / "index.html", len(families), "Familien")
