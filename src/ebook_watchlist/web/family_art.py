"""Bilder und Zeichen der Merkmalsfamilien (#55).

Jede Familie und jedes Erzählmuster hat ein Stimmungsbild und ein Zeichen. Das
Bild steht nur auf der Karte der Erstaufnahme, das Zeichen überall vor dem
Namen. Beide liegen neben dem Vokabular in ``vocabulary/bilder/<id>.jpg`` und
``vocabulary/zeichen/<id>.svg`` — und wie dieses nicht in Git (#59), denn ihre
Namen sind die der Familien. Fehlt eine Datei, fehlt eben Bild oder Zeichen;
die Seite sieht dann aus wie vorher.

Ein Zeichen ist ein SVG-Fragment im 24er-Raster (Pfade mit
``fill="currentColor"``); es kommt als ``<symbol id="fz-<id>">`` ins Sprite
neben die übrigen Icons und erbt Farbe und Größe vom Text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from markupsafe import Markup

from ..judging.portrait import VOCABULARY_DIR

PICTURES_DIR = VOCABULARY_DIR / "bilder"
SIGNS_DIR = VOCABULARY_DIR / "zeichen"
#: Unter dieser Adresse liefert die App die Bilder aus.
PICTURES_URL = "/familien"


@dataclass(frozen=True, slots=True)
class FamilyArt:
    pictures: frozenset[str]
    signs: frozenset[str]
    sprite: Markup

    def picture(self, family_id: str) -> str | None:
        """Die Adresse des Bilds, oder None, wenn es keins gibt."""
        if family_id in self.pictures:
            return f"{PICTURES_URL}/{family_id}.jpg"
        return None

    def sign(self, family_id: str, css: str = "") -> Markup:
        """Das Zeichen als Icon, oder nichts, wenn es keins gibt."""
        if family_id not in self.signs:
            return Markup("")
        return Markup('<svg class="i fz {}" aria-hidden="true"><use href="#fz-{}"/></svg>').format(
            css, family_id
        )


def _stems(directory: Path, suffix: str) -> frozenset[str]:
    if not directory.is_dir():
        return frozenset()
    return frozenset(p.stem for p in directory.glob(f"*{suffix}"))


def load() -> FamilyArt:
    """Was gerade an Bildern und Zeichen daliegt."""
    signs = _stems(SIGNS_DIR, ".svg")
    symbols = "".join(
        f'<symbol id="fz-{k}" viewBox="0 0 24 24">'
        f'{(SIGNS_DIR / f"{k}.svg").read_text(encoding="utf-8").strip()}</symbol>'
        for k in sorted(signs)
    )
    return FamilyArt(
        pictures=_stems(PICTURES_DIR, ".jpg"), signs=signs, sprite=Markup(symbols)
    )
