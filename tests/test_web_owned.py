"""Meine Bücher: alles, was die Leserin als *Hab ich* führt (#71)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 9, 26, 12, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def owned(db: Store, title: str, author: str, *, when: datetime = NOW) -> int:
    book = db.find_or_create_book(isbn=None, title=title, author=author, now=when)
    db.put_relation("test", book.id, str(RelationKind.OWNED), now=when)
    return book.id


def test_the_page_lists_what_she_owns_and_nothing_else(client, db) -> None:
    b = owned(db, "Leopard", "Jo Nesbø")
    observed = db.books()[0]

    body = client.get("/owned").text

    assert "Meine Bücher" in body
    assert f'href="/book/{b}"' in body and "Leopard" in body
    assert f'href="/book/{observed.id}"' not in body


def test_what_is_marked_on_the_watchlist_appears_and_undo_takes_it_away(client, db) -> None:
    book = db.books()[0]

    client.post(f"/watchlist/{book.id}/finish", data={"kind": str(RelationKind.OWNED)})
    assert f'href="/book/{book.id}"' in client.get("/owned").text

    client.post("/watchlist/undo",
                data={"book_id": str(book.id), "kind": str(RelationKind.OWNED)})
    assert f'href="/book/{book.id}"' not in client.get("/owned").text


def test_the_list_sorts_by_title_by_default_and_by_author_on_request(client, db) -> None:
    owned(db, "Zebra", "Anna A")
    owned(db, "Apfel", "Zoe Z")

    by_title = client.get("/owned").text
    by_author = client.get("/owned?sortiert=autor").text

    assert by_title.index("Apfel") < by_title.index("Zebra")
    assert by_author.index("Zebra") < by_author.index("Apfel")


def test_the_newest_mark_comes_first_on_request(client, db) -> None:
    owned(db, "Alt", "A", when=datetime(2026, 1, 1))
    owned(db, "Neu", "B", when=datetime(2026, 9, 1))

    body = client.get("/owned?sortiert=neu").text

    assert body.index("Neu") < body.index("Alt")


def test_each_row_can_be_found_by_the_search(client, db) -> None:
    owned(db, "Leopard", "Jo Nesbø")

    body = client.get("/owned").text

    assert 'data-search="leopard jo nesbø"' in body
    assert 'x-model="query"' in body


def test_her_own_stars_stand_in_the_row(client, db) -> None:
    b = owned(db, "Leopard", "Jo Nesbø")
    from ebook_watchlist.ratings import BY_READER, book_subject

    db.put_rating(book_subject(b), stars=4, confidence="belegt", reason="",
                  profile_version=0, now=NOW, origin=BY_READER)

    body = client.get("/owned").text

    assert 'aria-label="deine Sterne: 4 von 5"' in body


def test_the_profile_page_leads_to_the_whole_list(client, db) -> None:
    owned(db, "Leopard", "Jo Nesbø")

    assert 'href="/owned"' in client.get("/profile").text


def test_without_owned_books_the_page_says_so(client) -> None:
    assert "Noch kein Buch als „Hab ich“ vermerkt." in client.get("/owned").text
