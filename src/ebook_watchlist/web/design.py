"""Die Bausteinseite ``/_design`` (#113).

Sie rendert die echten Makros und Teil-Templates, damit man jeden Baustein in
seinen Zuständen sieht — hell und dunkel, auf dem Telefon und am Schreibtisch.
Die Bücher kommen aus dem Bestand, wo es sie gibt; erfundene Beispiele springen
nur ein, wo er leer ist (CI, frischer Klon). Gestellt bleiben die Momente — ein
laufender Auftrag, ein fehlgeschlagener Lauf, ein überlanger Titel —, die es in
der Datenbank nur zufällig gibt. Ein neuer Baustein kommt zuerst hierher, dann
in eine Seite. Die Seite ist zugleich die Testfläche für die Layoutprüfungen im
Browser (#105).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from ..config import Settings
from ..store import Store
from . import home, symbols, triage, watchlist
from .runs import RunState

#: Der längste Titel, den der Stapel bisher gesehen hat, und noch etwas mehr:
#: an ihm zeigt sich, ob eine Zeile kürzt, statt zu brechen.
LONG_TITLE = (
    "Er – Er ist hier. Er beobachtet dich. Er will dich zerstören: "
    "Psychothriller über einen Stalker"
)

#: Die Farb-Tokens aus `assets/app.css`, in der Reihenfolge ihrer Rollen.
COLOR_TOKENS = (
    "paper", "card", "ink", "soft", "rule", "hair",
    "accent", "accent-bg", "amber", "amber-bg", "danger", "gold",
)


def _first(rows, label: str, test) -> list[tuple[str, object]]:
    found = next((row for row in rows if test(row)), None)
    return [(label, found)] if found is not None else []


def real_rows(store: Store, settings: Settings) -> dict:
    """Echte Zeilen aus dem Bestand, je eine für einen Fall, der vorkommt.

    Gerendert werden sie mit denselben Teil-Templates wie auf Watchlist und
    Stapel. Was es im Bestand nicht gibt — im CI, in einem frischen Klon —,
    fehlt hier einfach; dann springen die erfundenen Beispiele ein.
    """
    entries = watchlist.entries(store, settings, include_paused=False)
    items = triage.pending(store, settings, limit=500).items
    picked_entries = (
        _first(entries, "Schnäppchen", lambda e: e.deal and e.cover_file)
        + _first(entries, "ausleihbar", lambda e: e.borrowable and not e.deal and e.cover_file)
        + _first(entries, "ohne Urteil", lambda e: e.stars is None)
        + ([("längster Titel", max(entries, key=lambda e: len(e.title)))] if entries else [])
    )
    judged = [(i.percent, i) for i in items if i.percent is not None]
    picked_items = (
        ([("bestes Urteil", max(judged, key=lambda pair: pair[0])[1])] if judged else [])
        + _first(items, "knapp an der Schwelle", lambda i: i.borderline)
        + _first(items, "Sammelausgabe", lambda i: i.is_bundle)
        + _first(items, "ohne Cover", lambda i: not i.cover_file)
    )
    return {"watchlist": _unique(picked_entries), "suggestions": _unique(picked_items)}


def _unique(picked: list[tuple[str, object]]) -> list[tuple[str, object]]:
    """Ein Buch, das zwei Fälle erfüllt, steht nur einmal da."""
    seen, out = set(), []
    for label, row in picked:
        if id(row) not in seen:
            seen.add(id(row))
            out.append((label, row))
    return out


def context(now: datetime) -> dict:
    """Die erfundenen Daten für jeden Zustand, den die Seite zeigt."""
    return {
        "closings": watchlist.CLOSINGS,
        "actions": triage.ACTIONS,
        "icons": symbols.RELATION_ICONS,
        "color_tokens": COLOR_TOKENS,
        "long_title": LONG_TITLE,
        # `book_id` 0 gibt es nie: ein versehentlicher Klick träfe kein Buch.
        "entry": SimpleNamespace(book_id=0, active=True),
        "jobs": {
            "busy": SimpleNamespace(busy=True, trouble=None),
            "trouble": SimpleNamespace(busy=False, trouble="Das Modell hat nicht geantwortet"),
        },
        "statuses": {
            "fresh": home.Status(now - timedelta(hours=2), 3, None, now),
            "stale": home.Status(now - timedelta(days=2, hours=1), 0, None, now),
            "failed": home.Status(now - timedelta(hours=1), 0, "beam: kaputt", now),
        },
        "runs": {
            "idle": RunState("done", "Lauf abgeschlossen", "3 Änderungen"),
            "busy": RunState("running", "Lauf läuft …"),
            "failed": RunState(
                "failed",
                "Lauf mit Fehlern beendet",
                "SourceStructureError: OverDrive: Titel '7802220' nennt kein ownedCopies",
            ),
        },
    }
