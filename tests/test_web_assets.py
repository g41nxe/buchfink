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

    Eine Rolle, die nur auf andere Farben zeigt (`--color-price:
    var(--color-amber)`, ADR 39), erbt beide Werte von dort.
    """
    text = APP_CSS.read_text(encoding="utf-8")
    theme = text[text.index("@theme {") : text.index("/* Hell und Dunkel")]

    def inherits(row: str) -> bool:
        return "var(--color-" in row and "oklch(" not in row

    without_dark = [
        row.strip()
        for row in theme.splitlines()
        if row.strip().startswith("--color-") and "light-dark(" not in row and not inherits(row)
    ]
    assert without_dark == []


# --- Knöpfe und Felder auf dem Papier -----------------------------------------

TEMPLATES = ASSETS.parent / "templates"


def _template_text() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(TEMPLATES.glob("*.html"))}


def test_no_template_tints_the_accent_over_the_paper() -> None:
    """Petrol mit 10 % Deckkraft über Creme ergibt Mint, und das biss sich mit
    dem warmen Papier. Ein Hauptknopf trägt die volle Fläche (`bg-action`), eine
    gewählte Pille nur Rand und Schrift, ein Chip `bg-accent-bg`."""
    tinted = {name: re.findall(r"bg-accent/\d+", text) for name, text in _template_text().items()}

    assert {name: hits for name, hits in tinted.items() if hits} == {}


def test_fields_do_not_wear_the_paper() -> None:
    """Ein Eingabefeld auf Papierton sah aus wie aufs Papier gemalt; es liegt
    auf eigener Fläche mit einem Rand, der 3:1 erreicht."""
    fields = [
        (name, tag)
        for name, text in _template_text().items()
        for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", text, flags=re.S)
        if 'type="hidden"' not in tag and "sr-only" not in tag and "class=" in tag
    ]
    on_paper = [(name, tag) for name, tag in fields if "bg-paper" in tag]

    assert fields
    assert on_paper == []


def test_bordered_buttons_carry_their_own_surface() -> None:
    """Ein Knopf mit Rand und ohne Fläche zeigt das Papier durch und sieht
    aus wie aufs Papier gezeichnet; ruhige Knöpfe liegen auf `bg-button`."""
    bare = [
        (name, " ".join(tag.split())[:90])
        for name, text in _template_text().items()
        for tag in re.findall(r"<button\b[^>]*>", text, flags=re.S)
        if re.search(r"\bborder-rule\b", tag) and not re.search(r"\bbg-(?!opacity)", tag)
        and "rounded border" in " ".join(tag.split())
    ]

    assert bare == []
