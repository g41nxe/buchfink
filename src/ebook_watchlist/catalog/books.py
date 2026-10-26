"""Ein Fund wird zu einem Buch — oder findet ein vorhandenes wieder (ADR 18).

Zwei Stufen, in dieser Reihenfolge:

1. **Die ISBN**, wo es eine gibt. Exakt, kein Ermessen.
2. **Der Matcher**, sonst. Buendel, Sammelausgaben und Einzelfolgen tragen keine
   ISBN — acht von 48 Kacheln einer echten Trefferseite —, und zwei Quellen
   fuehren dasselbe Buch nicht zwangslaeufig in derselben Ausgabe: von den zwei
   Buechern dieser Watchlist, die es bei beiden gibt, teilt eines die ISBN und
   eines nicht. Der Rueckfall ist also der Normalfall, nicht der Randfall.

Die Tabelle haelt Dutzende Zeilen, keine Zehntausende — deshalb darf die Suche
jedes Mal ueber alle gehen. Waere das teuer, waere ein Index auf den
normalisierten Formen noetig, und der wuerde still veralten, sobald sich die
Normalisierungsregeln aendern (ADR 18).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..matching import Candidate, Confidence, Query, match


@dataclass(frozen=True, slots=True)
class BookLike:
    """Das Wenige, das die Suche von einem Buch braucht."""

    id: int
    isbn: str | None
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class Found:
    book_id: int
    #: Woran es erkannt wurde — steht spaeter in der Begruendung.
    how: str


BY_ISBN = "isbn"
BY_MATCH = "match"


def find(
    books: Sequence[BookLike], *, isbn: str | None, title: str, author: str | None
) -> Found | None:
    """Das vorhandene Buch zu diesem Fund, falls es eines gibt.

    Eine uebereinstimmende ISBN entscheidet allein. Sie ist ausdruecklich
    staerker als ein widersprechender Titel: wenn zwei Quellen dieselbe ISBN
    unter verschiedenen Titeln fuehren, ist das eine Marketingvariante, kein
    zweites Buch.
    """
    if isbn:
        for book in books:
            if book.isbn and book.isbn == isbn:
                return Found(book.id, BY_ISBN)

    candidates = [
        Candidate(title=book.title, author=book.author, payload=book.id)
        for book in books
        # Ein Buch mit *anderer* ISBN ist eine andere Ausgabe. Es per Titel
        # einzusammeln wuerde die ISBN nachtraeglich entwerten.
        if not (isbn and book.isbn and book.isbn != isbn)
    ]
    if not candidates:
        return None

    resolution = match(Query(title=title, author=author), candidates)
    accepted = resolution.accepted
    if accepted is None or resolution.confidence is Confidence.NO_MATCH:
        return None
    return Found(int(accepted.payload), BY_MATCH)
