"""Eine Zeile je Werk in Stapel und Tagesbericht (ADR 42, Schritt 3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.catalog.one_per_work import collapse
from ebook_watchlist.config import load_settings
from ebook_watchlist.models import Availability, MatchReason, Observation
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, triage

NOW = datetime(2026, 10, 26, 7, 0)
GERMAN = "9783641253486"
ENGLISH = "9781524759803"


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def found(db: Store, source: str, item_id: str, isbn: str, *, price: int | None = 399,
          availability: Availability | None = None) -> Observation:
    observation = Observation(
        source=source, source_item_id=item_id, title="Recursion", author="Blake Crouch",
        match_reason=MatchReason.GENRE_CATEGORY, price_cents=price, isbn=isbn,
        availability=availability, url=f"https://{source}.invalid/{item_id}",
        category="belletristik/krimi-thriller/psychothriller",
    )
    run_id = db.start_run("test", "cli", NOW)
    db.append(run_id, "test", [observation], NOW)
    db.finish_run(run_id, status="ok", delta_count=1, finished_at=NOW)
    return observation


def test_two_editions_of_one_work_are_one_row(db: Store) -> None:
    found(db, "beam", "b1", GERMAN)
    found(db, "overdrive", "d1", ENGLISH, price=None, availability=Availability.AVAILABLE)
    settings = replace(load_settings(), languages=("ger", "eng"))

    pile = triage.pending(db, settings, limit=50)

    rows = [item for item in pile.items if item.title == "Recursion"]
    assert len(rows) == 1
    assert rows[0].isbn == GERMAN  # erste Lesesprache vor „ausleihbar“
    assert rows[0].also and "englisch" in rows[0].also[0]


def test_the_first_reading_language_decides(db: Store) -> None:
    found(db, "beam", "b1", GERMAN)
    found(db, "overdrive", "d1", ENGLISH, price=None, availability=Availability.AVAILABLE)
    settings = replace(load_settings(), languages=("eng", "ger"))

    pile = triage.pending(db, settings, limit=50)

    (row,) = [item for item in pile.items if item.title == "Recursion"]
    assert row.isbn == ENGLISH


def test_the_row_says_where_else_it_is(data_dir: Path, db: Store) -> None:
    found(db, "beam", "b1", GERMAN)
    found(db, "overdrive", "d1", ENGLISH)
    db.save_settings(load_settings().slug, {"languages": ["ger", "eng"]}, now=NOW)

    body = TestClient(create_app()).get("/suggestions").text

    assert body.count('name="shown"') == 1
    assert "auch als" in body and "englisch" in body


def test_collapse_keeps_what_has_no_work() -> None:
    items = ["a", "b"]

    kept = collapse(items, isbn_of=lambda i: None, siblings={}, language_of=lambda i: None,
                    languages=("ger",), cost=lambda i: (0,))

    assert [winner for winner, _ in kept] == ["a", "b"]


def test_collapse_ranks_language_then_cost() -> None:
    items = [("x1", "eng", 1), ("x2", "ger", 5), ("x3", "ger", 2)]
    siblings = {"x1": {"x1", "x2", "x3"}, "x2": {"x1", "x2", "x3"}, "x3": {"x1", "x2", "x3"}}

    ((winner, others),) = collapse(
        items, isbn_of=lambda i: i[0], siblings=siblings, language_of=lambda i: i[1],
        languages=("ger", "eng"), cost=lambda i: (i[2],),
    )

    assert winner[0] == "x3"
    assert [o[0] for o in others] == ["x2", "x1"]


def test_the_digest_reports_a_work_once(db: Store) -> None:
    from ebook_watchlist.models import Delta, DeltaKind
    from ebook_watchlist.run import _one_per_work

    german = found(db, "beam", "b1", GERMAN)
    english = found(db, "overdrive", "d1", ENGLISH)
    watched = replace(english, match_reason=MatchReason.WATCHLIST, source_item_id="w1")
    deltas = [Delta(kind=DeltaKind.FIRST_SEEN, current=o, previous=None)
              for o in (english, german, watched)]

    kept = _one_per_work(db, replace(load_settings(), languages=("ger", "eng")), deltas)

    assert [d.current.source_item_id for d in kept] == ["b1", "w1"]
