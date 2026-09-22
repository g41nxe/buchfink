"""Nur Funde in den Sprachen des Profils (#10).

Kein Test hier geht ins Netz.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.dnb import Record
from ebook_watchlist.language import is_foreign, language_finder
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 19, 12, 0)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def fund(isbn: str | None, grund: MatchReason = MatchReason.GENRE_CATEGORY) -> Observation:
    return Observation(source="beam", source_item_id=isbn or "x", title="Ein Buch",
                       match_reason=grund, isbn=isbn)


def test_a_find_in_another_language_is_foreign(db: Store) -> None:
    db.save_dnb("9780000000001", Record(title="A Book", language="eng"), NOW)

    assert is_foreign(fund("9780000000001"), load_settings(), language_finder(db))


def test_a_german_find_is_not(db: Store) -> None:
    db.save_dnb("9783000000001", Record(title="Ein Buch", language="ger"), NOW)

    assert not is_foreign(fund("9783000000001"), load_settings(), language_finder(db))


@pytest.mark.parametrize("wie", ["ohne ISBN", "nie gefragt", "DNB kennt es nicht",
                                 "ohne Sprachangabe"])
def test_unknown_is_never_foreign(db: Store, wie: str) -> None:
    """Viele Selbstverlagstitel haben keine ISBN, und die DNB kennt nicht
    alles. Unbekannt darf nie heissen: fremd.

    Die Nummer gehoert zur Gruppe 992, die in keiner Tabelle steht: seit #32
    spraeche sonst die ISBN selbst, und der Fall waere keiner mehr."""
    isbn = None if wie == "ohne ISBN" else "9789920000002"
    if wie == "DNB kennt es nicht":
        db.save_dnb("9789920000002", None, NOW)
    if wie == "ohne Sprachangabe":
        db.save_dnb("9789920000002", Record(title="A Book"), NOW)

    assert not is_foreign(fund(isbn), load_settings(), language_finder(db))


def test_a_watchlist_title_is_never_foreign(db: Store) -> None:
    """Was die Leserin selbst auf die Liste setzt, bleibt dort."""
    db.save_dnb("9780000000001", Record(title="A Book", language="eng"), NOW)

    assert not is_foreign(fund("9780000000001", MatchReason.WATCHLIST), load_settings(),
                          language_finder(db))


@pytest.mark.parametrize("code", ["und", "mul", "zxx", "mis"])
def test_the_codes_for_unknown_are_not_foreign(db: Store, code: str) -> None:
    """ISO 639-2 hat Codes fuer "unbestimmt", "mehrere", "ohne Sprache" und
    "nicht erfasst". Keiner sagt, dass das Buch *nicht* deutsch ist — eine
    zweisprachige Ausgabe traegt ``mul``."""
    db.save_dnb("9780000000003", Record(title="Zweisprachig", language=code), NOW)

    assert not is_foreign(fund("9780000000003"), load_settings(), language_finder(db))


# --- die Registrierungsgruppe der ISBN (#32) --------------------------------


def test_a_hungarian_isbn_is_foreign_even_without_a_dnb_record(db: Store) -> None:
    """Der Fall, der das Ticket ausgeloest hat: *Wayward Pines* mit ungarischem
    Klappentext. Die DNB kennt die Nummer nicht — sie erfasst deutsche
    Veroeffentlichungen —, aber die Gruppe 978-615 sagt Ungarn."""
    assert is_foreign(fund("9786155522017"), load_settings(), language_finder(db))


def test_an_unknown_group_stays_silent(db: Store) -> None:
    """Gruppe 992 steht in keiner Tabelle. Behaupten ist schlimmer als
    schweigen: der Fund bleibt im Stapel."""
    assert not is_foreign(fund("9789920000001"), load_settings(), language_finder(db))


def test_the_dnb_outranks_the_group(db: Store) -> None:
    """Ein deutscher Text bei einem ungarischen Verlag. Die DNB hatte das Buch
    in der Hand, die Gruppe kennt nur den Verlag."""
    db.save_dnb("9789630000001", Record(title="Ein Buch", language="ger"), NOW)

    assert not is_foreign(fund("9789630000001"), load_settings(), language_finder(db))


def test_the_group_only_speaks_where_the_dnb_is_silent(db: Store) -> None:
    """Umgekehrt: deutsche Gruppe, aber die DNB nennt Englisch. Das fing schon
    #10, und daran aendert die Gruppe nichts."""
    db.save_dnb("9783000000099", Record(title="A Book", language="eng"), NOW)

    assert is_foreign(fund("9783000000099"), load_settings(), language_finder(db))


def test_a_watchlist_title_stays_whatever_its_isbn_says(db: Store) -> None:
    """Was die Leserin selbst auf die Liste setzt, bleibt dort."""
    assert not is_foreign(
        fund("9786155522017", MatchReason.WATCHLIST), load_settings(), language_finder(db)
    )
