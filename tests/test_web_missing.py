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


def eintrag(db: Store, titel: str, **quellen: str) -> int:
    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title=titel, author="Wer Auch Immer", now=NOW)
    db.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    for quelle, ausgang in quellen.items():
        db.put_book_source(
            buch.id,
            quelle,
            outcome=ausgang,
            url="https://x/1" if ausgang == str(LinkOutcome.LINKED) else None,
            resolved_at=NOW,
            reason="",
        )
    return buch.id


def eintraege(db: Store):
    return {e.book_id: e for e in watchlist.entries(db, load_settings())}


def test_all_sources_silent_is_a_question(db: Store) -> None:
    buch_id = eintrag(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND),
                      onleihe=str(LinkOutcome.NOT_FOUND))

    assert eintraege(db)[buch_id].missing


def test_one_source_finding_it_is_no_question(db: Store) -> None:
    """Vierzehn von vierzehn Einträgen stehen bei der Onleihe auf `not_found` —
    sie führt die meisten nicht. Eine Meldung je Quelle hätte jeden Titel jeden
    Tag gemeldet, genau der Fehler aus Ticket 04."""
    buch_id = eintrag(db, "Die Straße", beam=str(LinkOutcome.LINKED),
                      onleihe=str(LinkOutcome.NOT_FOUND))

    assert not eintraege(db)[buch_id].missing


def test_an_entry_nobody_has_looked_at_yet_is_no_question(db: Store) -> None:
    buch_id = eintrag(db, "Frisch aufgenommen")

    assert not eintraege(db)[buch_id].missing


def test_a_paused_entry_says_nothing(db: Store) -> None:
    settings = load_settings()
    buch_id = eintrag(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND))
    db.deactivate_relation(settings.slug, buch_id, str(RelationKind.WATCHING), now=NOW)

    assert not eintraege(db)[buch_id].missing


def test_the_page_offers_to_correct_the_title(client: TestClient, db: Store) -> None:
    buch_id = eintrag(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND))

    body = client.get("/watchlist").text

    assert "Keine Quelle kennt diesen Titel" in body
    assert f"/watchlist/{buch_id}/umbenennen" in body


def test_renaming_keeps_the_entry_and_drops_the_assignments(
    client: TestClient, db: Store
) -> None:
    """Umbenannt wird die bestehende Zeile: Notiz, Beziehung und Urteile hängen
    an ihrer Nummer. Die Zuordnungen fallen weg — sie galten für den alten
    Titel und stießen sonst nie eine neue Suche an."""
    buch_id = eintrag(db, "Dunkle Gefilde", beam=str(LinkOutcome.NOT_FOUND))

    client.post(f"/watchlist/{buch_id}/umbenennen", data={"title": "Profit", "author": "R. Morgan"})

    buch = db.book(buch_id)
    assert buch.title == "Profit"
    assert buch.author == "R. Morgan"
    assert db.get_book_source(buch_id, "beam") is None
    assert eintraege(db)[buch_id].unresolved


def test_an_empty_title_changes_nothing(client: TestClient, db: Store) -> None:
    buch_id = eintrag(db, "Hardwired", beam=str(LinkOutcome.NOT_FOUND))

    client.post(f"/watchlist/{buch_id}/umbenennen", data={"title": "   "})

    assert db.book(buch_id).title == "Hardwired"


def test_i_know_hides_the_hint(client: TestClient, db: Store) -> None:
    buch_id = eintrag(db, "Hardware", beam=str(LinkOutcome.NOT_FOUND))

    client.post(f"/watchlist/{buch_id}/fehlt", data={"title": "Hardware"})

    eintrag_danach = eintraege(db)[buch_id]
    assert eintrag_danach.missing
    assert eintrag_danach.missing_known
    assert "Keine Quelle kennt diesen Titel" not in client.get("/watchlist").text


def test_after_a_rename_the_hint_comes_back(client: TestClient, db: Store) -> None:
    """Gemerkt wird der Titel, nicht das Buch: nach einer Umbenennung ist es
    eine neue Behauptung über eine neue Eingabe (ADR 27)."""
    buch_id = eintrag(db, "Hardware", beam=str(LinkOutcome.NOT_FOUND))
    client.post(f"/watchlist/{buch_id}/fehlt", data={"title": "Hardware"})

    client.post(f"/watchlist/{buch_id}/umbenennen", data={"title": "Hardwired"})
    db.put_book_source(buch_id, "beam", outcome=str(LinkOutcome.NOT_FOUND), url=None,
                       resolved_at=NOW, reason="")

    assert not eintraege(db)[buch_id].missing_known


def test_the_note_survives_a_dismissal(client: TestClient, db: Store) -> None:
    settings = load_settings()
    buch_id = eintrag(db, "Hardware", beam=str(LinkOutcome.NOT_FOUND))
    db.put_relation(settings.slug, buch_id, str(RelationKind.WATCHING), now=NOW,
                    note="Cyberpunk-Actioner.")

    client.post(f"/watchlist/{buch_id}/fehlt", data={"title": "Hardware"})

    assert eintraege(db)[buch_id].note == "Cyberpunk-Actioner."
