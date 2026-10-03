"""Das Werk in der Oberfläche: Stapel und Watchlist (ADR 36, #80)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.dnb import Record
from ebook_watchlist.models import Availability, MatchReason, Observation
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 10, 3, 12, 0)
GERMAN = "9783641253486"
ENGLISH = "9781524759803"


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def recursion(db: Store) -> None:
    """Die deutsche Ausgabe als Fund in der Bibliothek, das Original als Buch."""
    slug = load_settings().slug
    db.append(db.start_run(slug, "cli", NOW), slug, [
        Observation(source="onleihe", source_item_id="53486", title="Gestohlene Erinnerung",
                    author="Blake Crouch", isbn=GERMAN, availability=Availability.AVAILABLE,
                    match_reason=MatchReason.PROFILE_AUTHOR, observed_at=datetime.now()),
        Observation(source="overdrive", source_item_id="59803", title="Recursion",
                    author="Blake Crouch", isbn=ENGLISH, match_reason=MatchReason.WATCHLIST,
                    observed_at=datetime.now()),
    ], NOW)
    db.save_dnb(GERMAN, Record(title="Gestohlene Erinnerung", author="Crouch, Blake",
                               original_title="Recursion"), NOW)


def english_book(db: Store, kind: RelationKind) -> int:
    book = db.find_or_create_book(isbn=ENGLISH, title="Recursion", author="Blake Crouch",
                                  now=NOW)
    db.put_relation(load_settings().slug, book.id, str(kind), now=NOW)
    return book.id


def test_the_pile_does_not_offer_a_work_she_owns(client: TestClient, db: Store) -> None:
    """Keine Übersetzung eines Buchs, das sie schon kennt."""
    recursion(db)
    assert "Gestohlene Erinnerung" in client.get("/suggestions").text

    english_book(db, RelationKind.OWNED)

    assert "Gestohlene Erinnerung" not in client.get("/suggestions").text


def test_a_work_she_only_watches_is_still_offered(client: TestClient, db: Store) -> None:
    recursion(db)
    english_book(db, RelationKind.WATCHING)

    assert "Gestohlene Erinnerung" in client.get("/suggestions").text


def test_the_watchlist_says_she_has_it_already(client: TestClient, db: Store) -> None:
    """Beobachtet sie das Original und hat die Übersetzung, bleibt die Zeile —
    sie sagt nur, was sie schon hat."""
    recursion(db)
    english_book(db, RelationKind.OWNED)
    german = db.find_or_create_book(isbn=GERMAN, title="Gestohlene Erinnerung",
                                    author="Blake Crouch", now=NOW)
    db.put_relation(load_settings().slug, german.id, str(RelationKind.WATCHING), now=NOW)

    body = client.get("/watchlist").text

    assert "Gestohlene Erinnerung" in body
    assert "hast du schon als" in body and "Recursion" in body
