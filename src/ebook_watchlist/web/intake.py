"""Die Erstaufnahme, Bildschirme 1 und 2: Bücher nennen und bestätigen (#47).

Eine Leserin ohne Profil nennt drei bis fünf Bücher, die sie geliebt hat, und
bis zu fünf, die sie enttäuscht haben (ADR 33, Punkt 6). Der Titel genügt: im
Hintergrund legt das Modell den Steckbrief an und erkennt dabei, welches Buch
gemeint ist, auch bei einem Tippfehler oder einem deutschen Titel. Die Leserin
bestätigt jeden Vorschlag; erst dann wird aus dem Eintrag ein Buch im Regal.

Es gibt keine Vorgeschichte: kein Klappentext, kein Eintrag im Bestand. Der
Steckbrief hängt deshalb zunächst an der Eingabe selbst und zieht beim
Bestätigen zum Buch um.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import Settings
from ..portrait import (
    Portrait,
    VocabularyError,
    fingerprint,
    load_vocabulary,
    portray,
)
from ..rating import RatingUnavailable, build_rater
from ..relations import RelationKind
from ..store import Store
from .book import portrait_subject

#: Die beiden Seiten, in der Reihenfolge der Seite, mit ihren Grenzen.
SIDES: dict[str, tuple[int, int]] = {
    str(RelationKind.LIKED): (3, 5),
    str(RelationKind.DISLIKED): (0, 5),
}

OPEN, CONFIRMED, REMOVED = "open", "confirmed", "removed"


class IntakeError(ValueError):
    """Eine Eingabe, die die Erstaufnahme nicht annimmt."""


def intake_subject(title: str, author: str | None) -> str:
    """Woran der Steckbrief einer Eingabe hängt, bevor es ein Buch gibt.

    Aus der Eingabe selbst gebildet: dieselbe Eingabe findet denselben
    Steckbrief wieder und kostet keinen zweiten Aufruf (ADR 33, Punkt 3).
    """
    return f"intake:{title.strip().casefold()}|{(author or '').strip().casefold()}"


@dataclass(frozen=True, slots=True)
class Entry:
    """Ein genannter Titel und was aus ihm geworden ist."""

    id: int
    side: str
    typed_title: str
    typed_author: str | None
    #: ``asking`` (das Modell arbeitet), ``proposed``, ``unknown`` oder
    #: ``confirmed``.
    state: str
    title: str | None = None
    author: str | None = None
    #: Nur, wenn er anders lautet als der Titel.
    original_title: str | None = None
    genre: str | None = None
    book_id: int | None = None


@dataclass(frozen=True, slots=True)
class Side:
    kind: str
    entries: tuple[Entry, ...]
    fewest: int
    most: int

    @property
    def confirmed(self) -> int:
        return sum(e.state == "confirmed" for e in self.entries)

    @property
    def full(self) -> bool:
        return len(self.entries) >= self.most


@dataclass(frozen=True, slots=True)
class Page:
    liked: Side
    disliked: Side

    @property
    def ready(self) -> bool:
        """Genug geliebte Bücher bestätigt, und keines wartet mehr auf Antwort."""
        return self.liked.confirmed >= self.liked.fewest and not any(
            e.state in ("asking", "proposed") for e in (*self.liked.entries, *self.disliked.entries)
        )


def _stored(store: Store, row) -> Portrait | None:
    try:
        abdruck = fingerprint(load_vocabulary())
    except VocabularyError:
        return None
    return store.portrait(intake_subject(row.typed_title, row.typed_author), abdruck)


def entry(store: Store, row) -> Entry:
    """Ein Eintrag, wie die Seite ihn zeigt."""
    if row.status == CONFIRMED:
        buch = store.book(row.book_id) if row.book_id else None
        return Entry(
            row.id, row.side, row.typed_title, row.typed_author, "confirmed",
            title=buch.title if buch else row.typed_title,
            author=buch.author if buch else row.typed_author,
            book_id=row.book_id,
        )
    bild = _stored(store, row)
    if bild is None:
        return Entry(row.id, row.side, row.typed_title, row.typed_author, "asking")
    if not bild.known:
        return Entry(row.id, row.side, row.typed_title, row.typed_author, "unknown")
    titel = bild.title or row.typed_title
    original = bild.original_title
    if original and original.strip().casefold() == titel.strip().casefold():
        original = None
    return Entry(
        row.id, row.side, row.typed_title, row.typed_author, "proposed",
        title=titel, author=bild.author, original_title=original, genre=bild.genre,
    )


def build(store: Store, settings: Settings) -> Page:
    eintraege = [entry(store, row) for row in store.intake_entries(settings.slug)]
    seiten = {
        kind: Side(kind, tuple(e for e in eintraege if e.side == kind), *grenzen)
        for kind, grenzen in SIDES.items()
    }
    return Page(liked=seiten[str(RelationKind.LIKED)], disliked=seiten[str(RelationKind.DISLIKED)])


def add(
    store: Store, settings: Settings, side: str, title: str, author: str | None, *, now: datetime
) -> int:
    """Einen Titel aufnehmen — sofort gespeichert, gefragt wird danach."""
    if side not in SIDES:
        raise IntakeError(f"unbekannte Seite {side!r}")
    title, author = title.strip(), (author or "").strip() or None
    if not title:
        raise IntakeError("Ohne Titel lässt sich nichts suchen.")
    genannt = [row for row in store.intake_entries(settings.slug) if row.side == side]
    if len(genannt) >= SIDES[side][1]:
        raise IntakeError(f"Höchstens {SIDES[side][1]} Bücher auf dieser Seite.")
    return store.add_intake_entry(settings.slug, side, title, author, now=now)


def identify(store: Store, settings: Settings, entry_id: int, *, now: datetime) -> str:
    """Das Modell fragen, welches Buch gemeint ist — die Arbeit im Hintergrund.

    Gibt zurück, was schiefging, oder nichts. Gespeichert wird nur eine
    Antwort; ein Fehler lässt den Eintrag offen, und er wird erneut gefragt.
    """
    row = store.intake_entry(entry_id)
    if row is None or row.status != OPEN:
        return ""
    try:
        vocabulary = load_vocabulary()
    except VocabularyError as exc:
        return str(exc)
    subject = intake_subject(row.typed_title, row.typed_author)
    if store.portrait(subject, fingerprint(vocabulary)) is not None:
        return ""
    rater = build_rater(settings.rating_model)
    if rater is None:
        return "Kein Bewerter eingerichtet: ohne Modell lässt sich kein Buch erkennen."
    try:
        bild = portray(row.typed_title, row.typed_author, None, rater.ask, vocabulary)
    except RatingUnavailable as exc:
        return str(exc)
    store.put_portrait(subject, bild, now=now)
    return ""


def retype(store: Store, entry_id: int, title: str, author: str | None) -> None:
    """„Anderes Buch": die Leserin gibt es genauer ein, und es wird neu gefragt."""
    row = store.intake_entry(entry_id)
    title = title.strip()
    if row is None or row.status != OPEN:
        raise IntakeError("Diesen Eintrag gibt es nicht mehr.")
    if not title:
        raise IntakeError("Ohne Titel lässt sich nichts suchen.")
    store.update_intake_entry(
        entry_id, typed_title=title, typed_author=(author or "").strip() or None
    )


def remove(store: Store, entry_id: int) -> None:
    """Entfernt wird nur aus der Erstaufnahme; ein bestätigtes Buch bleibt im
    Regal, dort nimmt man es auf der Buchseite zurück (ADR 18)."""
    if store.intake_entry(entry_id) is not None:
        store.update_intake_entry(entry_id, status=REMOVED)


def confirm(store: Store, settings: Settings, entry_id: int, *, now: datetime) -> int:
    """Ja, dieses Buch: es kommt mit seinem Steckbrief ins Regal.

    Das Buch wird unter dem erkannten Titel angelegt, nicht unter dem
    getippten — sonst stünde "Ted Williams" im Regal. Der Steckbrief zieht zum
    Buch um, damit die Buchseite ihn findet, ohne ein zweites Mal zu fragen.
    """
    row = store.intake_entry(entry_id)
    if row is None or row.status != OPEN:
        raise IntakeError("Diesen Eintrag gibt es nicht mehr.")
    bild = _stored(store, row)
    if bild is None or not bild.known:
        raise IntakeError("Zu diesem Eintrag gibt es noch keinen Vorschlag.")
    buch = store.find_or_create_book(
        isbn=None, title=bild.title or row.typed_title, author=bild.author, now=now
    )
    store.put_portrait(portrait_subject(buch), bild, now=now)
    store.put_relation(settings.slug, buch.id, row.side, active=True, now=now)
    store.update_intake_entry(entry_id, status=CONFIRMED, book_id=buch.id)
    return buch.id
