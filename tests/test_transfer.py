"""Mitnehmen, einspielen, erster Start — der Rest von #104."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from ebook_watchlist import cli, first_start, paths, transfer
from ebook_watchlist.config import load_settings
from ebook_watchlist.relations import InterestKey, RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app

NOW = datetime(2026, 10, 25, 12, 0)


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(paths.db_path())


def _themes(store: Store, slug: str) -> list[str]:
    return [r.value for r in store.interests(slug, key=str(InterestKey.GENRE_CATEGORY))]


# --- Themen auf der Profilseite ----------------------------------------------


def test_a_theme_can_be_followed_from_the_profile(data_dir: Path, store: Store) -> None:
    client = TestClient(create_app(), follow_redirects=True)
    code = "FIC031000"

    client.post("/profile/preference", data={"kind": "followed_theme", "value": code})

    assert code in _themes(store, load_settings().slug)
    assert "Thriller" in client.get("/profile").text


def test_a_theme_can_be_given_up(data_dir: Path, store: Store) -> None:
    client = TestClient(create_app(), follow_redirects=True)
    slug, code = load_settings().slug, "FIC031000"
    client.post("/profile/preference", data={"kind": "followed_theme", "value": code})

    client.post("/profile/preference",
                data={"kind": "followed_theme", "value": code, "action": "remove"})

    assert code not in _themes(store, slug)


def test_an_unknown_theme_is_refused(data_dir: Path, store: Store) -> None:
    client = TestClient(create_app(), follow_redirects=True)

    client.post("/profile/preference", data={"kind": "followed_theme", "value": "erfunden"})

    assert "erfunden" not in _themes(store, load_settings().slug)


# --- ebw export / ebw import ----------------------------------------------------


def test_export_carries_what_the_reader_set(store: Store) -> None:
    settings = load_settings()
    store.save_settings(settings.slug, {"run_every_hours": 12}, now=NOW)
    store.put_interest(settings.slug, str(InterestKey.AUTHOR), "Sebastian Fitzek", now=NOW,
                       tier="core")
    book = store.find_or_create_book(isbn=None, title="Kugelblitz", author="Cixin Liu", now=NOW)
    store.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)

    data = transfer.export(store, load_settings())

    assert data["settings"]["run_every_hours"] == 12
    assert "Sebastian Fitzek" in data["reference_authors"]["core"]
    assert {"title": "Kugelblitz", "author": "Cixin Liu"} in [
        {k: e[k] for k in ("title", "author")} for e in data["watchlist"]
    ]


def test_import_brings_it_back(
    store: Store, tmp_path: Path
) -> None:
    settings = load_settings()
    exported = {
        "settings": {"run_every_hours": 6, "home_offers": 8},
        "reference_authors": {"core": ["Sebastian Fitzek"], "extended": ["Arno Strobel"]},
        "genre_categories": ["FIC031000"],
        "watchlist": [{"title": "Kugelblitz", "author": "Cixin Liu"}],
        "owned": [{"title": "Der Schwarm", "author": "Frank Schätzing"}],
    }

    transfer.import_(store, settings, exported, now=NOW)

    after = load_settings()
    assert after.run_every_hours == 6 and after.home_offers == 8
    authors = {r.value for r in store.interests(settings.slug, key=str(InterestKey.AUTHOR))}
    assert authors == {"Sebastian Fitzek", "Arno Strobel"}
    assert _themes(store, settings.slug) == ["FIC031000"]
    watching = store.relations(settings.slug, kind=str(RelationKind.WATCHING))
    assert "Kugelblitz" in [b.title for r in watching if (b := store.book(r.book_id))]


def test_a_broken_setting_in_an_import_is_refused(store: Store) -> None:
    settings = load_settings()

    with pytest.raises(transfer.ImportError_):
        transfer.import_(store, settings, {"settings": {"deal_max_cents": "viel"}}, now=NOW)

    assert store.saved_settings(settings.slug) == {}


def test_export_and_import_on_the_command_line(store: Store, tmp_path: Path) -> None:
    target = tmp_path / "buchfink.yaml"
    store.save_settings(load_settings().slug, {"home_offers": 7}, now=NOW)

    assert cli.main(["export", str(target)]) == 0
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["settings"]["home_offers"] == 7

    data["settings"]["home_offers"] = 2
    target.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert cli.main(["import", str(target)]) == 0
    assert load_settings().home_offers == 2


# --- der allererste Start -------------------------------------------------------


def test_the_first_start_brings_the_examples(tmp_path: Path, monkeypatch) -> None:
    """Der Schnellstart braucht kein Kopieren mehr (#104)."""
    empty = tmp_path / "frisch"
    monkeypatch.setenv("EBW_DATA_DIR", str(empty))

    first_start.ensure()

    assert (empty / "settings.yaml").is_file()
    assert (empty / "seed.yaml").is_file()
    assert (empty / "watchlist.yaml").is_file()
    store = Store(paths.db_path())
    assert store.relations(load_settings().slug, kind=str(RelationKind.WATCHING))


def test_a_second_start_changes_nothing(data_dir: Path) -> None:
    before = (data_dir / "settings.yaml").read_text(encoding="utf-8")

    first_start.ensure()

    assert (data_dir / "settings.yaml").read_text(encoding="utf-8") == before
