"""Was auf der Startseite „jetzt zu haben“ ist, bekommt im Lauf seinen
Steckbrief (28.10.2026).

Der Lauf beschrieb nur Funde; ein Watchlist-Titel bekam Sterne erst über den
Hammer. Gerade beim Schnäppchen will man aber wissen, ob es sich lohnt.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from conftest import give_profile
from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.run import describe_offers
from ebook_watchlist.store import Store
from test_web_home import seen

NOW = datetime(2026, 10, 28, 22, 0)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def _sisters(db):
    return next(b for b in db.books() if b.title == "Die sieben Schwestern")


def test_an_offer_without_a_portrait_is_described(db) -> None:
    give_profile(db)
    sisters = _sisters(db)
    seen(db, sisters.id, price=399, available=True)
    asked: list[int] = []

    described = describe_offers(db, load_settings(), budget=5, now=NOW,
                                portray=lambda s, st, book_id, now: asked.append(book_id) or "")

    assert asked == [sisters.id]
    assert described == 1


def test_no_budget_no_description(db) -> None:
    give_profile(db)
    seen(db, _sisters(db).id, price=399, available=True)
    asked: list[int] = []

    describe_offers(db, load_settings(), budget=0, now=NOW,
                    portray=lambda s, st, book_id, now: asked.append(book_id) or "")

    assert asked == []


def test_without_a_profile_nothing_is_described(db) -> None:
    seen(db, _sisters(db).id, price=399, available=True)
    asked: list[int] = []

    describe_offers(db, load_settings(), budget=5, now=NOW,
                    portray=lambda s, st, book_id, now: asked.append(book_id) or "")

    assert asked == []


def test_a_title_that_is_no_offer_is_left_alone(db) -> None:
    give_profile(db)
    seen(db, _sisters(db).id, price=2999, available=False)
    asked: list[int] = []

    describe_offers(db, load_settings(), budget=5, now=NOW,
                    portray=lambda s, st, book_id, now: asked.append(book_id) or "")

    assert asked == []
