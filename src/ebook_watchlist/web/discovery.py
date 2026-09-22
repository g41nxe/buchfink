"""Die Seite zu einem Fund (Issue #9).

Ein unentschiedener Fund hat keine Buch-Zeile — ADR 18 legt sie erst an, wenn
die Leserin etwas über ihn gesagt hat. Er hat aber alles andere: Titel, Autor,
Klappentext, den Anlass, das Urteil des Bewertungstors und eine Geschichte über
mehrere Läufe. Diese Seite ist deshalb die Buchseite ohne die Teile, die es
noch nicht gibt, und der einzige Ort, an dem die **Begründung** des Tors
ausgeschrieben steht (ADR 19 wollte sie nachprüfbar machen; der Stapel zeigt
nur den Pitch).

Sie baut auf denselben Bausteinen wie ``book.py`` — ``Sighting``, ``Judgement``,
``Origin`` und deren Erzeuger —, damit dieselbe Auskunft nicht zweimal
verschieden entsteht.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import Settings
from ..deals import is_strong_deal
from ..ratings import VIA_DISCOVERY_PAGE
from ..reasons import thema_name
from ..sources import registry
from ..store import Store
from .book import (
    _AVAILABILITY,
    HISTORY_ROWS,
    Judgement,
    Origin,
    Sighting,
    _judgements,
    _origin,
    _price,
    rate_observation,
)
from .triage import _cover_file


@dataclass(frozen=True, slots=True)
class Page:
    """Was die Seite über einen Fund weiß."""

    source: str
    source_item_id: str
    title: str
    author: str | None
    series: str | None
    isbn: str | None
    cover_file: str | None
    blurb: str | None
    #: Die Quelle, die ihn gefunden hat — Name, Art und Adresse dort.
    source_label: str
    source_category: str
    url: str | None
    origin: Origin | None
    judgements: tuple[Judgement, ...]
    history: tuple[Sighting, ...]
    thema: str | None
    deal: bool

    @property
    def key(self) -> str:
        """Was die Entscheidungs-Formulare schicken — Quelle und Nummer, denn
        eine Buch-Nummer gibt es noch nicht."""
        return f"{self.source}:{self.source_item_id}"

    @property
    def price(self) -> str | None:
        return self.history[0].price if self.history else None

    @property
    def availability(self) -> str | None:
        """Was die Quelle zuletzt zur Ausleihe sagte — bei einem Shop nichts."""
        return self.history[0].availability if self.history else None

    @property
    def last_seen(self) -> datetime | None:
        """Wann die Quelle zuletzt gesprochen hat."""
        return self.history[0].when if self.history else None

    @property
    def recent_history(self) -> tuple[Sighting, ...]:
        """Die letzten Sichtungen — dieselbe Grenze wie auf der Buchseite."""
        return self.history[:HISTORY_ROWS]

    @property
    def hidden_history(self) -> int:
        return max(0, len(self.history) - HISTORY_ROWS)


def rate(store: Store, settings: Settings, source: str, item_id: str, *, now: datetime) -> str:
    """Einen Fund von seiner Seite aus neu beurteilen lassen (#15).

    Dieselbe Funktion wie auf der Buchseite, nur der Fund ist ein anderer: hier
    der, um den es auf der Seite geht, in seiner juengsten Fassung. Bei einem
    Fund ist ein schlechtes Urteil teurer als bei einem Buch — unter drei
    Sternen verschwindet er aus dem Stapel.
    """
    seen = store.observations_for_item(settings.slug, source, item_id)
    if not seen:
        return "Diesen Fund hat noch niemand gesehen — es gibt nichts zu beurteilen."
    return rate_observation(store, settings, seen[0], now=now, via=VIA_DISCOVERY_PAGE)


def build(store: Store, settings: Settings, source: str, item_id: str) -> Page | None:
    """Die Seite zu einem Fund, oder ``None``, wenn ihn nie jemand gesehen hat."""
    seen = store.observations_for_item(settings.slug, source, item_id)
    if not seen:
        return None

    newest = seen[0]
    history = tuple(
        Sighting(
            when=observation.observed_at,
            name=observation.source,
            source=registry.label(settings, observation.source),
            price=_price(observation.price_cents),
            availability=_AVAILABILITY.get(observation.availability)
            if observation.availability
            else None,
            # Ein Titel, der sich unter derselben Nummer ändert, heißt: die
            # Quelle hat die Ausgabe getauscht. Das ist eine Auskunft, keine
            # Kleinigkeit (ADR 18) — deshalb steht sie in der Zeile.
            other_title=(
                observation.title
                if observation.title.strip() != newest.title.strip()
                else None
            ),
            deal=is_strong_deal(observation.price_cents, settings),
        )
        for observation in seen
    )

    return Page(
        source=source,
        source_item_id=item_id,
        title=newest.title,
        author=newest.author,
        series=newest.series,
        isbn=newest.isbn,
        cover_file=_cover_file(newest),
        blurb=newest.blurb,
        source_label=registry.label(settings, source),
        source_category=registry.category(settings, source),
        url=newest.url,
        origin=_origin(seen),
        judgements=_judgements(store, None, seen, isbn=newest.isbn),
        history=history,
        thema=thema_name(newest.category),
        deal=is_strong_deal(newest.price_cents, settings),
    )
