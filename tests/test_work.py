"""Ein Werk, ein Urteil: Übersetzung und Original teilen Steckbrief und Sterne (ADR 36, #80)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from ebook_watchlist.dnb import Record
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.portrait import Portrait
from ebook_watchlist.ratings import BY_READER, book_subject
from ebook_watchlist.store import Store
from ebook_watchlist.work import work_key

NOW = datetime(2026, 10, 3, 12, 0)
GERMAN = "9783641253486"
ENGLISH = "9781524759803"


@pytest.mark.parametrize(("left", "right"), [
    (("Crouch, Blake", "Recursion"), ("Blake Crouch", "Recursion")),
    (("Blake Crouch", "Gestohlene  Erinnerung."), ("Blake Crouch", "gestohlene erinnerung")),
    (("Andrzej Sapkowski", "Der letzte Wunsch"), ("Sapkowski, Andrzej", "Der Letzte Wunsch")),
])
def test_one_work_has_one_key(left: tuple[str, str], right: tuple[str, str]) -> None:
    assert work_key(*left) == work_key(*right)


@pytest.mark.parametrize(("author", "left", "right"), [
    # Bände einer Reihe: abgeschnitten bliebe nur der Reihenname (03.10.2026).
    ("Charles Sheffield", "The Heritage Universe - Band 1: Gezeitensturm",
     "The Heritage Universe - Band 2: Die Reliktjäger"),
    ("Alex Berg", "Tod im Norden – Am Anfang war der Tod", "Tod im Norden – Der Tod wartet nicht"),
    # Ein Sammelband ist nicht sein erster Band.
    ("Chris Carter", "Der Kruzifix-Killer", "Der Kruzifix-Killer / Der Vollstrecker"),
    ("John Scalzi", "Die letzte Einheit", "Die letzte Einheit,  - Episode 1: Das B-Team"),
])
def test_volumes_and_bundles_are_works_of_their_own(author: str, left: str, right: str) -> None:
    """Der ganze Titel zählt, auch der Teil nach dem Strich."""
    assert work_key(author, left) != work_key(author, right)


def test_two_books_of_one_author_are_two_works() -> None:
    """Die Gegenprobe: dieselbe Autor:in macht noch kein Werk."""
    assert work_key("Blake Crouch", "Recursion") != work_key("Blake Crouch", "Dark Matter")
    assert work_key("Blake Crouch", "") is None


def seen(store: Store, *observations: Observation) -> None:
    store.append(store.start_run("test", "cli", NOW), "test", list(observations), NOW)


def find(isbn: str, title: str, author: str = "Blake Crouch") -> Observation:
    return Observation(source="beam" if isbn == GERMAN else "overdrive",
                       source_item_id=isbn[-5:], title=title, author=author, isbn=isbn,
                       match_reason=MatchReason.GENRE_CATEGORY, observed_at=NOW)


def recursion(store: Store) -> None:
    """Die deutsche Ausgabe nennt ihr Original nur über die DNB."""
    seen(store, find(GERMAN, "Gestohlene Erinnerung"), find(ENGLISH, "Recursion"))
    store.save_dnb(GERMAN, Record(title="Gestohlene Erinnerung", author="Crouch, Blake",
                                  original_title="Recursion"), NOW)


def portrait(pitch: str, *, with_text: bool = True) -> Portrait:
    return Portrait(fingerprint="fp", known=True, title="t", author="Blake Crouch",
                    pitch=pitch, with_text=with_text)


def test_a_translation_and_its_original_are_one_work(store: Store) -> None:
    recursion(store)

    assert store.work_siblings([ENGLISH])[ENGLISH] == {GERMAN, ENGLISH}


def test_a_second_edition_finds_the_portrait_of_the_first(store: Store) -> None:
    """Ein Werk, ein Steckbrief: die englische Ausgabe kostet keinen Aufruf."""
    recursion(store)
    store.put_portrait(f"isbn:{GERMAN}", portrait("Erinnerungen werden neu erlebt."), now=NOW)

    assert store.portrait(f"isbn:{ENGLISH}", "fp").pitch == "Erinnerungen werden neu erlebt."
    assert store.portraits_for([f"isbn:{ENGLISH}"], "fp")[f"isbn:{ENGLISH}"].pitch == (
        "Erinnerungen werden neu erlebt.")


def test_within_a_work_a_portrait_with_text_wins(store: Store) -> None:
    """Der jüngere ohne Text beschrieb *Dark Matter* — er gilt nicht."""
    recursion(store)
    store.put_portrait(f"isbn:{ENGLISH}", portrait("Recursion.", with_text=True), now=NOW)
    store.put_portrait(f"isbn:{GERMAN}", portrait("Dark Matter.", with_text=False),
                       now=NOW + timedelta(hours=8))

    assert store.portrait(f"isbn:{GERMAN}", "fp").pitch == "Recursion."


def test_her_stars_belong_to_the_work(store: Store) -> None:
    recursion(store)
    german = store.find_or_create_book(isbn=GERMAN, title="Gestohlene Erinnerung",
                                       author="Blake Crouch", now=NOW)
    english = store.find_or_create_book(isbn=ENGLISH, title="Recursion",
                                        author="Crouch, Blake", now=NOW)
    store.put_rating(book_subject(german.id), stars=4, confidence="belegt", reason="",
                     profile_version=1, origin=BY_READER, now=NOW)

    stored = store.rating(book_subject(english.id), origin=BY_READER)

    assert stored is not None and stored.stars == 4
    assert store.ratings_for([book_subject(english.id)])[
        (book_subject(english.id), BY_READER)].stars == 4


def test_two_books_of_one_author_keep_their_own_portraits(store: Store) -> None:
    seen(store, find(GERMAN, "Gestohlene Erinnerung"), find(ENGLISH, "Dark Matter"))
    store.put_portrait(f"isbn:{GERMAN}", portrait("Erinnerungen."), now=NOW)

    assert store.portrait(f"isbn:{ENGLISH}", "fp") is None
    assert store.work_siblings([ENGLISH])[ENGLISH] == {ENGLISH}


def test_an_old_dnb_answer_joins_its_work_on_the_next_run(store: Store) -> None:
    recursion(store)
    store.forget_work_entries()  # wie vor ADR 36

    store.series_from_dnb()

    assert store.work_siblings([ENGLISH])[ENGLISH] == {GERMAN, ENGLISH}


def test_a_watch_of_one_edition_sees_the_other_she_owns(store: Store) -> None:
    """„hast du schon als …" — die Watchlist wird nicht angefasst (ADR 36)."""
    recursion(store)
    german = store.find_or_create_book(isbn=GERMAN, title="Gestohlene Erinnerung",
                                       author="Blake Crouch", now=NOW)
    store.put_relation("test", german.id, "owned", now=NOW)

    assert store.owned_as("test", [ENGLISH]) == {ENGLISH: "Gestohlene Erinnerung"}
    assert replace(find(ENGLISH, "Recursion")).isbn in store.decided_works("test")


def test_new_stars_on_one_edition_hold_for_the_whole_work(store: Store) -> None:
    """Aus dem Review (04.10.2026): wer an der zweiten Ausgabe neue Sterne
    vergibt, ändert das Urteil des Werks — nicht ein zweites daneben."""
    from ebook_watchlist.web.book import set_stars

    recursion(store)
    german = store.find_or_create_book(isbn=GERMAN, title="Gestohlene Erinnerung",
                                       author="Blake Crouch", now=NOW)
    english = store.find_or_create_book(isbn=ENGLISH, title="Recursion",
                                        author="Crouch, Blake", now=NOW)

    class Settings:
        slug = "test"

    set_stars(store, Settings(), german.id, 4, now=NOW)
    set_stars(store, Settings(), english.id, 2, now=NOW)

    assert store.rating(book_subject(german.id), origin=BY_READER).stars == 2
    assert store.rating(book_subject(english.id), origin=BY_READER).stars == 2

    set_stars(store, Settings(), german.id, None, now=NOW)

    assert store.rating(book_subject(english.id), origin=BY_READER) is None
