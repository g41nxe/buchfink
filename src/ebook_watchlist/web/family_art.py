"""Bilder und Zeichen der Merkmalsfamilien (#55).

Jede Familie und jedes Erzählmuster hat ein Stimmungsbild und ein Zeichen. Das
Bild steht nur auf der Karte der Erstaufnahme, das Zeichen überall vor dem
Namen. Beide liegen neben dem Vokabular in ``vocabulary/bilder/<id>.jpg`` und
``vocabulary/zeichen/<id>.svg`` — und wie dieses nicht in Git (#59), denn ihre
Namen sind die der Familien. Fehlt eine Datei, fehlt eben Bild oder Zeichen;
die Seite sieht dann aus wie vorher.

Eine eigene Fassung des Vokabulars (#59) braucht keine eigenen: fehlt ihr
Ordner, gelten die der bisherigen, und eine Familie, die eine alte ersetzt,
trägt deren Bild und Zeichen.

Ein Zeichen ist ein SVG-Fragment im 24er-Raster (Pfade mit
``fill="currentColor"``); es kommt als ``<symbol id="fz-<id>">`` ins Sprite
neben die übrigen Icons und erbt Farbe und Größe vom Text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from markupsafe import Markup

from ..judging.portrait import DEFAULT_VOCABULARY_DIR, VOCABULARY_DIR, to_stored


def _art_dir(name: str) -> Path:
    """Der Ordner der geltenden Fassung, sonst der der bisherigen."""
    own = VOCABULARY_DIR / name
    return own if own.is_dir() else DEFAULT_VOCABULARY_DIR / name


PICTURES_DIR = _art_dir("bilder")
SIGNS_DIR = _art_dir("zeichen")
#: Unter dieser Adresse liefert die App die Bilder aus.
PICTURES_URL = "/familien"


@dataclass(frozen=True, slots=True)
class FamilyArt:
    pictures: frozenset[str]
    signs: frozenset[str]
    sprite: Markup
    #: Die Id, unter der eine Familie der geltenden Fassung gespeichert wird —
    #: dort liegen Bild und Zeichen, wenn sie eine alte ersetzt.
    stored: Callable[[str], str] = field(default=lambda some_id: some_id)

    def _found(self, family_id: str, known: frozenset[str]) -> str | None:
        if family_id in known:
            return family_id
        old = self.stored(family_id)
        return old if old in known else None

    def picture(self, family_id: str) -> str | None:
        """Die Adresse des Bilds, oder None, wenn es keins gibt."""
        if (found := self._found(family_id, self.pictures)) is not None:
            return f"{PICTURES_URL}/{found}.jpg"
        return None

    def sign(self, family_id: str, css: str = "") -> Markup:
        """Das Zeichen als Icon, oder nichts, wenn es keins gibt."""
        if (found := self._found(family_id, self.signs)) is None:
            return Markup("")
        family_id = found
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
        pictures=_stems(PICTURES_DIR, ".jpg"), signs=signs, sprite=Markup(symbols),
        stored=to_stored(),
    )
