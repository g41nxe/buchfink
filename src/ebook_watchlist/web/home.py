"""Die Startseite (Issue #5).

Was die Leserin jeden Tag zuerst sieht: ob das Werkzeug gelaufen ist, was
sich davon jetzt lohnt, und worüber sie entscheiden soll. Alles kommt aus dem
Store — der Tagesbericht wird nicht ein zweites Mal abgelegt, er ist eine
Darstellung dieser Daten, keine Quelle (docs/research/startseite-tracking-
werkzeuge.md, docs/reviews/design-review-2026-09-09.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import Profile
from ..relations import DONE_LABELS
from ..store import Store
from . import triage, watchlist
from .triage import Suggestion
from .watchlist import Entry

#: Die drei Verkaufsargumente aus der README — nur im Leerzustand. Wer die
#: Seite täglich öffnet, kennt sie; wer sie zum ersten Mal öffnet, hat sonst
#: nichts zu sehen. Die Bilder dazu kommen aus Issue #3.
ARGUMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "ic-star",
        "Jeder Stern hat einen Grund",
        "Ein Sprachmodell liest jeden Fund und schreibt in einem Satz, ob er zu dir passt.",
    ),
    (
        "ic-lib",
        "Zwei Quellen, eine Zeile",
        "Bibliothek und Shop für jeden Titel gleichzeitig — Preis hier, Verfügbarkeit dort.",
    ),
    (
        "ic-clock",
        "Der ganze Verlauf",
        "Jede Beobachtung wird angehängt, nie überschrieben.",
    ),
)


@dataclass(frozen=True, slots=True)
class Status:
    """Der letzte abgeschlossene Lauf, so wie die Statuszeile ihn braucht."""

    finished_at: datetime
    delta_count: int
    error: str | None
    now: datetime

    @property
    def when(self) -> str:
        """Dasselbe Format wie überall: Tag und Uhrzeit, kein Jahr, keine Sekunden."""
        return f"{self.finished_at:%d.%m. %H:%M}"

    @property
    def age_days(self) -> int:
        return (self.now - self.finished_at).days

    @property
    def stale(self) -> bool:
        """Ein Tageslauf, der einen Tag fehlt, ist eine Nachricht — keine Zahl."""
        return self.age_days >= 1

    @property
    def failed(self) -> bool:
        return bool(self.error)


@dataclass(frozen=True, slots=True)
class HomeView:
    status: Status | None
    #: Schnäppchen zuerst, das günstigste vorn, dann Ausleihbares.
    offers: tuple[Entry, ...]
    offers_total: int
    watchlist_total: int
    suggestions: tuple[Suggestion, ...]
    suggestions_total: int

    @property
    def first_run(self) -> bool:
        """Noch kein Lauf zu Ende — die Seite erklärt sich, statt Nullen zu zeigen."""
        return self.status is None


def build(store: Store, profile: Profile, *, now: datetime) -> HomeView:
    entries = watchlist.entries(store, profile, include_paused=False)
    offers = [entry for entry in entries if entry.deal or entry.borrowable]
    # Preis nur beim Schnäppchen ein Kriterium: ein ausleihbarer Titel ohne
    # Shop-Preis darf nicht zwischen zwei Preisen einsortiert werden.
    offers.sort(
        key=lambda entry: (
            not entry.deal,
            entry.price_cents or 0 if entry.deal else 0,
            entry.title.casefold(),
        )
    )
    # Wie viele Zeilen je Spalte stehen, sagt das Profil (``home_offers``,
    # ``home_suggestions``): das haengt am Bildschirm der Leserin und nicht am
    # Werkzeug. Der Rest haengt am Verweis darunter.
    pile = triage.pending(store, profile, limit=profile.home_suggestions)
    return HomeView(
        status=_status(store, profile.slug, now),
        offers=tuple(offers[:profile.home_offers]),
        offers_total=len(offers),
        watchlist_total=len(entries),
        suggestions=pile.items,
        suggestions_total=pile.total,
    )




@dataclass(frozen=True, slots=True)
class Undo:
    """Die gerade getroffene Entscheidung, so wie die Zeile sie anbietet."""

    key: str
    kind: str
    title: str

    @property
    def done(self) -> str:
        return DONE_LABELS[self.kind]


def _book_of(store: Store, key: str) -> int | None:
    source, _, item_id = key.partition(":")
    if not source or not item_id:
        return None
    return store.book_by_source_item(source, item_id)


def undo_for(store: Store, key: str, kind: str) -> Undo | None:
    """Was die Seite zurückzunehmen anbietet — nichts, wenn die Adresse
    etwas nennt, das es nicht gibt."""
    if kind not in DONE_LABELS:
        return None
    book_id = _book_of(store, key)
    book = store.book(book_id) if book_id is not None else None
    return Undo(key, kind, book.title) if book is not None else None


def undo(store: Store, profile: Profile, key: str, kind: str, *, now: datetime) -> bool:
    """Die Beziehung stilllegen, nicht löschen (ADR 18). Der Fund steht danach
    wieder im Stapel, weil nur aktive Beziehungen als Entscheidung zählen."""
    if kind not in DONE_LABELS:
        return False
    book_id = _book_of(store, key)
    if book_id is None:
        return False
    store.deactivate_relation(profile.slug, book_id, kind, now=now)
    return True


def _status(store: Store, profile_slug: str, now: datetime) -> Status | None:
    # Der jüngste *abgeschlossene* Rundgang. Ein Lauf, der gerade läuft oder
    # abgeschossen wurde, hat kein Ende — über den spricht die Übersicht.
    for run in store.recent_runs(profile_slug, limit=5):
        if run.finished_at is not None:
            return Status(run.finished_at, run.delta_count or 0, run.error, now)
    return None
