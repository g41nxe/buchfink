"""Nicht mitten in einer Reihe anfangen.

Die Regel stand im alten Leseprofil unter „Einstieg": abgeschlossene
Einzelbände jederzeit, Reihen von Autor:innen, die die Leserin ausdrücklich
mag, auch mittendrin — aber Band 5 einer Reihe, die sie nicht verfolgt, ist
kein Angebot, so gut das Buch für sich sein mag. Das alte Modell las sie als
Text und gab null Sterne; mit ihm ging sie verloren (#52). Jetzt rechnet sie
der Code.

Wie Sprache und KI-Autorschaft eine Frage der Form, nicht des Geschmacks:
der Lauf filtert vor dem Tor, damit ein Folgeband keinen Steckbrief kostet,
der Stapel beim Anzeigen. Beide fragen hier.

**Zwei Zeugen.** Der Titel nennt den Band oft selbst („Otherland. Band 2",
Untertitel „Bobby Dollar 2"), die DNB auch dort, wo er schweigt („Immerkalt"
ist Band 3 der Immermorde). Ohne beide ist nichts ein Folgeband.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .matching.normalize import named_volume, volume_of
from .models import MatchReason, Observation
from .relations import InterestKey

if TYPE_CHECKING:
    from .store import Store

_LEADING_NUMBER = re.compile(r"\s*(\d{1,3})")


def _name(text: str) -> str:
    return " ".join(text.casefold().split())


def _dnb_volume(index: str | None) -> int | None:
    """„3", „3.1", „Bd. 3" → 3. Was keine Zahl nennt, schweigt."""
    if not index:
        return None
    hit = _LEADING_NUMBER.match(re.sub(r"^\D+", "", index))
    return int(hit.group(1)) if hit else None


@dataclass(frozen=True, slots=True)
class MidSeries:
    """Ob ein Fund ein späterer Band einer Reihe ist, die die Leserin nicht verfolgt."""

    #: ISBN → (Reihe, Band) nach der DNB.
    dnb: Mapping[str, tuple[str | None, str | None]]
    #: Die Autor:innen, denen die Leserin folgt, klein geschrieben.
    authors: frozenset[str]
    #: Die Reihen ihrer eigenen Bücher, klein geschrieben.
    followed: frozenset[str]

    def __call__(self, observation: Observation) -> bool:
        if observation.match_reason is MatchReason.WATCHLIST:
            return False
        series, index = self.dnb.get(observation.isbn or "", (None, None))
        volume = _dnb_volume(index)
        if volume is None:
            # Im Titel nur mit Wort: „Station 11" ist ein Einzelband. Im
            # Untertitel steht die Reihe mit Nummer („Bobby Dollar 2").
            volume = named_volume(observation.title or "")
        if volume is None and observation.subtitle:
            volume = volume_of(observation.subtitle)
        if volume is None or volume <= 1:
            return False
        if observation.author and _name(observation.author) in self.authors:
            return False
        return not (series and _name(series) in self.followed)


def mid_series_finder(store: Store, profile_slug: str) -> Callable[[Observation], bool]:
    """Einmal gelesen, für den ganzen Lauf oder die ganze Seite."""
    authors = frozenset(
        _name(row.value)
        for row in store.interests(profile_slug, key=str(InterestKey.AUTHOR))
    )
    own = store.books_by_id(store.books_with_relations(profile_slug).values())
    followed = frozenset(_name(book.series) for book in own.values() if book.series)
    return MidSeries(dnb=store.dnb_series(), authors=authors, followed=followed)
