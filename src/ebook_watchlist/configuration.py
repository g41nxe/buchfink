"""Woher ein Lauf seine Konfiguration nimmt (Ticket 05, ADR 10).

Aus der Datenbank — YAML ist nur noch die Saatgutdatei. Was dort *bleibt*, sind
die Einstellungen, die nie eine Beziehung waren: Schwellwerte, welche Quellen
gebaut werden, die Kontaktadresse. Die haben keine Zeile in ADR 18 und gehören
weiterhin in eine Datei, die man versionieren kann.

Was aus der Datenbank kommt, ist alles, was die Leserin über *Bücher* und
*Interessen* sagt — und genau das war vorher über vier Dateien verstreut.

Es gibt bewusst **keinen stillen Rückfall auf YAML**. Eine leere Datenbank
bedeutet "noch nicht importiert", und das gehört gesagt, nicht heimlich
überbrückt: sonst liefe der Lauf monatelang gegen eine Datei, von der alle
annehmen, sie sei abgelöst.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from .config import Settings, WatchlistEntry
from .relations import InterestKey, RelationKind
from .store import InterestRow, Store


class NotSeeded(Exception):
    """Die Datenbank kennt weder Interessen noch beobachtete Bücher."""


@dataclass(frozen=True, slots=True)
class Configured:
    """Was ein Lauf braucht — Profil, Watchlist, und wer welches Interesse ist."""

    settings: Settings
    watchlist: list[WatchlistEntry]
    #: Interesse-Zeilen nach Wert, damit die Aussaat sie wiederfindet.
    author_interests: dict[str, InterestRow]
    thema_interests: dict[str, InterestRow]

    def interest_for(self, key: str, value: str) -> InterestRow | None:
        table = self.author_interests if key == InterestKey.AUTHOR else self.thema_interests
        return table.get(value)


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


def load(store: Store, settings: Settings) -> Configured:
    """Die Konfiguration dieses Profils, aus der Datenbank.

    ``settings`` liefert nur, was dort nicht steht: Schwellwerte, Quellen,
    Kontakt, Sweep-Tag.
    """
    interests = store.interests(settings.slug)
    authors = {row.value: row for row in interests if row.key == InterestKey.AUTHOR}
    themen = {row.value: row for row in interests if row.key == InterestKey.THEMA}

    core, extended = [], []
    for value, row in authors.items():
        (extended if _details(row).get("tier") == "extended" else core).append(value)

    watchlist = []
    for relation in store.relations(settings.slug, kind=str(RelationKind.WATCHING)):
        book = store.book(relation.book_id)
        if book is None:  # pragma: no cover - nur bei geloeschtem Buch
            continue
        details = _details(relation)
        restrict = details.get("restrict")
        watchlist.append(
            WatchlistEntry(
                title=book.title,
                author=book.author,
                isbn=book.isbn,
                # "library" und "shop" statt Quellennamen: wie eine Quelle
                # heisst, entscheidet die Konfiguration (Ticket 05, Review).
                check_library=restrict in (None, "library"),
                check_shop=restrict in (None, "shop"),
                active=True,  # inaktive Beziehungen liefert der Store nicht
                notes=details.get("note"),
            )
        )

    if not interests and not watchlist:
        raise NotSeeded(
            "die Datenbank kennt weder Interessen noch beobachtete Bücher — "
            "einmalig 'python -m ebook_watchlist.run seed' aufrufen"
        )

    settings = replace(
        settings,
        reference_authors=core,
        extended_authors=extended,
        genre_categories=list(themen),
        # Aus der Datenbank gelesene Buchlisten sind Beziehungen, keine
        # Freitextlisten mehr. Die Felder bleiben leer, damit niemand aus
        # Versehen gegen eine veraltete YAML-Kopie arbeitet.
        liked_books=[],
        disliked_books=[],
    )
    return Configured(
        settings=settings,
        watchlist=watchlist,
        author_interests=authors,
        thema_interests=themen,
    )
