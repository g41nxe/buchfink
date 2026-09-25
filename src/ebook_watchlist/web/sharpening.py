"""Das Nachschärfen auf der Buchseite (#51, ADR 33 Punkt 7).

Jedes Buch, das die Leserin *Mag ich* oder *Doof* nennt, wird sofort gegen ihr
Profil gehalten — im Moment, in dem sie das Buch vor Augen hat. Nie
*Ausschließen*, nie die eigenen Sterne: das eine ist eine Anweisung an den
Stapel, das andere eine Anzeige.

Ein gemochtes Buch zeigt seine eigenen Merkmale und Erzählmuster als Karten,
im selben Bild wie Bildschirm 3 der Erstaufnahme: antippen zählt das Merkmal
zu den gemochten, bis zu drei lassen sich verstärken. Die Facetten bildet das
Werkzeug aus allen gemochten Merkmalen neu — nie aus Erzählmustern (#63) — und
bestätigt sie nicht eigens (24.09.2026).

Bei einem *Doof*-Buch bleibt es wie zuvor: was es verloren hat, wird als
Gegengewicht angeboten, mit der Nachfrage, wenn ein gemochtes Buch dasselbe
trägt. Trifft es eine Facette ganz, bleibt die Facette, wie sie ist.

Hinzugefügt wird nur über Bücher, nie über freie Eingabe. Jede Änderung ist
eine neue Fassung mit dem Buch als Anlass; danach urteilt der Code neu, ohne
Modell.

Dazu, bei jedem gelesenen Buch, **deine Sicht** (#79): was der Steckbrief nennt,
aber für die Leserin nicht stimmt, und was ihm fehlt. Das ist kein Eintrag ins
Profil, sondern ihre Auskunft über dieses Buch; sie steht an ihrer Bewertung
und geht der Beschreibung des Modells vor, wenn die Geschmacksform lernt. Auch
das Ergänzen bleibt an ein Buch gebunden: es sagt, was *dieses* Buch für sie
war.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from .. import reader_reasons
from ..config import Settings
from ..facets import (
    MOST_BOOSTED,
    Facet,
    Liked,
    ReadingProfile,
    ScopeError,
    derive_facets,
    family_description,
    family_name,
    family_names,
    is_pattern,
    merge_counterweights,
    scoped_counterweight,
    strength,
    strength_level,
)
from ..portrait import VocabularyError, fingerprint, load_vocabulary
from ..relations import RelationKind
from ..store import Store
from .book import _stored_portrait as stored_portrait
from .intake import Card, IntakeError, Pill, ShelfBook, defining_in, shelf_book

LIKED, DISLIKED = str(RelationKind.LIKED), str(RelationKind.DISLIKED)


@dataclass(frozen=True, slots=True)
class Family:
    """Ein Merkmal oder Erzählmuster eines *Doof*-Buchs (Nachfrage nach dem
    Gegengewicht)."""

    family_id: str
    name: str
    pattern: bool
    #: Welche gemochten Bücher es auch tragen — der Anlass für die Nachfrage.
    also_in: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sharpening:
    kind: str
    title: str
    #: Noch kein Steckbrief: gefragt werden kann erst, wenn er da ist.
    waiting: bool = False
    #: Das Modell kennt das Buch nicht; es trägt nichts bei.
    unknown: bool = False
    #: Bei *Mag ich*: die Merkmale und Erzählmuster dieses Buchs, gerankt.
    cards: tuple[Card, ...] = ()
    can_boost: bool = True
    #: Doof, trifft aber eine Facette ganz: die bleibt.
    kept: tuple[str, ...] = ()
    lost: tuple[Family, ...] = ()
    genre: str | None = None
    #: Deine Sicht (#79): die Familien des Buchs, die sich abwählen lassen …
    own: tuple[Family, ...] = ()
    #: … welche davon für die Leserin nicht stimmen …
    dropped: frozenset[str] = frozenset()
    #: … was sie ergänzt hat …
    added: tuple[Family, ...] = ()
    #: … und was sich ergänzen ließe: je Dimension (Name, ((id, Name), …)).
    choices: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()


def carried_by(families: Collection[str], books: Collection[ShelfBook]) -> tuple[ShelfBook, ...]:
    """Die Bücher, die alle diese Familien tragen — daraus die Stärke."""
    return tuple(b for b in books if set(families) <= set(b.families))


def liked_shelf(store: Store, settings: Settings, vocabulary) -> list[ShelfBook]:
    """Alle gemochten Bücher mit Steckbrief — nicht nur die der Erstaufnahme."""
    books = (
        shelf_book(store, vocabulary, row.book_id)
        for row in store.relations(settings.slug, kind=LIKED)
    )
    return [b for b in books if b is not None]


def _kind(store: Store, settings: Settings, book_id: int) -> str | None:
    active = {r.kind for r in store.relations_of(settings.slug, book_id) if r.active}
    return LIKED if LIKED in active else DISLIKED if DISLIKED in active else None


def build(store: Store, settings: Settings, book_id: int) -> Sharpening | None:
    """Was dieses Buch am Profil ändern könnte — oder nichts, wenn es nichts
    zu schärfen gibt: kein Profil, oder weder *Mag ich* noch *Doof*."""
    profile = store.reading_profile(settings.slug)
    kind = _kind(store, settings, book_id)
    book = store.book(book_id)
    if profile is None or kind is None or book is None:
        return None
    try:
        vocabulary = load_vocabulary()
    except VocabularyError:
        return None
    shelf = shelf_book(store, vocabulary, book_id)
    if shelf is None:
        # Kein Steckbrief heißt warten; ein Steckbrief "unbekannt" heißt, dass
        # es hier nichts zu schärfen gibt — beides zu vermengen hieß, auf etwas
        # zu vertrösten, das nie kommt.
        portrait = stored_portrait(store, book, fingerprint(vocabulary))
        if portrait is not None and not portrait.known:
            return Sharpening(kind, book.title, unknown=True)
        return Sharpening(kind, book.title, waiting=True)

    return replace(
        _by_kind(store, settings, profile, kind, book.title, shelf, vocabulary),
        **_view_of_reasons(store, settings, book_id, kind, shelf, vocabulary),
    )


def _by_kind(store, settings, profile, kind, title, shelf, vocabulary) -> Sharpening:
    """Was ein *Mag ich*- oder ein *Doof*-Buch am Profil ändern könnte."""
    if kind == DISLIKED:
        liked_books = liked_shelf(store, settings, vocabulary)
        full_matches = [f for f in profile.facets if set(f.families) <= set(shelf.families)]
        existing_weights = {(c.families, c.genre) for c in profile.counterweights}

        def family_entry(f: str) -> Family:
            return Family(
                f, family_name(f, vocabulary), vocabulary.is_pattern(f),
                tuple(b.title for b in carried_by((f,), liked_books)),
            )

        return Sharpening(
            kind, title,
            kept=tuple(family_names(f.families, vocabulary) for f in full_matches),
            lost=tuple(
                family_entry(f) for f in shelf.families if ((f,), None) not in existing_weights
            ),
            genre=shelf.genre,
        )

    liked_books = liked_shelf(store, settings, vocabulary)
    liked_ids = {g.family for g in profile.liked}
    boosted_ids = {g.family for g in profile.liked if g.boosted}
    def level(f: str) -> int:
        carriers = carried_by((f,), liked_books)
        return strength_level(len(carriers), defining_in((f,), carriers))

    rank = sorted(shelf.families, key=lambda f: (-level(f), -len(carried_by((f,), liked_books)),
                                                  family_name(f, vocabulary).casefold()))

    def card(f: str) -> Card:
        carriers = carried_by((f,), liked_books)
        return Card(
            Pill(f, family_name(f, vocabulary), vocabulary.is_pattern(f), False, f in liked_ids,
                 boosted=f in boosted_ids),
            family_description(f, vocabulary),
            strength(len(carriers), defining_in((f,), carriers)),
            tuple((b.title, b.families[f]) for b in carriers),
        )

    return Sharpening(
        kind, title,
        cards=tuple(card(f) for f in rank),
        can_boost=len(boosted_ids) < MOST_BOOSTED,
    )


def family_choices(vocabulary) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Alle Familien des Vokabulars je Dimension, in der Reihenfolge der Datei.

    Eine Familie steht einmal, unter der Dimension ihres ersten Merkmals —
    *rasant* hat Merkmale im Tempo und in der Handlung.
    """
    by_dimension: dict[str, dict[str, str]] = {name: {} for name, _ in vocabulary.dimensions}
    seen: set[str] = set()
    for term in vocabulary.terms.values():
        family = vocabulary.family_of(term.id)
        if family.id in seen:
            continue
        seen.add(family.id)
        dimension = vocabulary.terms[family.members[0]].dimension
        by_dimension.setdefault(dimension, {})[family.id] = family.name
    return tuple(
        (name, tuple(sorted(families.items(), key=lambda kv: kv[1].casefold())))
        for name, families in by_dimension.items()
        if families
    )


def _view_of_reasons(store, settings, book_id, kind, shelf, vocabulary) -> dict:
    _, reasons = reader_reasons.of(store, settings.slug, book_id, kind)

    def entry(f: str) -> Family:
        return Family(f, family_name(f, vocabulary), is_pattern(f, vocabulary))

    return {
        "own": tuple(entry(f) for f in shelf.families),
        # Was nur hier gestört hat, zählt so wenig wie was nicht stimmt: beides
        # steht als abgewählt da und lässt sich hier zurücknehmen.
        "dropped": frozenset(reader_reasons.not_counted(reasons)),
        "added": tuple(entry(f) for f in reasons.get("add", ())),
        "choices": tuple(
            (name, tuple((f, n) for f, n in families if f not in shelf.families))
            for name, families in family_choices(vocabulary)
        ),
    }


def set_reasons(
    store: Store,
    settings: Settings,
    book_id: int,
    drop: Sequence[str],
    add: Sequence[str],
    *,
    now: datetime,
) -> None:
    """Deine Sicht auf ein gelesenes Buch (#79): was nicht stimmt, was fehlte.

    Ersetzt beides. Was die Leserin beim Gegengewicht *nur hier* gewählt hat,
    steht hier als abgewählt und geht in die neue Wahl auf. Abwählen lässt
    sich nur, was der Steckbrief nennt; ergänzen nur, was das Vokabular kennt
    und der Steckbrief nicht schon nennt. Was schon ergänzt war und inzwischen
    im Steckbrief steht oder das Vokabular nicht mehr kennt, fällt still weg,
    statt das Speichern zu blockieren.
    """
    kind = _kind(store, settings, book_id)
    if kind is None:
        raise IntakeError("Dieses Buch ist weder *Mag ich* noch *Doof*.")
    shelf, vocabulary = _book(store, settings, book_id, kind)
    drop = list(dict.fromkeys(f for f in drop if f))
    add = list(dict.fromkeys(f for f in add if f))
    known = {f for _, families in family_choices(vocabulary) for f, _ in families}
    bag, reasons = reader_reasons.of(store, settings.slug, book_id, kind)
    before = set(reasons.get("add", ()))
    for f in drop:
        if f not in shelf.families:
            raise IntakeError(f"{f} trägt dieses Buch nicht.")
    for f in [f for f in add if f not in before]:
        if f not in known:
            raise IntakeError(f"{f} kennt das Vokabular nicht.")
        if f in shelf.families:
            raise IntakeError(f"{f} steht schon im Steckbrief.")
    reasons = {
        "drop": drop,
        "add": [f for f in add if f in known and f not in shelf.families],
    }
    reader_reasons.keep(store, settings.slug, book_id, kind, bag, reasons, now=now)


def _book(store: Store, settings: Settings, book_id: int, kind: str):
    """Das Buch mit seinen Familien, und nur, wenn es wirklich so markiert ist."""
    if store.reading_profile(settings.slug) is None:
        raise IntakeError("Es gibt noch kein Leseprofil, das sich schärfen ließe.")
    if _kind(store, settings, book_id) != kind:
        raise IntakeError("Dieses Buch ist nicht so markiert.")
    vocabulary = load_vocabulary()
    shelf = shelf_book(store, vocabulary, book_id)
    if shelf is None:
        raise IntakeError("Zu diesem Buch gibt es noch keinen Steckbrief.")
    return shelf, vocabulary


def _facets_from(
    store: Store, settings: Settings, vocabulary, liked: tuple[Liked, ...]
) -> tuple[Facet, ...]:
    """Die Facetten aus allen gemochten Merkmalen neu gebildet — nie aus
    Erzählmustern (#63). Das Werkzeug bildet sie selbst; bestätigt wird nichts."""
    liked_books = liked_shelf(store, settings, vocabulary)
    liked_terms = [g.family for g in liked if not is_pattern(g.family, vocabulary)]
    carriers: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    for b in liked_books:
        titles[b.key] = b.title
        for f in b.families:
            carriers.setdefault(f, []).append(b.key)
    return tuple(
        Facet(f.families, tuple(titles[k] for k in f.books))
        for f in derive_facets(liked_terms, carriers)
    )


def set_liked(
    store: Store, settings: Settings, book_id: int, family_id: str, *, on: bool, now: datetime
) -> int | None:
    """Antippen: die Familie zählt jetzt zu den gemochten Merkmalen oder
    Erzählmustern — oder nicht mehr. Wer eine Familie wieder löst, löst auch
    ihre Verstärkung. Die Facetten werden aus allem Gemochten neu gebildet."""
    shelf, vocabulary = _book(store, settings, book_id, LIKED)
    if family_id not in shelf.families:
        raise IntakeError(f"{family_id} trägt dieses Buch nicht.")
    profile = store.reading_profile(settings.slug)
    boost = {g.family: g.boosted for g in profile.liked}
    if on:
        if family_id in boost:
            return None
        boost[family_id] = False
    else:
        if family_id not in boost:
            return None
        del boost[family_id]
    updated_liked = tuple(Liked(f, b) for f, b in boost.items())
    facets = _facets_from(store, settings, vocabulary, updated_liked)
    return store.put_reading_profile(
        settings.slug, ReadingProfile(facets, profile.counterweights, updated_liked),
        cause=f"Nachschärfen: {shelf.title}", now=now,
    )


def set_boosted(
    store: Store, settings: Settings, book_id: int, family_id: str, *, on: bool, now: datetime
) -> int | None:
    """Verstärken: höchstens ``MOST_BOOSTED``, und nur, was schon gemocht ist.
    Ändert nie die Facetten — nur, wie stark ein Merkmal für sich zählt."""
    shelf, _ = _book(store, settings, book_id, LIKED)
    profile = store.reading_profile(settings.slug)
    boost = {g.family: g.boosted for g in profile.liked}
    if family_id not in boost:
        raise IntakeError("Verstärken lässt sich nur, was du angetippt hast.")
    if boost[family_id] == on:
        return None
    if on and sum(boost.values()) >= MOST_BOOSTED:
        raise IntakeError(f"Höchstens {MOST_BOOSTED} lassen sich verstärken.")
    boost[family_id] = on
    updated_liked = tuple(Liked(f, b) for f, b in boost.items())
    return store.put_reading_profile(
        settings.slug, ReadingProfile(profile.facets, profile.counterweights, updated_liked),
        cause=f"Nachschärfen: {shelf.title}", now=now,
    )


def add_counterweights(
    store: Store, settings: Settings, book_id: int, scopes: Mapping[str, str], *, now: datetime
) -> int | None:
    """Gegengewichte aus einem *Doof*-Buch. ``scopes`` nennt je angetippter
    Familie ihren Umfang; *nur bei diesem Buch* zählt gegen nichts."""
    shelf, _ = _book(store, settings, book_id, DISLIKED)
    profile = store.reading_profile(settings.slug)
    new_weights = []
    only_here = []
    for f, scope in scopes.items():
        if f not in shelf.families:
            raise IntakeError(f"{f} trägt dieses Buch nicht.")
        try:
            weight = scoped_counterweight(f, scope, shelf.genre, shelf.title)
        except ScopeError as exc:
            raise IntakeError(str(exc)) from None
        if weight is not None:
            new_weights.append(weight)
        else:
            only_here.append(f)
    # *Nur bei diesem Buch* zählt gegen nichts — auch nicht, wenn die
    # Geschmacksform aus dem Buch lernt (#79). Wird eine Familie dagegen ein
    # Gegengewicht, hat das Buch sie für sie getragen: sie zählt wieder.
    reader_reasons.mark_only_here(store, settings.slug, book_id, DISLIKED, only_here, now=now)
    reader_reasons.unmark(
        store, settings.slug, book_id, DISLIKED, [f for f in scopes if f not in only_here],
        now=now,
    )
    counterweights, changed = merge_counterweights(profile.counterweights, new_weights)
    if not changed:
        return None
    return store.put_reading_profile(
        settings.slug, ReadingProfile(profile.facets, counterweights, profile.liked),
        cause=f"Nachschärfen: {shelf.title}", now=now,
    )
