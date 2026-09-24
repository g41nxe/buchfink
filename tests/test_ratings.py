"""Gespeicherte Urteile: die Sterne der Leserin und fremde Stimmen (ADR 17, ADR 33).

Was die Anwendung selbst urteilt, wird gerechnet und nicht gespeichert
(``judging``); hier steht nur, was ein Mensch oder fremde Leser:innen sagen.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.ratings import BY_ONLEIHE_READERS, BY_READER, book_subject, subject_of
from ebook_watchlist.run import _record_foreign_ratings
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 4, 22, 0)


def test_the_readers_stars_and_a_foreign_average_stand_side_by_side(store: Store) -> None:
    """Der Schlüssel ist ``(subject, origin)``: keines überschreibt das andere
    (ADR 17)."""
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    subject = book_subject(book.id)
    store.put_rating(subject, stars=5, confidence="belegt", reason="", profile_version=1,
                     now=NOW, origin=BY_READER)

    store.put_rating(subject, stars=3.4, confidence="belegt", reason="", profile_version=0,
                     now=NOW, origin=BY_ONLEIHE_READERS, votes=12)

    assert store.rating(subject, origin=BY_READER).stars == 5
    assert store.rating(subject, origin=BY_ONLEIHE_READERS).stars == 3.4


@pytest.mark.parametrize("origin", ["model", "conversation", "freund"])
def test_an_unknown_origin_is_refused(store: Store, origin: str) -> None:
    """Das Urteil der Anwendung wird seit ADR 33 gerechnet, nicht gespeichert;
    ``model`` und ``conversation`` gibt es nicht mehr (#52)."""
    with pytest.raises(ValueError, match="unbekannte Herkunft"):
        store.put_rating("book:1", stars=4, confidence="teils", reason="", profile_version=1,
                         now=NOW, origin=origin)


def test_taking_her_stars_back_leaves_nothing_rather_than_a_zero(store: Store) -> None:
    """Nicht bewertet und "passt überhaupt nicht" sind zwei Auskünfte."""
    store.put_rating("book:1", stars=4, confidence="belegt", reason="", profile_version=1,
                     now=NOW, origin=BY_READER)

    assert store.drop_rating("book:1", BY_READER) is True
    assert store.rating("book:1", origin=BY_READER) is None
    assert store.drop_rating("book:1", BY_READER) is False


def test_a_foreign_voice_is_recorded_with_its_votes(store: Store) -> None:
    """Keine eigene Tabelle: ``rating`` ist schon nach (subject, origin)
    geschlüsselt, und genau darauf kommt eine weitere Quelle dazu (ADR 19,
    Ticket 54)."""
    found = Observation(
        source="onleihe", source_item_id="1", title="Die sieben Schwestern",
        author="Riley, Lucinda", match_reason=MatchReason.WATCHLIST,
        isbn="9783641117009", rating=4, rating_votes=1641,
    )

    _record_foreign_ratings(store, [found])

    foreign = store.rating(subject_of(found), origin=BY_ONLEIHE_READERS)
    assert (foreign.stars, foreign.votes, foreign.confidence) == (4, 1641, "belegt")


def test_a_single_voice_is_not_evidence(store: Store) -> None:
    """Fünf von sieben Bewertungen unseres Korpus ruhen bei Google Books auf
    einer einzigen Stimme. Der Wert wird festgehalten, und ohne Anzahl wird gar
    nichts geschrieben."""
    barely = Observation(source="onleihe", source_item_id="2", title="Kaum Stimmen",
                         author="Wer", match_reason=MatchReason.WATCHLIST,
                         isbn="9780000000002", rating=5, rating_votes=3)
    without = Observation(source="onleihe", source_item_id="3", title="Gar keine",
                          author="Wer", match_reason=MatchReason.WATCHLIST,
                          isbn="9780000000003", rating=5, rating_votes=None)

    _record_foreign_ratings(store, [barely, without])

    # "belegt" heißt "aus geprüfter Quelle", nicht "statistisch belastbar". Wie
    # dünn die Stimmenlage ist, sagt die Zahl daneben, keine erfundene Grenze.
    row = store.rating(subject_of(barely), origin=BY_ONLEIHE_READERS)
    assert (row.confidence, row.votes) == ("belegt", 3)
    assert store.rating(subject_of(without), origin=BY_ONLEIHE_READERS) is None


def test_without_an_isbn_the_find_itself_is_the_subject() -> None:
    """Bündel und Einzelfolgen haben keine — ein Schlüssel je Quelle ist
    ehrlicher als einer, der über den Titel geraten wäre."""
    plain = Observation(source="beam", source_item_id="1", title="Ein Fund",
                        match_reason=MatchReason.GENRE_CATEGORY)

    assert subject_of(plain) == "item:beam:1"
    assert subject_of(Observation(source="beam", source_item_id="1", title="x",
                                  match_reason=MatchReason.GENRE_CATEGORY,
                                  isbn="9783104911854")) == "isbn:9783104911854"
