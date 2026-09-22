"""Was das Werkzeug über die Leserin zu wissen glaubt (Ticket 09).

Ausdrücklich **nur lesend**. Das Leseprofil liegt als Repo-Datei mit eigenem
Änderungsverfahren und einer asymmetrischen Beweislast (ADR 17): ein Formular
hier würde genau dieses Verfahren umgehen. Die Seite zeigt ihn, verlinkt ihn
und nennt den Weg, auf dem er sich ändert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import Settings
from ..rating import (
    LESEPROFIL_PATH,
    RatingUnavailable,
    load_leseprofil,
    load_rating_scheme,
)
from ..reasons import thema_name
from ..relations import InterestKey, RelationKind, labelled
from ..store import Store

#: Wie oft der lange Ausläufer gefegt wird — dieselbe Frist, die der Lauf
#: benutzt. Hier nur zur Anzeige.
EXTENDED_SWEEP_KEY = "last_extended_sweep"
SWEEP_INTERVAL = timedelta(days=7)

_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

_RELATION_LABELS: tuple[tuple[str, str], ...] = labelled(
    RelationKind.WATCHING,
    RelationKind.OWNED,
    RelationKind.LIKED,
    RelationKind.DISLIKED,
    RelationKind.DISMISSED,
)


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


@dataclass(frozen=True, slots=True)
class Interest:
    value: str
    label: str
    tier: str
    active: bool

    @property
    def weekly(self) -> bool:
        return self.tier == "extended"


@dataclass(frozen=True, slots=True)
class Held:
    """Ein Buch, wie es in einer der Regale steht."""

    book_id: int
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class Shelf:
    """Eine Beziehungsart mit den Buechern dahinter (Ticket 49).

    Bis dahin stand hier nur eine Zahl. Solange nichts die Watchlist verliess,
    reichte das; seit Ticket 48 verlaesst sie etwas, und ohne diesen Rueckweg
    waere ein Buch nach einem Klick auf "im Besitz" nur noch ueber seine
    Nummer zu finden.
    """

    kind: str
    label: str
    books: tuple[Held, ...]

    @property
    def count(self) -> int:
        return len(self.books)


@dataclass(frozen=True, slots=True)
class Overview:
    authors: tuple[Interest, ...]
    themen: tuple[Interest, ...]
    counts: tuple[Shelf, ...]
    strong_deal: str
    deal: str
    min_discount: int
    sweep_weekday: str
    last_sweep: datetime | None
    no_gos: tuple[str, ...]
    leseprofil: str | None
    profile_version: int | None
    leseprofil_path: str
    #: Das Verfahren, ohne Version (ADR 21).
    scheme: str | None

    @property
    def next_sweep(self) -> str:
        """Wann der wöchentliche Durchgang wieder ansteht.

        Ein Lauf, der nie stattfand, darf keine ganze Woche kosten — deshalb
        ist ein überfälliger Sweep sofort fällig, nicht erst am Wochentag
        (ADR 4). Die Anzeige sagt das genauso.
        """
        if self.last_sweep is None:
            return "beim nächsten Lauf"
        due = self.last_sweep + SWEEP_INTERVAL
        if due <= datetime.now():
            return "überfällig — beim nächsten Lauf"
        return f"{self.sweep_weekday}, frühestens {due:%d.%m.}"


def _money(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def build(store: Store, settings: Settings) -> Overview:
    rows = store.interests(settings.slug, active_only=False)

    def collect(key: InterestKey) -> tuple[Interest, ...]:
        return tuple(
            Interest(
                value=row.value,
                label=thema_name(row.value) or row.value
                if key is InterestKey.THEMA
                else row.value,
                tier=_details(row).get("tier", "core"),
                active=row.active,
            )
            for row in rows
            if row.key == key
        )

    # Nicht nur die Zahl, sondern die Buecher dahinter: was Ticket 48 aus der
    # Watchlist entfernt, war sonst nur ueber die Buch-Adresse zu finden, und
    # die muss man kennen (Ticket 49).
    #
    # Nur lesen. Die fuenf Knoepfe stehen auf der Buchseite, und eine dritte
    # Stelle, an der Beziehungen geschrieben werden, waere eine zu viel.
    #
    # Ohne Titelbild: von 53 Buechern haben 13 eine Bilddatei, eine Bildliste
    # bestuende zu drei Vierteln aus Platzhaltern.
    counts = tuple(
        Shelf(
            kind=kind,
            label=label,
            books=tuple(
                Held(book_id=buch.id, title=buch.title, author=buch.author)
                for row in store.relations(settings.slug, kind=kind)
                if (buch := store.book(row.book_id)) is not None
            ),
        )
        for kind, label in _RELATION_LABELS
    )

    try:
        # Die Datei, wie sie auf der Platte liegt — nicht die für das Modell
        # gerenderte Fassung. Geändert wird das Dokument, also gehört das
        # Dokument auf die Seite.
        _, version = load_leseprofil()
        leseprofil = LESEPROFIL_PATH.read_text(encoding="utf-8")
    except RatingUnavailable:
        leseprofil, version = None, None
    try:
        scheme = load_rating_scheme().text
    except RatingUnavailable:
        scheme = None

    return Overview(
        authors=collect(InterestKey.AUTHOR),
        themen=collect(InterestKey.THEMA),
        counts=counts,
        strong_deal=_money(settings.strong_deal_max_cents),
        deal=_money(settings.deal_max_cents),
        min_discount=settings.min_discount_pct,
        sweep_weekday=_WEEKDAYS[settings.extended_sweep_weekday % 7],
        last_sweep=store.get_state(settings.slug, EXTENDED_SWEEP_KEY),
        no_gos=tuple(settings.no_gos),
        leseprofil=leseprofil,
        profile_version=version,
        leseprofil_path=str(LESEPROFIL_PATH.name),
        scheme=scheme,
    )
