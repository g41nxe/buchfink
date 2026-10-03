"""Die Reihe in der Oberfläche: „Reihe · Band n", beobachten, filtern (#85)."""

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

NOW = datetime(2026, 10, 3, 12, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def volume(isbn: str, title: str, number: str) -> Observation:
    return Observation(source="overdrive", source_item_id=isbn[-4:], title=title,
                       author="Pierce Brown", isbn=isbn, series="Red Rising Saga",
                       series_index=number, series_ref="532674",
                       availability=Availability.AVAILABLE,
                       match_reason=MatchReason.GENRE_CATEGORY, observed_at=datetime.now())


def red_rising(db: Store) -> int:
    slug = load_settings().slug
    db.append(db.start_run(slug, "cli", NOW), slug, [
        volume("9783000000101", "Red Rising", "1"),
        volume("9783000000102", "Golden Son", "2"),
        volume("9783000000103", "Morning Star", "3"),
    ], NOW)
    return next(r.id for r in db.series_rows() if r.key == "red rising")


def watch_book(db: Store, isbn: str, title: str) -> int:
    book = db.find_or_create_book(isbn=isbn, title=title, author="Pierce Brown", now=NOW)
    db.put_relation(load_settings().slug, book.id, str(RelationKind.WATCHING), now=NOW)
    return book.id


def test_the_watchlist_names_series_and_volume(client: TestClient, db: Store) -> None:
    red_rising(db)
    watch_book(db, "9783000000101", "Red Rising")

    assert "Red Rising Saga · Band 1" in client.get("/watchlist").text


def test_the_watchlist_filters_by_series(client: TestClient, db: Store) -> None:
    series_id = red_rising(db)
    watch_book(db, "9783000000101", "Red Rising")

    everything = client.get("/watchlist").text
    only = client.get(f"/watchlist?series={series_id}").text

    assert "Die sieben Schwestern" in everything
    assert f'<option value="{series_id}"' in everything
    assert "Red Rising" in only
    assert "Die sieben Schwestern" not in only


def test_the_book_page_offers_to_watch_its_series(client: TestClient, db: Store) -> None:
    series_id = red_rising(db)
    book_id = watch_book(db, "9783000000101", "Red Rising")

    page = client.get(f"/book/{book_id}").text
    assert "Red Rising Saga · Band 1" in page
    assert f'action="/series/{series_id}/watch"' in page
    assert "Reihe beobachten" in page

    after = client.post(f"/series/{series_id}/watch",
                        data={"watch": "1", "back": f"/book/{book_id}"}).text

    assert "Nicht mehr beobachten" in after
    titles = {b.title for b in db.books()}
    assert {"Golden Son", "Morning Star"} <= titles
    assert "Golden Son" in client.get("/watchlist").text


def test_unwatching_from_the_book_page(client: TestClient, db: Store) -> None:
    series_id = red_rising(db)
    book_id = watch_book(db, "9783000000101", "Red Rising")
    client.post(f"/series/{series_id}/watch", data={"watch": "1", "back": f"/book/{book_id}"})

    client.post(f"/series/{series_id}/watch", data={"watch": "0", "back": f"/book/{book_id}"})

    body = client.get("/watchlist").text
    assert "Golden Son" not in body
    assert "Red Rising Saga · Band 1" in body


def test_the_suggestion_pile_names_the_series(client: TestClient, db: Store) -> None:
    red_rising(db)

    assert "Red Rising Saga · Band 1" in client.get("/suggestions").text


def test_the_owned_list_names_series_and_volume(client: TestClient, db: Store) -> None:
    red_rising(db)
    book = db.find_or_create_book(isbn="9783000000102", title="Golden Son",
                                  author="Pierce Brown", now=NOW)
    db.put_relation(load_settings().slug, book.id, str(RelationKind.OWNED), now=NOW)

    assert "Red Rising Saga · Band 2" in client.get("/owned").text
