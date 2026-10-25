"""Mitnehmen und einspielen: ``ebw export`` und ``ebw import`` (#104).

Seit #104 ist die Datenbank die Wahrheit für alles, was eine Leserin einstellt.
YAML bleibt der Weg, es mitzunehmen — in eine andere Installation, in eine
Sicherung, die man lesen kann. Ein Export ist eine Datei mit fünf Teilen:
Einstellungen, Autor:innen, Themen, Watchlist und Besitz. Ein Import spielt sie
über denselben Weg ein wie das Saatgut (`seed.sow`): nichts doppelt, nichts
zurückgesetzt, was inzwischen anders ist.

Nicht dabei: Urteile, Steckbriefe, Leseprofil und die Geschichte der Preise —
die gehören in eine Sicherung der Datenbank (`scripts/sicherung.py`), nicht in
eine Datei zum Bearbeiten.
"""

from __future__ import annotations

import json
from datetime import datetime

from .config import (
    EDITABLE,
    ConfigError,
    OwnedBook,
    Seed,
    Settings,
    WatchlistEntry,
    load_settings,
)
from .relations import InterestKey, RelationKind
from .seed import SeedReport, sow
from .store import Store


class ImportError_(ValueError):
    """Eine Datei, die sich nicht einspielen lässt — und nichts wurde geändert."""


def _details(row) -> dict:
    try:
        return json.loads(row.details or "{}")
    except (TypeError, ValueError):  # pragma: no cover - defekte Zeile
        return {}


def export(store: Store, settings: Settings) -> dict:
    """Was die Leserin eingestellt hat, als eine Struktur für YAML."""
    slug = settings.slug
    authors = store.interests(slug, key=str(InterestKey.AUTHOR))
    watchlist = []
    for relation in store.relations(slug, kind=str(RelationKind.WATCHING), active_only=False):
        book = store.book(relation.book_id)
        if book is None:  # pragma: no cover - nur bei gelöschtem Buch
            continue
        entry: dict = {"title": book.title, "author": book.author}
        if book.isbn:
            entry["isbn"] = book.isbn
        restrict = _details(relation).get("restrict")
        if restrict in ("library", "shop"):
            entry["check"] = restrict
        if not relation.active:
            entry["active"] = False
        watchlist.append(entry)
    owned = []
    for relation in store.relations(slug, kind=str(RelationKind.OWNED)):
        book = store.book(relation.book_id)
        if book is not None:
            owned.append({"title": book.title, "author": book.author})
    return {
        "settings": {
            key: value for key in EDITABLE if (value := getattr(settings, key)) is not None
        },
        "reference_authors": {
            "core": [r.value for r in authors if _details(r).get("tier") != "extended"],
            "extended": [r.value for r in authors if _details(r).get("tier") == "extended"],
        },
        "genre_categories": [
            r.value for r in store.interests(slug, key=str(InterestKey.GENRE_CATEGORY))
        ],
        "watchlist": watchlist,
        "owned": owned,
    }


def _watchlist(rows: list | None) -> list[WatchlistEntry]:
    entries = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("title"):
            raise ImportError_(f"watchlist: jeder Eintrag braucht einen Titel, nicht {row!r}")
        check = row.get("check")
        entries.append(WatchlistEntry(
            title=str(row["title"]),
            author=row.get("author"),
            isbn=row.get("isbn"),
            check_library=check != "shop",
            check_shop=check != "library",
            active=row.get("active", True) is not False,
        ))
    return entries


def import_(store: Store, settings: Settings, data: dict, *, now: datetime) -> SeedReport:
    """Eine exportierte Datei einspielen.

    Die Einstellungen kommen zuerst und zur Probe: ist eine davon ungültig,
    wird nichts geändert — weder sie noch Bücher und Interessen.
    """
    if not isinstance(data, dict):
        raise ImportError_("Ein Export ist eine Zuordnung mit settings, watchlist, …")
    values = {key: value for key, value in (data.get("settings") or {}).items() if key in EDITABLE}
    before = store.saved_settings(settings.slug)
    store.save_settings(settings.slug, values, now=now)
    try:
        load_settings()
    except ConfigError as exc:
        store.save_settings(settings.slug, {key: before.get(key) for key in values}, now=now)
        raise ImportError_(f"Einstellungen: {exc}") from exc

    authors = data.get("reference_authors") or {}
    if isinstance(authors, list):
        authors = {"core": authors}
    seed = Seed(
        reference_authors=list(authors.get("core") or []),
        extended_authors=list(authors.get("extended") or []),
        genre_categories=list(data.get("genre_categories") or []),
    )
    owned = [
        OwnedBook(title=str(row["title"]), author=row.get("author"))
        for row in data.get("owned") or [] if isinstance(row, dict) and row.get("title")
    ]
    return sow(store, settings, seed, _watchlist(data.get("watchlist")), owned=owned, now=now)
