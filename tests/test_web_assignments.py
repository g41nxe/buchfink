"""Unklare Zuordnungen entscheiden — auf der Watchlist (Ticket 41).

Der Bestätigungsweg ist der Regelfall für schwierige Titel, nicht der
Notausgang — nur gab es dafür keine Stelle: die Vorlage war schon eine
Radio-Liste, hatte aber genau eine Option.

Entschieden wird in der Zeile, nicht auf einer eigenen Seite: der Titel, wie
die Leserin ihn geschrieben hat, steht dann direkt darüber.
"""

from __future__ import annotations

import json
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

NOW = datetime(2026, 9, 6, 12, 0)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


def unsure(db: Store, *candidates: tuple[str, str]) -> int:
    """Ein beobachtetes Buch mit einer unsicheren Zuordnung."""
    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Red Rising", author="Pierce Brown", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(
        book.id,
        "beam",
        outcome=str(LinkOutcome.UNSURE),
        url=None,
        resolved_at=NOW,
        reason="zwei Kandidaten sind gleich gut",
        candidates=[
            {"title": title, "author": "Brown, Pierce", "url": url, "cover_url": None}
            for title, url in candidates
        ],
    )
    return book.id


def test_every_candidate_is_offered_not_just_the_winner(client: TestClient, db: Store) -> None:
    """Der Befund, der das Ticket ausgelöst hat: gespeichert wurde nur der
    Sieger, obwohl `Resolution.ranked` die übrigen kannte."""
    unsure(db, ("Red Rising", "https://beam.invalid/1"), ("Red Rising - Asche", "https://beam.invalid/2"))

    body = client.get("/watchlist?only=unsure").text

    assert "Red Rising - Asche" in body
    # Ein Formular je Eintrag, eine Karte je Kandidat.
    assert body.count('class="pick"') == 2


def test_confirming_says_a_human_decided(client: TestClient, db: Store) -> None:
    """`confirmed` statt `linked` — das ist der ganze Unterschied (ADR 9)."""
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))

    client.post(
        f"/watchlist/{book_id}/assign",
        data={"source": "beam", "url": "https://beam.invalid/1", "action": "confirm"},
    )

    row = db.get_book_source(book_id, "beam")
    assert row is not None
    assert row.url == "https://beam.invalid/1"
    assert json.loads(row.details)["outcome"] == str(LinkOutcome.CONFIRMED)


def test_none_of_them_rejects_the_whole_group(client: TestClient, db: Store) -> None:
    book_id = unsure(
        db, ("Red Rising", "https://beam.invalid/1"), ("Falsch", "https://beam.invalid/2")
    )

    client.post(
        f"/watchlist/{book_id}/assign",
        data={"source": "beam", "action": "none"},
    )

    # „Keiner davon" trifft die ganze gezeigte Gruppe: einen einzelnen
    # abzulehnen gibt es nicht mehr (Ticket 41).
    assert not any(e.needs_choice for e in watchlist.entries(db, load_settings()))
    entry = next(e for e in watchlist.entries(db, load_settings()) if e.book_id == book_id)
    assert len(entry.rejected) == 2


def test_a_rejection_can_be_taken_back(client: TestClient, db: Store) -> None:
    """Ein Irrtum beim Wegklicken darf nicht dauerhaft sein (ADR 18)."""
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))
    db.reject_candidates(book_id, "beam", ["https://beam.invalid/1"])

    client.post(
        f"/watchlist/{book_id}/assign",
        data={"source": "beam", "action": "restore"},
    )

    entry = next(e for e in watchlist.entries(db, load_settings()) if e.needs_choice)
    assert not entry.rejected
    assert len(entry.candidates) == 1


def test_rejecting_twice_records_it_once(db: Store) -> None:
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))

    db.reject_candidates(book_id, "beam", ["https://beam.invalid/1"])
    db.reject_candidates(book_id, "beam", ["https://beam.invalid/1"])

    row = db.get_book_source(book_id, "beam")
    assert json.loads(row.details)["rejected"] == ["https://beam.invalid/1"]


def test_a_book_no_longer_watched_is_no_longer_a_question(db: Store) -> None:
    """Eine unklare Zuordnung zu einem Buch, das niemand mehr beobachtet, ist
    keine Frage an die Leserin."""
    settings = load_settings()
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))
    db.deactivate_relation(settings.slug, book_id, str(RelationKind.WATCHING), now=NOW)

    assert not any(e.needs_choice for e in watchlist.entries(db, settings))


def test_an_empty_pile_says_so(client: TestClient, db: Store) -> None:
    assert "Nichts offen" in client.get("/watchlist?only=unsure").text


def test_a_bundle_candidate_is_marked_as_one(client: TestClient, db: Store) -> None:
    """Ohne das Abzeichen sieht „Titel A / Titel B" aus wie eine
    Schreibvariante, nicht wie zwei Bücher (ADR 24)."""
    unsure(
        db,
        ("Der Kruzifix-Killer", "https://beam.invalid/1"),
        ("Der Kruzifix-Killer / Der Vollstrecker", "https://beam.invalid/2"),
    )

    body = client.get("/watchlist?only=unsure").text

    assert "2 Bände" in body


def test_an_old_row_without_a_candidate_list_still_asks(client: TestClient, db: Store) -> None:
    """Zeilen aus der Zeit vor der Kandidatenliste tragen nur den Sieger. Ohne
    Rückfall hörten sie stillschweigend auf zu fragen — der teuerste denkbare
    Weg, eine Entscheidung zu verlieren."""
    settings = load_settings()
    book = db.find_or_create_book(isbn=None, title="Red Rising", author="Pierce Brown", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(
        book.id,
        "beam",
        outcome=str(LinkOutcome.UNSURE),
        url="https://beam.invalid/alt",
        resolved_at=NOW,
        matched_title="Red Rising - Asche zu Asche",
        matched_author="Brown, Pierce",
        reason="zwei Kandidaten sind gleich gut",
    )

    body = client.get("/watchlist?only=unsure").text

    assert "Red Rising - Asche zu Asche" in body
    assert "https://beam.invalid/alt" in body


def test_a_paused_entry_asks_nothing(db: Store) -> None:
    """Pausiert heißt: wird nicht mehr geprüft. Dann ist die Zuordnung auch
    keine offene Frage."""
    settings = load_settings()
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))
    db.deactivate_relation(settings.slug, book_id, str(RelationKind.WATCHING), now=NOW)

    entry = next(e for e in watchlist.entries(db, settings) if e.book_id == book_id)
    assert entry.candidates
    assert not entry.needs_choice


def test_confirming_returns_to_the_list_you_came_from(client: TestClient, db: Store) -> None:
    """Vorher stand hier fest `?nur=unklar`: wer aus der vollen Liste heraus
    bestätigte, landete in der gefilterten und sah seinen Eintrag nicht mehr."""
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))

    response = client.post(
        f"/watchlist/{book_id}/assign",
        data={"source": "beam", "url": "https://beam.invalid/1", "action": "confirm",
              "back": "/watchlist"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/watchlist"


def test_a_smuggled_destination_is_ignored(client: TestClient, db: Store) -> None:
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))

    response = client.post(
        f"/watchlist/{book_id}/assign",
        data={"source": "beam", "action": "none", "back": "https://woanders.invalid"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/watchlist"


def test_the_book_inherits_the_cover_of_the_chosen_edition(
    client: TestClient, db: Store, data_dir: Path
) -> None:
    """Das Bild lag schon da — die Kandidatenkarte hat es gezeigt. Ohne diesen
    Schritt stand die Zeile bis zum nächsten Lauf mit einem Platzhalter."""
    from ebook_watchlist.covers import CoverStore, file_name

    settings = load_settings()
    image = "https://beam.invalid/cover.jpg"
    covers = CoverStore(paths.covers_dir())
    covers.directory.mkdir(parents=True, exist_ok=True)
    covers.path(file_name(image)).write_bytes(b"x" * 5000)

    book = db.find_or_create_book(isbn=None, title="Dark Matter", author="Crouch", now=NOW)
    db.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.UNSURE), url=None, resolved_at=NOW,
        reason="unklar",
        candidates=[{"title": "Der Zeitenläufer", "author": "Crouch",
                     "url": "https://beam.invalid/1", "cover_url": image}],
    )

    client.post(
        f"/watchlist/{book.id}/assign",
        data={"source": "beam", "url": "https://beam.invalid/1", "action": "confirm"},
    )

    assert db.book(book.id).cover_file == file_name(image)


def test_the_last_decision_does_not_land_on_an_empty_filter(
    client: TestClient, db: Store
) -> None:
    """Der Filter ist zum Abarbeiten da. War es die letzte Frage, fuehrt er in
    eine leere Liste — kein Fehler, aber eine Sackgasse."""
    book_id = unsure(db, ("Red Rising", "https://beam.invalid/1"))

    response = client.post(
        f"/watchlist/{book_id}/assign",
        data={"source": "beam", "action": "none", "back": "/watchlist?only=unsure"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/watchlist"


def test_an_old_way_back_leads_to_the_new_filter(client: TestClient, db: Store) -> None:
    """Eine Seite, die noch mit `?nur=unklar` offen war, schickt den alten
    Rücksprung (#70)."""
    settings = load_settings()
    first = unsure(db, ("Red Rising", "https://beam.invalid/1"))
    second = db.find_or_create_book(isbn=None, title="Noch eins", author="Wer", now=NOW)
    db.put_relation(settings.slug, second.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(
        second.id, "beam", outcome=str(LinkOutcome.UNSURE), url=None, resolved_at=NOW,
        reason="unklar",
        candidates=[{"title": "Noch eins", "author": "Wer", "url": "https://x/9",
                     "cover_url": None}],
    )

    response = client.post(
        f"/watchlist/{first}/assign",
        data={"source": "beam", "action": "none", "back": "/watchlist?nur=unklar"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/watchlist?only=unsure"


def test_while_something_is_open_the_filter_holds(client: TestClient, db: Store) -> None:
    settings = load_settings()
    first = unsure(db, ("Red Rising", "https://beam.invalid/1"))
    second = db.find_or_create_book(isbn=None, title="Noch eins", author="Wer", now=NOW)
    db.put_relation(settings.slug, second.id, str(RelationKind.WATCHING), now=NOW)
    db.put_book_source(
        second.id, "beam", outcome=str(LinkOutcome.UNSURE), url=None, resolved_at=NOW,
        reason="unklar",
        candidates=[{"title": "Noch eins", "author": "Wer", "url": "https://x/9",
                     "cover_url": None}],
    )

    response = client.post(
        f"/watchlist/{first}/assign",
        data={"source": "beam", "action": "none", "back": "/watchlist?only=unsure"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/watchlist?only=unsure"
