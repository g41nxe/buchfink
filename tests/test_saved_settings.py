"""Einstellungen in der Datenbank, änderbar auf der Übersicht (#100, #104)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import ConfigError, load_settings
from ebook_watchlist.run import EXIT_OK, main
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 10, 25, 12, 0)


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(paths.db_path())


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


def test_a_saved_setting_wins_over_the_file(store: Store) -> None:
    """Die Datei ist nur noch der Startwert (#104)."""
    slug = load_settings().slug
    store.save_settings(slug, {"run_every_hours": 6, "home_offers": 9}, now=NOW)

    settings = load_settings()

    assert settings.run_every_hours == 6
    assert settings.home_offers == 9


def test_without_anything_saved_the_file_still_counts(store: Store) -> None:
    assert load_settings().home_suggestions == 3


def test_the_cadence_is_a_day_by_default(tmp_path: Path) -> None:
    """24 Stunden (#100): der Dienst misst ab dem Beginn des letzten fertigen
    Laufs, also rutscht nichts mehr nach hinten."""
    path = tmp_path / "settings.yaml"
    path.write_text("slug: t\nname: T\nsources: {fake: {fixture: f.yaml}}\n", encoding="utf-8")

    assert load_settings(path).run_every_hours == 24


def test_the_overview_offers_the_settings(client: TestClient) -> None:
    body = client.get("/overview").text

    assert 'name="run_every_hours"' in body
    assert 'name="public_url"' in body
    assert "Lauf alle" in body


def test_saving_the_form_changes_what_counts(client: TestClient) -> None:
    response = client.post(
        "/settings",
        data={"run_every_hours": "12", "home_offers": "4", "home_suggestions": "2",
              "suggestions_shown": "30", "strong_deal_max_cents": "3,99",
              "deal_max_cents": "8", "min_discount_pct": "30", "rating_budget": "20",
              "dnb_budget": "50", "public_url": "http://192.168.178.20:8437"},
    )

    assert response.status_code == 200
    settings = load_settings()
    assert settings.run_every_hours == 12
    assert settings.strong_deal_max_cents == 399
    assert settings.deal_max_cents == 800
    assert settings.suggestions_shown == 30
    assert settings.public_url == "http://192.168.178.20:8437"
    assert "gespeichert" in response.text


def test_a_broken_value_is_refused_and_nothing_changes(client: TestClient) -> None:
    before = load_settings()

    response = client.post(
        "/settings",
        data={"run_every_hours": "12", "strong_deal_max_cents": "20", "deal_max_cents": "5"},
    )

    assert response.status_code == 400
    assert load_settings().run_every_hours == before.run_every_hours
    assert load_settings().deal_max_cents == before.deal_max_cents


def test_an_empty_address_means_no_link(client: TestClient) -> None:
    client.post("/settings", data={"public_url": ""})

    assert load_settings().public_url is None


def test_the_address_must_be_a_web_address(store: Store) -> None:
    store.save_settings(load_settings().slug, {"public_url": "buchfink"}, now=NOW)

    with pytest.raises(ConfigError):
        load_settings()


# --- ebw run --wenn-faellig ----------------------------------------------------


def test_when_due_runs_only_when_the_cadence_says_so(data_dir: Path, store: Store) -> None:
    slug = load_settings().slug
    earlier = datetime.now() - timedelta(hours=2)
    store.finish_run(store.start_run(slug, "cron", earlier), status="ok", delta_count=0,
                     finished_at=earlier)
    before = len(store.recent_runs(slug))

    assert main(["run", "--wenn-faellig"]) == EXIT_OK
    assert len(store.recent_runs(slug)) == before

    store.save_settings(slug, {"run_every_hours": 1}, now=NOW)

    assert main(["run", "--wenn-faellig"]) == EXIT_OK
    assert len(store.recent_runs(slug)) == before + 1
