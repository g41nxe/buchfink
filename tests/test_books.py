"""Buchidentität: die ISBN, wo es eine gibt — sonst der Matcher (ADR 18).

Die ISBNs unten sind echt und stammen aus einem Lauf vom 2026-09-04.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ebook_watchlist.catalog.books import BY_ISBN, BY_MATCH, BookLike, find
from ebook_watchlist.models import LinkOutcome
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 4, 18, 0)


# --- die Suche für sich -----------------------------------------------------


def test_the_isbn_decides_on_its_own() -> None:
    books = [BookLike(1, "9783641130008", "Der Ruf des Kuckucks", "Robert Galbraith")]
    found = find(books, isbn="9783641130008", title="Ganz anders betitelt", author=None)

    assert found is not None
    assert (found.book_id, found.how) == (1, BY_ISBN)


def test_a_matching_isbn_beats_a_contradicting_title() -> None:
    """Zwei Titel zu einer ISBN sind eine Marketingvariante, kein zweites Buch."""
    books = [BookLike(1, "9783104911854", "Krieg der Klone", "John Scalzi")]
    found = find(
        books,
        isbn="9783104911854",
        title="Krieg der Klone / Military-SF / Bestseller",
        author="Scalzi, John",
    )
    assert found is not None and found.how == BY_ISBN


def test_a_different_isbn_is_a_different_edition() -> None:
    """Der Knochenjäger steht bei beam unter 9783641157180 und in der Onleihe
    unter 9783837110951 — dieselbe Geschichte, zwei Ausgaben. Sie per Titel
    einzusammeln würde die ISBN nachträglich entwerten."""
    books = [BookLike(1, "9783641157180", "Der Knochenjäger", "Jeffery Deaver")]
    other_edition = find(
        books, isbn="9783837110951", title="Der Knochenjäger", author="Jeffery Deaver"
    )
    assert other_edition is None


def test_without_an_isbn_the_matcher_decides() -> None:
    books = [BookLike(1, None, "Der Knochenjäger", "Jeffery Deaver")]
    found = find(books, isbn=None, title="Der Knochenjaeger", author="Deaver, Jeffery")

    assert found is not None
    assert (found.book_id, found.how) == (1, BY_MATCH)


def test_a_book_with_no_isbn_can_still_be_recognised_by_a_find_that_has_one() -> None:
    """Watchlist-Einträge kommen ohne ISBN aus der YAML; die Beobachtung bringt
    sie mit. Sonst entstünde für jeden Eintrag ein zweites Buch."""
    books = [BookLike(1, None, "Cold Eternity", "S.A. Barnes")]
    found = find(books, isbn="9783453321885", title="Cold Eternity", author="S.A. Barnes")

    assert found is not None and found.how == BY_MATCH


def test_a_stranger_is_not_forced_onto_an_existing_book() -> None:
    books = [BookLike(1, None, "Der Schwarm", "Frank Schätzing")]
    assert find(books, isbn=None, title="Achtsam morden", author="Karsten Dusse") is None


def test_an_empty_table_finds_nothing() -> None:
    assert find([], isbn="9783104911854", title="Irgendwas", author=None) is None


# --- durch den Store --------------------------------------------------------


def test_creating_the_same_book_twice_yields_one_row(store: Store) -> None:
    first = store.find_or_create_book(
        isbn=None, title="Providence", author="Max Barry", now=NOW
    )
    second = store.find_or_create_book(
        isbn=None, title="Providence", author="Barry, Max", now=NOW
    )
    assert first.id == second.id
    assert len(store.books()) == 1


def test_a_later_find_teaches_the_book_its_isbn(store: Store) -> None:
    book = store.find_or_create_book(isbn=None, title="Providence", author="Max Barry", now=NOW)
    assert book.isbn is None

    assert store.learn_isbn(book.id, "9783453321885") is True
    assert store.book(book.id).isbn == "9783453321885"


def test_an_isbn_already_known_is_not_overwritten(store: Store) -> None:
    """Eine zweite ISBN heißt andere Ausgabe. Das stillschweigend zu übernehmen
    würde die Identität des Buchs verschieben."""
    book = store.find_or_create_book(
        isbn="9783641157180", title="Der Knochenjäger", author="Jeffery Deaver", now=NOW
    )
    assert store.learn_isbn(book.id, "9783837110951") is False
    assert store.book(book.id).isbn == "9783641157180"


def test_an_isbn_another_book_already_holds_is_refused(store: Store) -> None:
    """Dann sind es zwei Zeilen für ein Buch — Zusammenführen ist eine eigene
    Entscheidung, keine Nebenwirkung eines Laufs."""
    store.find_or_create_book(isbn="9783104911854", title="Krieg der Klone", now=NOW)
    other = store.find_or_create_book(isbn=None, title="Ganz anderes Buch", now=NOW)

    assert store.learn_isbn(other.id, "9783104911854") is False
    assert store.book(other.id).isbn is None


# --- die Verknüpfung zur Quelle --------------------------------------------


def test_a_source_that_does_not_stock_it_is_an_answer_not_a_gap(store: Store) -> None:
    """Acht von zehn Watchlist-Titeln stehen bei der Onleihe so — und genau
    diese Zeile verhindert, dass täglich neu gesucht wird."""
    book = store.find_or_create_book(isbn=None, title="Providence", author="Max Barry", now=NOW)
    store.put_book_source(
        book.id, "onleihe", outcome=str(LinkOutcome.NOT_FOUND), resolved_at=NOW
    )

    row = store.get_book_source(book.id, "onleihe")
    assert row is not None
    assert row.url is None
    assert '"outcome": "not_found"' in row.details


def test_each_source_keeps_its_own_row(store: Store) -> None:
    book = store.find_or_create_book(isbn=None, title="Providence", author="Max Barry", now=NOW)
    store.put_book_source(
        book.id, "beam", outcome=str(LinkOutcome.LINKED), url="https://beam/1", resolved_at=NOW
    )
    store.put_book_source(
        book.id, "onleihe", outcome=str(LinkOutcome.NOT_FOUND), resolved_at=NOW
    )

    assert {row.source for row in store.book_sources(book.id)} == {"beam", "onleihe"}


def test_an_unknown_outcome_fails_loudly(store: Store) -> None:
    """Ein Tippfehler fiele sonst still aus jeder Abfrage heraus, die fragt,
    was noch Aufmerksamkeit braucht."""
    book = store.find_or_create_book(isbn=None, title="Providence", now=NOW)
    with pytest.raises(ValueError, match="unknown link outcome"):
        store.put_book_source(book.id, "beam", outcome="linkd", resolved_at=NOW)


def test_the_source_rendering_is_kept_alongside(store: Store) -> None:
    """Damit eine falsche automatische Zuordnung sichtbar bleibt (ADR 9)."""
    book = store.find_or_create_book(isbn=None, title="Providence", author="Max Barry", now=NOW)
    store.put_book_source(
        book.id,
        "beam",
        outcome=str(LinkOutcome.LINKED),
        url="https://beam/1",
        resolved_at=NOW,
        matched_title="Providence / Science-Fiction",
        matched_author="Barry, Max",
    )
    details = store.get_book_source(book.id, "beam").details
    assert "Providence / Science-Fiction" in details
    assert "Barry, Max" in details
