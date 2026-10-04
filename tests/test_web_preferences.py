"""Genres und Autor:innen auf der Profilseite ändern (ADR 37, #91)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.facets import ReadingProfile
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 10, 4, 12, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def change(client: TestClient, kind: str, value: str, action: str = "add") -> str:
    return client.post("/profile/preference",
                       data={"kind": kind, "value": value, "action": action}).text


def test_a_genre_can_be_disliked_and_taken_back_on_the_profile_page(
    client: TestClient, db: Store
) -> None:
    db.put_reading_profile(load_settings().slug, ReadingProfile((), ()), cause="t", now=NOW)

    body = change(client, "disliked_genre", "FIC027000")

    profile = db.reading_profile(load_settings().slug)
    assert profile.disliked_genres == ("FIC027000",)
    assert "Liebesroman" in body

    change(client, "disliked_genre", "FIC027000", action="remove")
    assert db.reading_profile(load_settings().slug).disliked_genres == ()


def test_a_genre_off_the_list_is_refused(client: TestClient, db: Store) -> None:
    db.put_reading_profile(load_settings().slug, ReadingProfile((), ()), cause="t", now=NOW)

    change(client, "liked_genre", "FIC999999")

    assert db.reading_profile(load_settings().slug).liked_genres == ()


def test_a_liked_author_becomes_a_weekly_discovery_channel(client: TestClient, db: Store) -> None:
    change(client, "liked_author", "Chris Carter")

    (row,) = [r for r in db.interests(load_settings().slug, key="author")
              if r.value == "Chris Carter"]
    assert json.loads(row.details)["tier"] == "extended"

    change(client, "liked_author", "Chris Carter", action="remove")
    assert "Chris Carter" not in {r.value for r in db.interests(load_settings().slug, key="author")}


def test_a_disliked_author_lands_in_the_profile(client: TestClient, db: Store) -> None:
    body = change(client, "disliked_author", "Rosamunde Pilcher")

    assert db.reading_profile(load_settings().slug).disliked_authors == ("Rosamunde Pilcher",)
    assert "Rosamunde Pilcher" in body


def test_the_profile_page_offers_the_genre_list(client: TestClient) -> None:
    body = client.get("/profile").text

    assert 'action="/profile/preference"' in body
    assert '<option value="FIC031080">' in body
