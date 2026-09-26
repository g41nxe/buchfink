"""Was die Seite ausliefert, muss ein Browser auch zeichnen koennen.

Anlass: im Favicon stand ein XML-Kommentar mit ``--color-accent`` darin. Zwei
Bindestriche hintereinander sind in einem XML-Kommentar verboten, also war die
Datei nicht mehr wohlgeformt — und das Zeichen der Anwendung war in der
Kopfzeile ein leeres Kaestchen. Kein Test schlug an, kein Bau meckerte: SVG
faellt still aus.
"""

from __future__ import annotations

import re
import xml.dom.minidom
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "ebook_watchlist" / "web" / "assets"


@pytest.mark.parametrize("svg", sorted(ASSETS.glob("*.svg")), ids=lambda p: p.name)
def test_every_delivered_svg_is_well_formed(svg: Path) -> None:
    xml.dom.minidom.parseString(svg.read_bytes().decode("utf-8"))


# --- Hell und Dunkel (#19) ---------------------------------------------------

APP_CSS = ASSETS / "app.css"


def test_the_palette_is_not_behind_a_media_query() -> None:
    """Der Wachhund dieses Tickets.

    Eine Regel unter ``@media (prefers-color-scheme: dark)`` laesst sich von
    keinem Knopf uebersteuern — sie ist genau der Grund, warum es vor #19
    keinen Umschalter gab. Wer die Palette dorthin zuruecklegt, nimmt dem
    Schalter still die Wirkung, und die Seite sieht dabei richtig aus, solange
    man nicht klickt.
    """
    without_comments = re.sub(r"/\*.*?\*/", "", APP_CSS.read_text(encoding="utf-8"), flags=re.S)

    assert "prefers-color-scheme" not in without_comments


def test_every_colour_carries_both_values() -> None:
    """Eine Farbe, die nur hell definiert ist, bleibt im Dunkeln stehen.

    Frueher standen die dunklen Werte in einem zweiten Block, und eine neue
    Farbe dort zu vergessen war ein stiller Fehler. Jetzt traegt jede Zeile
    beide Werte, und diese Probe sagt es, wenn eine es nicht tut.
    """
    text = APP_CSS.read_text(encoding="utf-8")
    theme = text[text.index("@theme {") : text.index("/* Hell und Dunkel")]
    without_dark = [
        row.strip()
        for row in theme.splitlines()
        if row.strip().startswith("--color-") and "light-dark(" not in row
    ]
    assert without_dark == []
