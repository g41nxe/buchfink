"""Reihe und Band aus Wikidata (ADR 45)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist.store import Store
from ebook_watchlist.wikidata import Membership, parse_membership, parse_volumes

NOW = datetime(2026, 11, 1, 12, 0)
WD = "http://www.wikidata.org/entity/"


def answer(*rows: dict) -> str:
    return json.dumps({"results": {"bindings": list(rows)}})


def row(item: str, author: str, series: str | None = None, name: str | None = None,
        ord_: str | None = None) -> dict:
    out = {"item": {"value": WD + item}, "authorLabel": {"value": author}}
    if series:
        out["series"] = {"value": WD + series}
        out["seriesLabel"] = {"value": name or ""}
    if ord_:
        out["ord"] = {"value": ord_}
    return out


def test_a_volume_of_a_series_is_found_with_its_number() -> None:
    """*Kriegsklingen* ist Band 1 der Reihe, die Wikidata „Klingenwelt“ nennt."""
    text = answer(row("Q1", "Joe Abercrombie", "Q9", "Klingenwelt", "1"))

    assert parse_membership(text, "Joe Abercrombie") == Membership("Q1", "Q9", "Klingenwelt", "1")


def test_a_book_of_the_same_world_has_no_volume() -> None:
    """*Racheklingen* steht in derselben Reihe, aber ohne Band: dieselbe Welt,
    keine Fortsetzung."""
    text = answer(row("Q2", "Joe Abercrombie", "Q9", "Klingenwelt"))

    assert parse_membership(text, "Joe Abercrombie") == Membership("Q2", "Q9", "Klingenwelt", None)


def test_another_author_is_not_taken() -> None:
    text = answer(row("Q1", "Jemand Anderes", "Q9", "Klingenwelt", "1"))

    assert parse_membership(text, "Joe Abercrombie") is None


def test_two_works_of_the_same_title_and_author_are_not_guessed_between() -> None:
    text = answer(row("Q1", "Joe Abercrombie", "Q9", "Klingenwelt", "1"),
                  row("Q3", "Joe Abercrombie"))

    assert parse_membership(text, "Joe Abercrombie") is None


def test_a_work_without_a_series_is_still_an_answer() -> None:
    assert parse_membership(answer(row("Q5", "Joe Abercrombie")), "Joe Abercrombie") \
        == Membership("Q5")


def test_the_volumes_come_in_order_with_their_german_titles() -> None:
    text = answer(
        {"item": {"value": WD + "Q12"}, "label": {"value": "Königsklingen"}, "ord": {"value": "3"}},
        {"item": {"value": WD + "Q10"}, "label": {"value": "Kriegsklingen"}, "ord": {"value": "1"}},
        {"item": {"value": WD + "Q11"}, "label": {"value": "Feuerklingen"}, "ord": {"value": "2"}},
    )

    assert parse_volumes(text) == [("1", "Kriegsklingen"), ("2", "Feuerklingen"),
                                   ("3", "Königsklingen")]


# --- im Speicher ----------------------------------------------------------------


@pytest.fixture
def db(store: Store) -> Store:
    return store


def test_a_numbered_volume_becomes_a_series_entry_below_the_dnb(db: Store) -> None:
    """Rangfolge: Leserin, DNB, Wikidata, OverDrive, Onleihe, Titel (ADR 45)."""
    db.save_wikidata("9783641068813", "Joe Abercrombie",
                     Membership("Q1", "Q9", "Klingenwelt", "1"), NOW)

    named = db.series_of(["9783641068813"])["9783641068813"]
    assert (named.name, named.volume) == ("Klingenwelt", "1")
    row = db.series_row(named.id)
    assert row is not None and row.wikidata_ref == "Q9"
    assert db.isbns_without_wikidata("test", 10) == []


def test_a_book_of_the_same_world_is_remembered_but_not_a_volume(db: Store) -> None:
    db.save_wikidata("9783453525221", "Joe Abercrombie",
                     Membership("Q2", "Q9", "Klingenwelt", None), NOW)

    assert "9783453525221" not in db.series_of(["9783453525221"])


def test_silence_is_remembered_so_nobody_asks_again(db: Store, tmp_path: Path) -> None:
    from ebook_watchlist.relations import RelationKind

    book = db.find_or_create_book(isbn="9783000000001", title="Ein Buch", author="Wer", now=NOW)
    db.put_relation("test", book.id, str(RelationKind.WATCHING), now=NOW)
    assert db.isbns_without_wikidata("test", 10) == [("9783000000001", "Ein Buch", "Wer")]

    db.save_wikidata("9783000000001", "Wer", None, NOW)

    assert db.isbns_without_wikidata("test", 10) == []


# --- im Lauf --------------------------------------------------------------------


def test_the_run_asks_wikidata_within_its_budget_and_files_what_it_hears(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist import run as run_module
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.relations import RelationKind

    store, settings = Store(paths.db_path()), load_settings()
    for n, title in enumerate(("Kriegsklingen", "Feuerklingen", "Racheklingen"), 1):
        book = store.find_or_create_book(isbn=f"978364106881{n}", title=title,
                                         author="Joe Abercrombie", now=NOW)
        store.put_relation(settings.slug, book.id, str(RelationKind.WATCHING), now=NOW)
    answers = {"Kriegsklingen": Membership("Q1", "Q9", "Klingenwelt", "1"),
               "Feuerklingen": Membership("Q2", "Q9", "Klingenwelt", "2"),
               "Racheklingen": Membership("Q3", "Q9", "Klingenwelt", None)}
    asked: list[str] = []

    class FakeWikidata:
        def __init__(self, client):
            pass

        def membership(self, title, author):
            asked.append(title)
            return answers[title]

    monkeypatch.setattr(run_module, "Wikidata", FakeWikidata)
    monkeypatch.setattr(run_module, "WIKIDATA_BUDGET", 2)

    from typing import cast

    from ebook_watchlist.http import HttpClient

    client = cast(HttpClient, None)  # die Attrappe braucht keinen
    for _ in range(3):
        run_module._ask_wikidata(store, client, settings)

    assert asked == ["Kriegsklingen", "Feuerklingen", "Racheklingen"]
    volumes = {isbn: named.volume for isbn, named in store.series_of(
        [f"978364106881{n}" for n in (1, 2, 3)]).items()}
    assert volumes == {"9783641068811": "1", "9783641068812": "2"}
