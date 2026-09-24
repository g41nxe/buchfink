"""Das Nachschärfen auf der Buchseite (#51, ADR 33 Punkt 7).

Jedes Buch, das die Leserin *Mag ich* oder *Doof* nennt, wird sofort gegen ihr
Profil gehalten — im Moment, in dem sie das Buch vor Augen hat. Nie
*Ausschließen*, nie die eigenen Sterne: das eine ist eine Anweisung an den
Stapel, das andere eine Anzeige.

Still geht nur das Bestärken: trägt ein gemochtes Buch eine Facette ganz, wird
sie stärker, und die Stärke ist abgeleitet, nicht gespeichert (ADR 16). Alles
Neue wird gefragt, im Muster der Erstaufnahme:

- ein gemochtes Buch, das keine Facette ganz trifft — was hält dich daran?
- Familien, die es mit anderen gemochten Büchern teilt und die noch keine
  Facette sind — eine neue Facette?
- bei einem *Doof*-Buch: was dich verloren hat, als Gegengewicht, mit der
  Nachfrage, wenn ein gemochtes Buch dasselbe trägt. Trifft es eine Facette
  ganz, bleibt die Facette, wie sie ist.

Hinzugefügt wird nur über Bücher, nie über freie Eingabe. Jede Änderung ist
eine neue Fassung mit dem Buch als Anlass; danach urteilt der Code neu, ohne
Modell.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime

from ..config import Settings
from ..facets import (
    MIN_FAMILIES,
    Facet,
    ReadingProfile,
    ScopeError,
    derive_facets,
    family_name,
    family_names,
    merge_counterweights,
    scoped_counterweight,
    strength,
)
from ..portrait import VocabularyError, fingerprint, load_vocabulary
from ..relations import RelationKind
from ..store import Store
from .book import _stored_portrait as stored_portrait
from .intake import IntakeError, ShelfBook, shelf_book

LIKED, DISLIKED = str(RelationKind.LIKED), str(RelationKind.DISLIKED)


@dataclass(frozen=True, slots=True)
class Strengthened:
    """Eine Facette, die dieses Buch still bestärkt."""

    name: str
    strength: str


@dataclass(frozen=True, slots=True)
class Family:
    family_id: str
    name: str
    pattern: bool
    #: Welche gemochten Bücher sie auch tragen — bei einem Doof-Buch der Anlass
    #: für die Nachfrage.
    also_in: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Eine neue Facette aus Familien, die mehrere gemochte Bücher teilen."""

    families: tuple[str, ...]
    name: str
    books: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Sharpening:
    kind: str
    title: str
    #: Noch kein Steckbrief: gefragt werden kann erst, wenn er da ist.
    waiting: bool = False
    #: Das Modell kennt das Buch nicht; es trägt nichts bei.
    unknown: bool = False
    strengthened: tuple[Strengthened, ...] = ()
    #: Gemocht, aber in keiner Facette: alles, was es trägt.
    uncovered: tuple[Family, ...] = ()
    suggestions: tuple[Suggestion, ...] = ()
    #: Doof, trifft aber eine Facette ganz: die bleibt.
    kept: tuple[str, ...] = ()
    lost: tuple[Family, ...] = ()
    genre: str | None = None


def carried_by(families: Collection[str], books: Collection[ShelfBook]) -> tuple[ShelfBook, ...]:
    """Die Bücher, die alle diese Familien tragen — daraus die Stärke."""
    return tuple(b for b in books if set(families) <= set(b.families))


def liked_shelf(store: Store, settings: Settings, vocabulary) -> list[ShelfBook]:
    """Alle gemochten Bücher mit Steckbrief — nicht nur die der Erstaufnahme."""
    buecher = (
        shelf_book(store, vocabulary, row.book_id)
        for row in store.relations(settings.slug, kind=LIKED)
    )
    return [b for b in buecher if b is not None]


def _kind(store: Store, settings: Settings, book_id: int) -> str | None:
    aktiv = {r.kind for r in store.relations_of(settings.slug, book_id) if r.active}
    return LIKED if LIKED in aktiv else DISLIKED if DISLIKED in aktiv else None


def build(store: Store, settings: Settings, book_id: int) -> Sharpening | None:
    """Was dieses Buch am Profil ändern könnte — oder nichts, wenn es nichts
    zu schärfen gibt: kein Profil, oder weder *Mag ich* noch *Doof*."""
    profil = store.reading_profile(settings.slug)
    kind = _kind(store, settings, book_id)
    buch = store.book(book_id)
    if profil is None or kind is None or buch is None:
        return None
    try:
        vocabulary = load_vocabulary()
    except VocabularyError:
        return None
    ich = shelf_book(store, vocabulary, book_id)
    if ich is None:
        # Kein Steckbrief heißt warten; ein Steckbrief "unbekannt" heißt, dass
        # es hier nichts zu schärfen gibt — beides zu vermengen hieß, auf etwas
        # zu vertrösten, das nie kommt.
        bild = stored_portrait(store, buch, fingerprint(vocabulary))
        if bild is not None and not bild.known:
            return Sharpening(kind, buch.title, unknown=True)
        return Sharpening(kind, buch.title, waiting=True)

    gemocht = liked_shelf(store, settings, vocabulary)
    andere = [b for b in gemocht if b.book_id != book_id]
    ganz = [f for f in profil.facets if set(f.families) <= set(ich.families)]

    def familie(f: str) -> Family:
        return Family(
            f, family_name(f, vocabulary), vocabulary.is_pattern(f),
            tuple(b.title for b in carried_by((f,), andere)),
        )

    if kind == DISLIKED:
        schon = {(c.families, c.genre) for c in profil.counterweights}
        return Sharpening(
            kind, buch.title,
            kept=tuple(family_names(f.families, vocabulary) for f in ganz),
            lost=tuple(familie(f) for f in ich.families if ((f,), None) not in schon),
            genre=ich.genre,
        )

    return Sharpening(
        kind, buch.title,
        strengthened=tuple(
            Strengthened(family_names(f.families, vocabulary),
                         strength(len(carried_by(f.families, gemocht))))
            for f in ganz
        ),
        uncovered=() if ganz else tuple(familie(f) for f in ich.families),
        suggestions=_suggestions(store, settings, profil, ich, andere, vocabulary),
    )


def _suggestions(store, settings, profil, ich, andere, vocabulary) -> tuple[Suggestion, ...]:
    """Familien, die dieses Buch mit anderen gemochten Büchern teilt und die
    zusammen noch keine Facette sind — abgeleitet wie in der Erstaufnahme.

    Nur aus Familien, die noch in keiner Facette stecken: "hart · gezeichnete
    Figur" und zwei Familien obendrauf wäre dieselbe Facette, nur enger, und
    keine neue Auskunft über den Geschmack.
    """
    belegt = {f for facet in profil.facets for f in facet.families}
    geteilt = [f for f in ich.families if f not in belegt and carried_by((f,), andere)]
    traeger = {f: [b.key for b in carried_by((f,), [ich, *andere])] for f in geteilt}
    titel = {b.key: b.title for b in [ich, *andere]}
    vorhanden = [set(f.families) for f in profil.facets]
    abgelehnt = store.declined_facets(settings.slug)
    vorschlaege = []
    for f in derive_facets(geteilt, traeger):
        familien = set(f.families)
        if (
            len(familien) < MIN_FAMILIES
            or ich.key not in f.books
            or any(familien <= v for v in vorhanden)
            or frozenset(familien) in abgelehnt
        ):
            continue
        vorschlaege.append(Suggestion(
            f.families, family_names(f.families, vocabulary),
            tuple(titel[k] for k in f.books),
        ))
    return tuple(vorschlaege)


def _book(store: Store, settings: Settings, book_id: int, kind: str):
    """Das Buch mit seinen Familien, und nur, wenn es wirklich so markiert ist."""
    if store.reading_profile(settings.slug) is None:
        raise IntakeError("Es gibt noch kein Leseprofil, das sich schärfen ließe.")
    if _kind(store, settings, book_id) != kind:
        raise IntakeError("Dieses Buch ist nicht so markiert.")
    vocabulary = load_vocabulary()
    ich = shelf_book(store, vocabulary, book_id)
    if ich is None:
        raise IntakeError("Zu diesem Buch gibt es noch keinen Steckbrief.")
    return ich, vocabulary


def add_facet(
    store: Store, settings: Settings, book_id: int, families: Collection[str], *, now: datetime
) -> int | None:
    """Eine neue Facette aus Familien dieses Buchs — nie aus freier Eingabe."""
    ich, vocabulary = _book(store, settings, book_id, LIKED)
    gewaehlt = tuple(f for f in ich.families if f in set(families))
    if len(gewaehlt) < MIN_FAMILIES:
        raise IntakeError("Eine Facette braucht mindestens zwei Familien.")
    profil = store.reading_profile(settings.slug)
    if any(set(gewaehlt) == set(f.families) for f in profil.facets):
        return None
    gemocht = liked_shelf(store, settings, vocabulary)
    neu = Facet(gewaehlt, tuple(b.title for b in carried_by(gewaehlt, gemocht)))
    return store.put_reading_profile(
        settings.slug, ReadingProfile((*profil.facets, neu), profil.counterweights),
        cause=f"Nachschärfen: {ich.title}", now=now,
    )


def decline(store: Store, settings: Settings, families: Collection[str], *, now: datetime) -> None:
    """„Passt nicht": dieser Vorschlag kommt nicht wieder. Keine neue Fassung."""
    if len(set(families)) >= MIN_FAMILIES:
        store.decline_facet(settings.slug, set(families), now=now)


def add_counterweights(
    store: Store, settings: Settings, book_id: int, scopes: Mapping[str, str], *, now: datetime
) -> int | None:
    """Gegengewichte aus einem *Doof*-Buch. ``scopes`` nennt je angetippter
    Familie ihren Umfang; *nur bei diesem Buch* zählt gegen nichts."""
    ich, _ = _book(store, settings, book_id, DISLIKED)
    profil = store.reading_profile(settings.slug)
    neu = []
    for f, umfang in scopes.items():
        if f not in ich.families:
            raise IntakeError(f"{f} trägt dieses Buch nicht.")
        try:
            gewicht = scoped_counterweight(f, umfang, ich.genre, ich.title)
        except ScopeError as exc:
            raise IntakeError(str(exc)) from None
        if gewicht is not None:
            neu.append(gewicht)
    gegen, geaendert = merge_counterweights(profil.counterweights, neu)
    if not geaendert:
        return None
    return store.put_reading_profile(
        settings.slug, ReadingProfile(profil.facets, gegen),
        cause=f"Nachschärfen: {ich.title}", now=now,
    )

