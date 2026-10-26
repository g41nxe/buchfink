"""Eine Seite je Werk, mit allen Ausgaben und Quellen (#111, ADR 42)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.models import Availability, MatchReason, Observation
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 10, 26, 7, 0)
ISBN = "9783442492817"


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), follow_redirects=False)


def seen(db: Store, source: str, item_id: str, *, isbn: str | None = ISBN,
         title: str = "Gestohlene Erinnerung", author: str = "Blake Crouch",
         price: int | None = 499, availability: Availability | None = None) -> Observation:
    observation = Observation(
        source=source, source_item_id=item_id, title=title, author=author,
        match_reason=MatchReason.GENRE_CATEGORY, price_cents=price, isbn=isbn,
        availability=availability, url=f"https://{source}.invalid/{item_id}",
    )
    run_id = db.start_run("test", "cli", NOW)
    db.append(run_id, "test", [observation], NOW)
    db.finish_run(run_id, status="ok", delta_count=1, finished_at=NOW)
    return observation


def test_a_find_is_one_page_with_every_source(client: TestClient, db: Store) -> None:
    """Dieselbe Ausgabe bei beam und in der Onleihe: eine Seite, beide Kacheln."""
    seen(db, "beam", "b1", price=499)
    seen(db, "onleihe", "o1", price=None, availability=Availability.AVAILABLE)

    body = client.get(f"/work/{ISBN}").text

    assert "Gestohlene Erinnerung" in body
    section = body.split("data-editions", 1)[1]
    assert "beam.invalid/b1" in section and "onleihe.invalid/o1" in section


def test_other_editions_of_the_work_stand_there_too(client: TestClient, db: Store) -> None:
    """Zwei ISBNs, ein Werk (gleiche Autor:in, gleicher Titel)."""
    seen(db, "beam", "b1")
    seen(db, "overdrive", "d1", isbn="9783442492824", price=None,
         availability=Availability.AVAILABLE)

    section = client.get(f"/work/{ISBN}").text.split("data-editions", 1)[1]

    assert "9783442492824" in section
    assert "overdrive.invalid/d1" in section


def test_the_named_edition_comes_first(client: TestClient, db: Store) -> None:
    seen(db, "beam", "b1")
    seen(db, "overdrive", "d1", isbn="9783442492824")

    section = client.get("/work/9783442492824").text.split("data-editions", 1)[1]

    assert section.index("9783442492824") < section.index(ISBN)


def test_a_lone_find_needs_no_editions_section(client: TestClient, db: Store) -> None:
    seen(db, "beam", "b1")

    assert "data-editions" not in client.get(f"/work/{ISBN}").text


def test_the_old_addresses_lead_to_the_work(client: TestClient, db: Store) -> None:
    seen(db, "beam", "b1")

    response = client.get("/discovery/beam/b1")

    assert response.status_code == 301
    assert response.headers["location"] == f"/work/{ISBN}"


def test_a_book_with_an_isbn_leads_to_its_work(client: TestClient, db: Store) -> None:
    seen(db, "beam", "b1")
    book = db.find_or_create_book(isbn=ISBN, title="Gestohlene Erinnerung",
                                  author="Blake Crouch", now=NOW)
    db.put_relation(load_settings().slug, book.id, str(RelationKind.WATCHING), now=NOW)

    response = client.get(f"/book/{book.id}")

    assert response.status_code == 301
    assert response.headers["location"] == f"/work/{ISBN}"
    # Und dort steht die Buchseite, mit ihren Beziehungen.
    page = client.get(f"/work/{ISBN}").text
    assert f"/book/{book.id}/" in page


def test_a_book_without_an_isbn_keeps_its_address(client: TestClient, db: Store) -> None:
    book = db.find_or_create_book(isbn=None, title="Ohne Nummer", author="A", now=NOW)
    db.put_relation(load_settings().slug, book.id, str(RelationKind.WATCHING), now=NOW)

    assert client.get(f"/book/{book.id}").status_code == 200


def test_a_find_without_an_isbn_is_named_by_source_and_number(
    client: TestClient, db: Store
) -> None:
    seen(db, "beam", "x9", isbn=None, title="Ein Sammelband")

    assert client.get("/discovery/beam/x9").status_code == 200
    assert "Ein Sammelband" in client.get("/work/beam:x9").text


def test_an_unknown_edition_is_not_found(client: TestClient) -> None:
    assert client.get("/work/9780000000000").status_code == 404
