"""Die feste Genre-Liste: BISAC-Codes mit deutschem Namen (ADR 37).

Das Genre eines Buchs war freier Text des Modells, 221 Schreibweisen in 393
Steckbriefen. Jetzt ist es ein Eintrag aus `docs/genres.yaml`: ein Code, an
dem Steckbriefe, Profil und Themen hängen, und ein Name für die Leserin. Die
Liste kennt keine Quelle; jede übersetzt die Codes selbst (``GENRES`` in ihren
``selectors.py``, siehe :meth:`ebook_watchlist.sources.base.Source.genre_address`).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

GENRES_PATH = Path(__file__).resolve().parents[2] / "docs" / "genres.yaml"
#: Was BISAC nicht kennt, steht mit diesem Anfang in der Liste.
EXTENSION_PREFIX = "DE-"


class GenreError(Exception):
    """Die Liste ist nicht lesbar — laut, nicht still (ADR 7)."""


@dataclass(frozen=True, slots=True)
class Genre:
    code: str
    name: str
    #: Die BISAC-Bezeichnung zum Nachprüfen; ``None`` bei einer Erweiterung.
    bisac: str | None
    #: Das Genre über einem Untergenre; ``None`` oben.
    parent: str | None = None
    extension: bool = False


class GenreList:
    """Die Liste, nach Code."""

    def __init__(self, genres: tuple[Genre, ...]) -> None:
        self._by_code = {genre.code: genre for genre in genres}

    def __iter__(self) -> Iterator[Genre]:
        return iter(self._by_code.values())

    def __contains__(self, code: object) -> bool:
        return code in self._by_code

    def get(self, code: str) -> Genre | None:
        return self._by_code.get(code)

    def name(self, code: str | None) -> str | None:
        genre = self._by_code.get(code or "")
        return genre.name if genre is not None else None

    def lineage(self, code: str) -> tuple[str, ...]:
        """Der Code und alles über ihm: Untergenre, dann Genre."""
        chain: list[str] = []
        genre = self._by_code.get(code)
        while genre is not None:
            chain.append(genre.code)
            genre = self._by_code.get(genre.parent or "")
        return tuple(chain)

    def covers(self, ancestor: str, code: str) -> bool:
        """Ob ``ancestor`` für ``code`` gilt — ein Genre für seine Untergenres."""
        return ancestor in self.lineage(code)


def parse_genres(text: str) -> GenreList:
    data = yaml.safe_load(text) or {}
    genres: list[Genre] = []

    def read(entry: dict, parent: str | None) -> None:
        code, name = entry.get("code"), entry.get("name")
        if not isinstance(code, str) or not isinstance(name, str) or not name.strip():
            raise GenreError(f"Genre ohne Code oder Namen: {entry!r}")
        extension = bool(entry.get("erweiterung", False))
        if extension != code.startswith(EXTENSION_PREFIX):
            raise GenreError(
                f"{code}: eine Erweiterung beginnt mit {EXTENSION_PREFIX!r} und ist als "
                "`erweiterung: true` markiert — beides oder keines"
            )
        if any(genre.code == code for genre in genres):
            raise GenreError(f"{code} steht zweimal in der Liste")
        genres.append(Genre(code, name.strip(), entry.get("bisac"), parent, extension))
        for child in entry.get("untergenres") or ():
            read(child, code)

    for entry in data.get("genres") or ():
        read(entry, None)
    return GenreList(tuple(genres))


@cache
def load_genres(path: Path = GENRES_PATH) -> GenreList:
    """Einmal gelesen; die Liste ändert sich nicht, während das Werkzeug läuft."""
    return parse_genres(path.read_text(encoding="utf-8"))
