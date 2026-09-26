"""Ein eigener Titel, den niemand findet, ist eine Frage (ADR 27).

`not_found` bleibt sonst eine Antwort und braucht niemanden. Hier aber sagt es
nichts über das Buch, sondern über die Eingabe: von neun so stehenden Titeln
waren am 6.9.2026 sieben schlicht falsch benannt — darunter ein Schnäppchen zu
2,99 €, das einen Tag lang unsichtbar blieb.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.models import LinkOutcome
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, watchlist

NOW = datetime(2026, 9, 6, 18, 0)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


def entry(db: Store, title: str, **sources: str) -> int:
    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title=title, author="Wer Auch Immer", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    for source, outcome in sources.items():
        db.put_book_source(
            book.id,
            source,
            outcome=outcome,
            url="https://x/1" if outcome == str(LinkOutcome.LINKED) else None,
            resolved_at=NOW,
            reason="",
        )
    return book.id


def entries(db: Store):
    return {e.book_id: e for e in watchlist.entries(db, load_settings())}


def test_all_sources_silent_is_a_question(db: Store) -> None:
    book_id = entry(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND),
                      onleihe=str(LinkOutcome.NOT_FOUND))

    assert entries(db)[book_id].missing


def test_one_source_finding_it_is_no_question(db: Store) -> None:
    """Vierzehn von vierzehn Einträgen stehen bei der Onleihe auf `not_found` —
    sie führt die meisten nicht. Eine Meldung je Quelle hätte jeden Titel jeden
    Tag gemeldet, genau der Fehler aus Ticket 04."""
    book_id = entry(db, "Die Straße", beam=str(LinkOutcome.LINKED),
                      onleihe=str(LinkOutcome.NOT_FOUND))

    assert not entries(db)[book_id].missing


def test_an_entry_nobody_has_looked_at_yet_is_no_question(db: Store) -> None:
    book_id = entry(db, "Frisch aufgenommen")

    assert not entries(db)[book_id].missing


def test_a_paused_entry_says_nothing(db: Store) -> None:
    settings = load_settings()
    book_id = entry(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND))
    db.deactivate_relation(settings.slug, book_id, str(RelationKind.WATCHING), now=NOW)

    assert not entries(db)[book_id].missing


def test_the_page_offers_to_correct_the_title(client: TestClient, db: Store) -> None:
    book_id = entry(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND))

    body = client.get("/watchlist").text

    assert "Keine Quelle kennt diesen Titel" in body
    assert f"/watchlist/{book_id}/rename" in body


def test_renaming_keeps_the_entry_and_drops_the_assignments(
    client: TestClient, db: Store
) -> None:
    """Umbenannt wird die bestehende Zeile: Notiz, Beziehung und Urteile hängen
    an ihrer Nummer. Die Zuordnungen fallen weg — sie galten für den alten
    Titel und stießen sonst nie eine neue Suche an."""
    book_id = entry(db, "Dunkle Gefilde", beam=str(LinkOutcome.NOT_FOUND))

    client.post(f"/watchlist/{book_id}/rename", data={"title": "Profit", "author": "R. Morgan"})

    book = db.book(book_id)
    assert book.title == "Profit"
    assert book.author == "R. Morgan"
    assert db.get_book_source(book_id, "beam") is None
    assert entries(db)[book_id].unresolved


def test_an_empty_title_changes_nothing(client: TestClient, db: Store) -> None:
    book_id = entry(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND))

    client.post(f"/watchlist/{book_id}/rename", data={"title": "   "})

    assert db.book(book_id).title == "Hardwired"


def test_i_know_hides_the_hint(client: TestClient, db: Store) -> None:
    book_id = entry(db, "Hardware", beam=str(LinkOutcome.NOT_FOUND))

    client.post(f"/watchlist/{book_id}/missing", data={"title": "Hardware"})

    entry_after = entries(db)[book_id]
    assert entry_after.missing
    assert entry_after.missing_known
    assert "Keine Quelle kennt diesen Titel" not in client.get("/watchlist").text


def test_after_a_rename_the_hint_comes_back(client: TestClient, db: Store) -> None:
    """Gemerkt wird der Titel, nicht das Buch: nach einer Umbenennung ist es
    eine neue Behauptung über eine neue Eingabe (ADR 27)."""
    book_id = entry(db, "Hardware", beam=str(LinkOutcome.NOT_FOUND))
    client.post(f"/watchlist/{book_id}/missing", data={"title": "Hardware"})

    client.post(f"/watchlist/{book_id}/rename", data={"title": "Hardwired"})
    db.put_book_source(book_id, "beam", outcome=str(LinkOutcome.NOT_FOUND), url=None,
                       resolved_at=NOW, reason="")

    assert not entries(db)[book_id].missing_known


def test_the_note_survives_a_dismissal(client: TestClient, db: Store) -> None:
    settings = load_settings()
    book_id = entry(db, "Hardware", beam=str(LinkOutcome.NOT_FOUND))
    db.put_relation(settings.slug, book_id, str(RelationKind.WATCHING), now=NOW,
                    note="Cyberpunk-Actioner.")

    client.post(f"/watchlist/{book_id}/missing", data={"title": "Hardware"})

    assert entries(db)[book_id].note == "Cyberpunk-Actioner."
