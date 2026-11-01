"""Eine gemochte Reihe hält ihre Bände (ADR 45, #121)."""

from __future__ import annotations

from datetime import datetime

from ebook_watchlist.catalog.series import liked_series
from ebook_watchlist.judging.judge import Verdict, with_series
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.wikidata import Membership

NOW = datetime(2026, 11, 1, 12, 0)
AUTHOR = "Joe Abercrombie"
SAGA = (("9783000000011", "Kriegsklingen", "1"), ("9783000000012", "Feuerklingen", "2"),
        ("9783000000013", "Königsklingen", "3"))


def saga(db: Store, *, mark: dict[str, RelationKind] | None = None) -> int:
    """Die Klingen-Saga, von Hand zugeordnet; ``mark`` legt Beziehungen an."""
    for isbn, title, volume in SAGA:
        book = db.find_or_create_book(isbn=isbn, title=title, author=AUTHOR, now=NOW)
        db.assign_series(isbn, "Klingen-Saga", AUTHOR, volume)
        if mark and title in mark:
            db.put_relation("test", book.id, str(mark[title]), now=NOW)
    return db.series_of([SAGA[0][0]])[SAGA[0][0]].id


def test_a_liked_volume_holds_the_others_above_the_threshold(store: Store) -> None:
    saga(store, mark={"Kriegsklingen": RelationKind.LIKED})

    liked = liked_series(store, "test")

    assert liked.note(SAGA[1][0]) == ("Fortsetzung von „Kriegsklingen“", True)
    assert liked.note(SAGA[2][0]) == ("Fortsetzung von „Kriegsklingen“", True)


def test_an_earlier_volume_is_no_continuation(store: Store) -> None:
    saga(store, mark={"Feuerklingen": RelationKind.LIKED})

    assert liked_series(store, "test").note(SAGA[0][0]) \
        == ("aus derselben Reihe wie „Feuerklingen“", True)


def test_owning_a_volume_alone_does_not_count(store: Store) -> None:
    """*Hab ich* sagt nicht, dass sie die Reihe mag."""
    saga(store, mark={"Kriegsklingen": RelationKind.OWNED})

    assert liked_series(store, "test").note(SAGA[1][0]) is None


def test_watching_the_series_counts_as_liking_it(store: Store) -> None:
    from ebook_watchlist.catalog import series_watch

    series_id = saga(store)
    series_watch.watch(store, "test", series_id, now=NOW)

    assert liked_series(store, "test").note(SAGA[1][0]) \
        == ("aus der Reihe Klingen-Saga, die du beobachtest", True)


def test_one_disliked_volume_lifts_the_floor_for_the_series(store: Store) -> None:
    saga(store, mark={"Kriegsklingen": RelationKind.LIKED,
                      "Königsklingen": RelationKind.DISLIKED})

    assert liked_series(store, "test").note(SAGA[1][0]) is None


def test_a_book_of_the_same_world_gets_a_note_but_no_floor(store: Store) -> None:
    """*Racheklingen* spielt in der Welt, ist aber kein Band der Saga."""
    store.find_or_create_book(isbn=SAGA[0][0], title="Kriegsklingen", author=AUTHOR, now=NOW)
    store.save_wikidata(SAGA[0][0], AUTHOR, Membership("Q1", "Q9", "Klingenwelt", "1"), NOW)
    book = store.find_or_create_book(isbn=SAGA[0][0], title="Kriegsklingen", now=NOW)
    store.put_relation("test", book.id, str(RelationKind.LIKED), now=NOW)
    store.save_wikidata("9783000000099", AUTHOR, Membership("Q4", "Q9", "Klingenwelt"), NOW)

    assert liked_series(store, "test").note("9783000000099") \
        == ("spielt in der Welt von „Kriegsklingen“", False)


def test_the_floor_lifts_a_weak_verdict_and_leaves_a_strong_one() -> None:
    weak, strong = Verdict(stars=1, percent=20), Verdict(stars=4, percent=70)
    note = ("Fortsetzung von „Kriegsklingen“", True)

    lifted = with_series(weak, note, 3)
    kept = with_series(strong, note, 3)
    world = with_series(weak, ("spielt in der Welt von „Kriegsklingen“", False), 3)

    assert (lifted.stars, lifted.percent, lifted.lifted) == (3, 20, True)
    assert lifted.series_note == "Fortsetzung von „Kriegsklingen“"
    assert (kept.stars, kept.lifted, kept.series_note) == (4, False, note[0])
    assert (world.stars, world.lifted) == (1, False)
    assert "Fortsetzung von „Kriegsklingen“" in lifted.why
    assert with_series(weak, None, 3) is weak
