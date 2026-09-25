"""Meine Bücher: alles, was die Leserin als *Hab ich* führt (#71).

Ein Bestand, keine Aufgabe: nichts wird hier beobachtet oder abgeschlossen,
jede Zeile führt auf ihre Buchseite. Nicht „Bibliothek" — das Wort meint im
Glossar die Ausleihe (Onleihe, OverDrive).

Je Zeile Titelbild, Titel, Autor:in, die eigenen Sterne, wenn sie welche
gegeben hat, und die Übereinstimmung, wenn es einen Steckbrief gibt. Gesucht
wird in der Seite selbst (Alpine), sortiert über die Adresse wie in den
anderen Listen (``sorting.OWNED``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import Settings
from ..judging import load_judge
from ..ratings import BY_READER, book_subject
from ..relations import RelationKind
from ..store import Store
from . import sorting


@dataclass(frozen=True, slots=True)
class OwnedBook:
    book_id: int
    title: str
    author: str | None
    series: str | None
    cover_file: str | None
    #: Seit wann sie es als *Hab ich* führt.
    since: datetime | None
    #: Ihre eigenen Sterne, oder keine.
    stars: int | None = None
    #: Die gerechnete Übereinstimmung, wenn es einen Steckbrief gibt.
    percent: int | None = None
    fit_stars: int | None = None

    @property
    def search(self) -> str:
        """Wonach die Suche in der Seite filtert — klein geschrieben wie dort
        (``toLowerCase``); ``casefold`` machte aus „ß" ein „ss", und „Straße"
        fände sich nicht mehr."""
        return " ".join(p for p in (self.title, self.author, self.series) if p).lower()


def build(store: Store, settings: Settings, sort: str | None = None) -> list[OwnedBook]:
    relations = store.relations(settings.slug, kind=str(RelationKind.OWNED))
    since = {r.book_id: r.created_at for r in relations}
    books = store.books_by_id(list(since))
    ratings = store.ratings_for(book_subject(i) for i in books)
    judge = load_judge(store, settings.slug)
    subjects = {
        i: ([f"isbn:{b.isbn}"] if b.isbn else []) + [book_subject(i)] for i, b in books.items()
    }
    portraits = (
        judge.portraits(store, [s for ss in subjects.values() for s in ss])
        if judge is not None
        else {}
    )
    rows = []
    for book_id, book in books.items():
        own = ratings.get((book_subject(book_id), BY_READER))
        verdict = judge.verdict_among(portraits, subjects[book_id]) if judge else None
        rows.append(
            OwnedBook(
                book_id,
                book.title,
                book.author,
                book.series,
                book.cover_file,
                since.get(book_id),
                round(own.stars) if own is not None else None,
                verdict.percent if verdict is not None else None,
                verdict.stars if verdict is not None else None,
            )
        )
    return sorting.apply(sorting.OWNED, rows, sort)
