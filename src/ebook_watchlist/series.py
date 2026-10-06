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

**Drei Zeugen.** Die DNB nennt den Band zur ISBN („Immerkalt" ist Band 3
der Immermorde), OverDrive in seiner Trefferliste (#83), und der Titel oft
selbst („Otherland. Band 2", Untertitel „Bobby Dollar 2"). Was zur ISBN
gespeichert ist, ist schon nach Herkunft entschieden (ADR 35). Ohne Zeugen ist
nichts ein Folgeband.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .cleaning import author_key
from .matching.normalize import named_volume, volume_of
from .models import MatchReason, Observation
from .relations import InterestKey

if TYPE_CHECKING:
    from .store import Store

_LEADING_NUMBER = re.compile(r"\s*(\d{1,3})")
#: „Die Flüsse-von-London-Reihe (Peter Grant)": der Zusatz in Klammern nennt
#: die Hauptfigur, nicht die Reihe.
_ADDENDUM = re.compile(r"\s*\([^)]*\)$")
_ARTICLE = re.compile(r"^(?:die|der|das|ein|eine)\s+")
_SUFFIX = re.compile(
    r"\s+(?:reihe|serie|trilogie|saga|zyklus|thriller|krimi|roman|ermittelt|ermitteln)$"
)


def series_key(name: str) -> str:
    """Woran sich entscheidet, ob zwei Namen dieselbe Reihe sind (ADR 35).

    „Die Cormoran-Strike-Reihe" und „Cormoran Strike", „Ein
    Wayward-Pines-Thriller" und „Wayward Pines": kleingeschrieben, Bindestriche
    als Leerzeichen, ohne Artikel vorn und ohne die Gattung hinten. Was danach
    leer wäre, bleibt stehen — „Die Reihe" ist `reihe`, nicht nichts.
    """
    plain = " ".join(name.casefold().replace("-", " ").split())
    text = " ".join(_ADDENDUM.sub("", name.casefold()).replace("-", " ").split()) or plain
    text = _ARTICLE.sub("", text) or text
    return _SUFFIX.sub("", text) or text


def _name(text: str) -> str:
    return " ".join(text.casefold().split())


#: Untertitel „Bobby Dollar 3", „Mysterien der Heide - Band 2": der Name, dann
#: höchstens ein Trennzeichen und ein Bandwort, dann eine kleine Zahl am Ende.
_SUBTITLE_FORM = re.compile(
    r"^(?P<name>.+?)\s*[-–:,]?\s*(?:band|bd\.?|teil|buch)?\s*(?P<volume>\d{1,2})$",
    re.IGNORECASE,
)
#: Titel „Otherland. Band 2", „The Heritage Universe - Band 3: Der kalte Tod":
#: hier muss das Bandwort stehen — „Die Hexenholzkrone 1" ist ein geteilter
#: Band, keine Reihe (dieselbe Grenze wie `named_volume`).
_TITLE_FORM = re.compile(
    r"^(?P<name>.{3,}?)\s*[.:–-]\s*(?:band|bd\.|teil|buch)\s+(?P<volume>\d{1,2})\b",
    re.IGNORECASE,
)
#: „Thriller: Natalie Price ermittelt 4" — ein Gattungswort vor dem Doppelpunkt
#: gehört nicht zum Namen.
_GENRE_PREFIX = re.compile(r"^\w[\w-]*:\s*")
#: „Band 2 und 3": hinter der Zahl folgt noch ein Band — ein Sammelband.
_TWO_VOLUMES = re.compile(r"\d\s*(?:und|&|-|–)$", re.IGNORECASE)
#: Was allein kein Name ist: „Folge 26", „Band 1".
_STRUCTURE_WORDS = frozenset(
    {"band", "bd", "folge", "teil", "buch", "episode", "special", "nummer", "nr"}
)


def series_from_title(title: str | None, subtitle: str | None) -> tuple[str, str] | None:
    """Reihe und Band, wenn Titel oder Untertitel sie in fester Form nennen (ADR 38).

    Zwei Formen, sonst nichts: der Titel „Name. Band n" geht vor, dann der
    Untertitel „Name n" oder „Name Band n", gelesen bis zum ersten „|". Drei
    Sperren gegen das Rauschen des Bestands: vom Namen muss nach der
    Schlüsselregel mehr als ein Strukturwort bleiben, hinter der Zahl darf
    kein zweiter Band folgen, und eine nackte Zahl im Titel zählt nicht.
    """
    if title and (hit := _TITLE_FORM.match(title.strip())):
        return _witness(hit.group("name"), hit.group("volume"))
    if subtitle:
        head = subtitle.split("|", 1)[0].strip().rstrip(".")
        if hit := _SUBTITLE_FORM.match(head):
            return _witness(_GENRE_PREFIX.sub("", hit.group("name")), hit.group("volume"))
    return None


def _witness(name: str, volume: str) -> tuple[str, str] | None:
    name = name.strip(" -–:,")
    if not name or _TWO_VOLUMES.search(name):
        return None
    words = set(series_key(name).split())
    if not words or words <= _STRUCTURE_WORDS:
        return None
    return name, volume


def volume_span(volumes: Iterable[str | None]) -> str | None:
    """„2–3" aus den Bänden eines Sammelbands; „2", wenn nur einer zählt (ADR 38).

    Der Folgeband-Filter liest daraus die erste Zahl: ein Sammelband mit
    Band 1 ist ein Einstieg, einer ab Band 2 nicht.
    """
    numbers = sorted({n for n in (_dnb_volume(v) for v in volumes) if n is not None})
    if not numbers:
        return None
    return str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}–{numbers[-1]}"


def _dnb_volume(index: str | None) -> int | None:
    """„3", „3.1", „Bd. 3" → 3. Was keine Zahl nennt, schweigt."""
    if not index:
        return None
    hit = _LEADING_NUMBER.match(re.sub(r"^\D+", "", index))
    return int(hit.group(1)) if hit else None


@dataclass(frozen=True, slots=True)
class SeriesOf:
    """Zu welcher Reihe ein Buch gehört, für die Oberfläche (#85)."""

    id: int
    name: str
    volume: str | None

    @property
    def label(self) -> str:
        """„Red Rising Saga · Band 3"."""
        return f"{self.name} · Band {self.volume}" if self.volume else self.name


@dataclass(frozen=True, slots=True)
class MidSeries:
    """Ob ein Fund ein späterer Band einer Reihe ist, die die Leserin nicht verfolgt."""

    #: ISBN → (Reihe, Band), schon nach Herkunft entschieden.
    known: Mapping[str, tuple[int | None, str | None]]
    #: (Schlüssel, Autor:in) → Reihe, für einen Fund ohne Eintrag zur ISBN.
    names: Mapping[tuple[str, str], int]
    #: Die Autor:innen, denen die Leserin folgt, klein geschrieben.
    authors: frozenset[str]
    #: Die Reihen ihrer eigenen Bücher. Ids, nicht Schlüssel: „Die Chroniken"
    #: zweier Autor:innen haben denselben Schlüssel und sind zwei Reihen.
    followed: frozenset[int]

    def __call__(self, observation: Observation) -> bool:
        if observation.match_reason is MatchReason.WATCHLIST:
            return False
        series, index = self.known.get(observation.isbn or "", (None, None))
        if series is None and observation.series:
            series = self.names.get(
                (series_key(observation.series), author_key(observation.author or ""))
            )
        volume = _dnb_volume(index)
        if volume is None:
            # Was die Quelle selbst nennt (OverDrive), wo zur ISBN nichts steht.
            volume = _dnb_volume(observation.series_index)
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
        return series is None or series not in self.followed


def mid_series_finder(store: Store, profile_slug: str) -> Callable[[Observation], bool]:
    """Einmal gelesen, für den ganzen Lauf oder die ganze Seite."""
    authors = frozenset(
        _name(row.value)
        for row in store.interests(profile_slug, key=str(InterestKey.AUTHOR))
    )
    own = store.books_by_id(store.books_with_relations(profile_slug).values())
    followed = store.series_ids_for(
        (book.isbn, book.series, book.author) for book in own.values()
    )
    return MidSeries(known=store.series_known(), names=store.series_names(),
                     authors=authors, followed=followed)
