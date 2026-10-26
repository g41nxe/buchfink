"""Ausgaben und Quellen eines Werks, für die Werkseite (#111, ADR 42).

Ein Werk ist ein Schlüssel über ISBNs (ADR 36, `work_entry`); hier wird er
nur nachgeschlagen. Je Ausgabe des Werks stehen ihre Quellen mit dem letzten
Stand — Preis hier, Ausleihbarkeit dort, auf einer Seite statt auf zweien.

Die genannte Ausgabe steht vorn, dann die in den Lesesprachen in deren
Rangfolge, dann die übrigen; Ausgaben in fremden Sprachen stehen hinter
„weitere Ausgaben“. Unbekannt ist nie fremd (#10).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..deals import is_strong_deal
from ..language import is_other_language, language_finder, language_name, language_of_isbn
from ..models import Observation
from ..sources import registry
from ..store import Store
from .book import _AVAILABILITY, _price


@dataclass(frozen=True, slots=True)
class Tile:
    display: str
    library: bool
    url: str | None
    price: str | None
    availability: str | None
    deal: bool


@dataclass(frozen=True, slots=True)
class Edition:
    isbn: str
    title: str
    author: str | None
    #: Die Sprache als ISO-639-2-Code, wo sie bekannt ist.
    code: str | None
    #: Die Ausgabe, deren Seite das ist.
    named: bool
    #: In einer Sprache, die keine Lesesprache ist.
    foreign: bool
    tiles: tuple[Tile, ...]

    @property
    def language(self) -> str | None:
        return language_name(self.code) if self.code else None


@dataclass(frozen=True, slots=True)
class Editions:
    shown: tuple[Edition, ...]
    #: Ausgaben in fremden Sprachen, hinter „weitere Ausgaben“.
    more: tuple[Edition, ...]

    @property
    def worth_showing(self) -> bool:
        """Mehr als eine Ausgabe oder mehr als eine Quelle — sonst sagt der
        Kopf der Seite schon alles."""
        everything = self.shown + self.more
        return len(everything) > 1 or sum(len(e.tiles) for e in everything) > 1


def _tile(observation: Observation, settings: Settings) -> Tile:
    return Tile(
        display=registry.label(settings, observation.source),
        library=registry.category(settings, observation.source) == "library",
        url=observation.url,
        price=_price(observation.price_cents),
        availability=_AVAILABILITY.get(observation.availability)
        if observation.availability
        else None,
        deal=is_strong_deal(observation.price_cents, settings),
    )


def build(store: Store, settings: Settings, isbn: str | None) -> Editions:
    """Die Ausgaben des Werks dieser ISBN, mit ihren Quellen."""
    if not isbn:
        return Editions((), ())
    isbns = store.work_siblings([isbn]).get(isbn) or {isbn}
    sightings = store.sightings_by_isbn(settings.slug, isbns)
    language_of = language_finder(store)
    editions = []
    for each in isbns:
        seen = sightings.get(each) or []
        if not seen:
            continue
        newest = max(seen, key=lambda o: (o.observed_at is not None, o.observed_at or 0))
        code = language_of(each) or language_of_isbn(each)
        editions.append(Edition(
            isbn=each,
            title=newest.title,
            author=newest.author,
            code=code,
            named=each == isbn,
            foreign=is_other_language(code, settings),
            tiles=tuple(_tile(o, settings) for o in sorted(seen, key=lambda o: o.source)),
        ))

    def rank(edition: Edition) -> tuple:
        known = edition.code in settings.languages
        position = settings.languages.index(edition.code) if known else len(settings.languages)
        return (not edition.named, position, edition.title, edition.isbn)

    ordered = sorted(editions, key=rank)
    return Editions(
        shown=tuple(e for e in ordered if not e.foreign or e.named),
        more=tuple(e for e in ordered if e.foreign and not e.named),
    )
