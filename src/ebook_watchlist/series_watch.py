"""Eine Reihe beobachten: ihre Bände stehen auf der Watchlist (ADR 35, #85).

Wer eine Reihe lesen will, musste jeden Band einzeln auf die Watchlist setzen —
`watchlist.yaml` beginnt mit einem Abschnitt „Reihen-Einstiege". Jetzt
beobachtet sie die Reihe, und jeder bekannte Band bekommt ein Buch und eine
Beobachtung mit der Angabe ``series``. Nur diese schaltet „Nicht mehr
beobachten" wieder ab; einen Band, den sie selbst auf die Watchlist gesetzt
hat, lässt es in Ruhe.

Ein Band ist danach ein gewöhnlicher Watchlist-Eintrag: geprüft wie jeder
andere, gemeldet zu jedem Preis, ohne Tor.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime

from .junk import is_short_story
from .models import MatchReason, Observation
from .relations import REMOVED, RelationKind
from .store import Store

WATCHING = str(RelationKind.WATCHING)
#: Vermerk an einem Band, den „Nicht mehr beobachten" entfernt hat — nicht sie.
SERIES_ENDED = "series_ended"


def watched(store: Store, profile_slug: str) -> set[int]:
    """Die Reihen, die sie beobachtet."""
    return store.watched_series(profile_slug)


def watch(store: Store, profile_slug: str, series_id: int, *, now: datetime) -> int:
    """Die Reihe beobachten und ihre bekannten Bände auf die Watchlist setzen.

    Gibt zurück, wie viele Bände dazukamen.
    """
    store.set_series_watch(profile_slug, series_id, active=True, now=now)
    return sum(
        _put_on_watchlist(store, profile_slug, series_id, isbn, title, author, now, revive=True)
        for isbn, title, author in store.series_volumes(series_id)
    )


def unwatch(store: Store, profile_slug: str, series_id: int, *, now: datetime) -> None:
    """Nicht mehr beobachten: nur die Bände, die über die Reihe kamen.

    Entfernt, nicht pausiert (#72): ein Band, der nur über die Reihe auf der
    Watchlist stand, verschwindet von ihr, statt ruhend stehen zu bleiben — auch
    ein pausierter. Was sie selbst entfernt hatte, bleibt, wie es ist; nur was
    die Reihe entfernt (``SERIES_ENDED``), holt ein erneutes Beobachten zurück.
    """
    store.set_series_watch(profile_slug, series_id, active=False, now=now)
    for relation in store.relations(profile_slug, kind=WATCHING, active_only=False):
        details = json.loads(relation.details or "{}")
        if details.get("series") != series_id:
            continue
        if not relation.active and details.get(REMOVED):
            continue
        store.set_relation_details(profile_slug, relation.book_id, WATCHING,
                                   {**details, REMOVED: True, SERIES_ENDED: True}, now=now)
        store.deactivate_relation(profile_slug, relation.book_id, WATCHING, now=now)


def add_volumes(
    store: Store,
    profile_slug: str,
    series_id: int,
    found: Iterable[Observation],
    *,
    now: datetime,
) -> int:
    """Was das Fegen einer Reihe fand, auf die Watchlist — wenn sie sie beobachtet.

    Eine Kurzgeschichte bleibt draußen: geprüft wird der Band, wie er als Fund
    geprüft würde, denn erst die Aufnahme macht ihn zum Watchlist-Titel.
    """
    if series_id not in store.watched_series(profile_slug):
        return 0
    return sum(
        _put_on_watchlist(store, profile_slug, series_id, o.isbn, o.title, o.author, now)
        for o in found
        if o.isbn and not is_short_story(replace(o, match_reason=MatchReason.GENRE_CATEGORY))
    )


def _put_on_watchlist(
    store: Store,
    profile_slug: str,
    series_id: int,
    isbn: str,
    title: str,
    author: str | None,
    now: datetime,
    *,
    revive: bool = False,
) -> bool:
    """Ein Band auf die Watchlist — außer, sie hat schon etwas zu ihm gesagt.

    Auch eine stillgelegte Beobachtung ist etwas, das sie gesagt hat: einen
    Band, den sie entfernt oder pausiert hat, setzt das Fegen jedes Laufs nicht
    zurück (Review, 04.10.2026). Nur ``revive`` — sie beobachtet die Reihe
    wieder — holt zurück, was die Reihe selbst entfernt hatte.
    """
    book = store.find_or_create_book(isbn=isbn, title=title, author=author, now=now)
    relations = store.relations_of(profile_slug, book.id)
    if any(r.active for r in relations):
        return False
    watching = next((r for r in relations if r.kind == WATCHING), None)
    if watching is not None:
        details = json.loads(watching.details or "{}")
        ended_by_series = details.get("series") == series_id and details.get(SERIES_ENDED)
        if not (revive and ended_by_series):
            return False
    store.put_relation(profile_slug, book.id, WATCHING, now=now, series=series_id)
    return True


def sweep(store: Store, profile_slug: str, sources, *, now: datetime) -> int:
    """Jede beobachtete Reihe bei jeder Quelle fegen, unter ihrer Adresse dort.

    Was gefunden wird, kommt in die Zuordnung (Band, Adresse), neue Bände auf
    die Watchlist. Ins Journal kommt es nicht: als Watchlist-Eintrag wird ein
    Band danach wie jeder andere geprüft und beim ersten Mal gemeldet — eine
    Sichtung hier nähme ihm genau diese erste Meldung. Eine Quelle, die
    scheitert, kostet nur sich.
    """
    added = 0
    for series_id in sorted(store.watched_series(profile_slug)):
        row = store.series_row(series_id)
        if row is None:
            continue
        authors = [author for _, _, author in store.series_volumes(series_id) if author]
        author = authors[0] if authors else row.author_key or None
        for source in sources:
            ref = {"overdrive": row.overdrive_ref, "onleihe": row.onleihe_ref}.get(source.name)
            try:
                found = source.by_series(row.name, author, ref)
            except Exception as exc:  # noqa: BLE001 - eine Quelle, nicht der Lauf
                print(f"Reihe {row.name}: {source.name} {type(exc).__name__}", file=sys.stderr)
                continue
            found = [replace(o, series=o.series or row.name) for o in found if o.isbn]
            store.file_series(found)
            added += add_volumes(store, profile_slug, series_id, found, now=now)
    return added


@dataclass(frozen=True, slots=True)
class SeriesView:
    """Die Reihe eines Buchs, wie Buch- und Fundseite sie zeigen (#85)."""

    id: int
    label: str
    watched: bool


def view(store: Store, profile_slug: str, isbn: str | None) -> SeriesView | None:
    """„Red Rising Saga · Band 1", und ob sie die Reihe beobachtet."""
    named = store.series_of([isbn]).get(isbn) if isbn else None
    if named is None:
        return None
    return SeriesView(named.id, named.label, named.id in store.watched_series(profile_slug))
