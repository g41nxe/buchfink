"""Eine Reihe beobachten: ihre Bände stehen auf der Watchlist (ADR 35, #85)."""

from __future__ import annotations

import json
from datetime import datetime

from ebook_watchlist import series_watch
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 3, 12, 0)
SLUG = "test"


def volume(isbn: str, title: str, number: str, *, author: str = "Pierce Brown",
           series: str = "Red Rising Saga") -> Observation:
    return Observation(source="overdrive", source_item_id=isbn[-4:], title=title, author=author,
                       isbn=isbn, series=series, series_index=number, series_ref="532674",
                       match_reason=MatchReason.GENRE_CATEGORY, observed_at=NOW)


def seen(store: Store, *observations: Observation) -> None:
    store.append(store.start_run(SLUG, "cli", NOW), SLUG, list(observations), NOW)


def red_rising(store: Store) -> int:
    seen(store, volume("9783000000101", "Red Rising", "1"),
         volume("9783000000102", "Golden Son", "2"),
         volume("9783000000103", "Morning Star", "3"))
    (row,) = store.series_rows()
    return row.id


def watching(store: Store) -> dict[str, dict]:
    """Titel -> Angaben, für jede aktive Beobachtung."""
    books = store.books_by_id(store.books_with_relations(SLUG).values())
    out = {}
    for book in books.values():
        for relation in store.relations_of(SLUG, book.id):
            if relation.kind == "watching" and relation.active:
                out[book.title] = json.loads(relation.details or "{}")
    return out


def test_watching_a_series_puts_its_volumes_on_the_watchlist(store: Store) -> None:
    series_id = red_rising(store)

    added = series_watch.watch(store, SLUG, series_id, now=NOW)

    assert added == 3
    assert set(watching(store)) == {"Red Rising", "Golden Son", "Morning Star"}
    assert all(d == {"series": series_id} for d in watching(store).values())
    assert series_watch.watched(store, SLUG) == {series_id}


def test_a_volume_she_already_has_stays_off_the_watchlist(store: Store) -> None:
    """Was man hat, muss man nicht beobachten."""
    series_id = red_rising(store)
    owned = store.find_or_create_book(isbn="9783000000101", title="Red Rising",
                                      author="Pierce Brown", now=NOW)
    store.put_relation(SLUG, owned.id, "owned", now=NOW)

    series_watch.watch(store, SLUG, series_id, now=NOW)

    assert set(watching(store)) == {"Golden Son", "Morning Star"}


def test_unwatching_leaves_what_she_watched_herself(store: Store) -> None:
    series_id = red_rising(store)
    own = store.find_or_create_book(isbn="9783000000103", title="Morning Star",
                                    author="Pierce Brown", now=NOW)
    store.put_relation(SLUG, own.id, "watching", now=NOW)
    series_watch.watch(store, SLUG, series_id, now=NOW)

    series_watch.unwatch(store, SLUG, series_id, now=NOW)

    assert set(watching(store)) == {"Morning Star"}
    assert series_watch.watched(store, SLUG) == set()


def test_a_new_volume_from_the_sweep_joins_the_watchlist(store: Store) -> None:
    series_id = red_rising(store)
    series_watch.watch(store, SLUG, series_id, now=NOW)
    fresh = volume("9783000000104", "Iron Gold", "4")
    short = volume("9783000000105", "Red Rising – Eine Kurzgeschichte", "4.5")

    added = series_watch.add_volumes(store, SLUG, series_id, [fresh, short], now=NOW)

    assert added == 1
    assert "Iron Gold" in watching(store)


def test_a_sweep_for_a_series_she_does_not_watch_adds_nothing(store: Store) -> None:
    series_id = red_rising(store)

    assert series_watch.add_volumes(store, SLUG, series_id,
                                    [volume("9783000000104", "Iron Gold", "4")], now=NOW) == 0
    assert watching(store) == {}


def test_the_run_sweeps_each_watched_series_where_its_address_is_known(store: Store) -> None:
    """Gefegt wird nur, wo die Quelle die Reihe kennt; ein Ausfall einer Quelle
    kostet nur sie."""
    series_id = red_rising(store)
    series_watch.watch(store, SLUG, series_id, now=NOW)
    asked: list[tuple[str, str | None]] = []

    class OverDrive:
        name = "overdrive"

        def by_series(self, name, author, ref):
            asked.append((name, ref))
            return [volume("9783000000104", "Iron Gold", "4")]

    class Onleihe:
        name = "onleihe"

        def by_series(self, name, author, ref):
            asked.append((name, ref))
            return []

    class Broken:
        name = "beam"

        def by_series(self, name, author, ref):
            raise RuntimeError("kaputt")

    added = series_watch.sweep(store, SLUG, [OverDrive(), Onleihe(), Broken()], now=NOW)

    assert added == 1
    assert "Iron Gold" in watching(store)
    keys = {row.id: row.key for row in store.series_rows()}
    sid, number = store.series_known()["9783000000104"]
    assert (keys[sid], number) == ("red rising", "4")
    # Die Onleihe kennt die Reihe nicht und bekommt keine Adresse; dass sie
    # dann nicht fragt, entscheidet sie selbst (test_series_sweep).
    assert asked == [("Red Rising Saga", "532674"), ("Red Rising Saga", None)]


# --- aus dem Review (04.10.2026) ---------------------------------------------


def _deactivate(store: Store, title: str, *, removed: bool) -> int:
    from ebook_watchlist.web import watchlist as view

    book = next(b for b in store.books() if b.title == title)
    if removed:
        view.finish(store, SLUG, book.id, "removed", now=NOW)
    else:
        store.deactivate_relation(SLUG, book.id, "watching", now=NOW)
    return book.id


def test_the_sweep_does_not_bring_back_a_volume_she_took_off(store: Store) -> None:
    """Entfernt oder pausiert ist ihre Entscheidung; das Fegen jedes Laufs
    findet den Band wieder, setzt ihn aber nicht zurück."""
    series_id = red_rising(store)
    series_watch.watch(store, SLUG, series_id, now=NOW)
    _deactivate(store, "Golden Son", removed=True)
    _deactivate(store, "Morning Star", removed=False)

    added = series_watch.add_volumes(store, SLUG, series_id, [
        volume("9783000000102", "Golden Son", "2"), volume("9783000000103", "Morning Star", "3"),
    ], now=NOW)

    assert added == 0
    assert set(watching(store)) == {"Red Rising"}


def test_watching_again_brings_back_what_came_through_the_series(store: Store) -> None:
    """Abbestellen und wieder beobachten: die Bände, die über die Reihe kamen,
    stehen wieder da."""
    series_id = red_rising(store)
    series_watch.watch(store, SLUG, series_id, now=NOW)
    series_watch.unwatch(store, SLUG, series_id, now=NOW)

    series_watch.watch(store, SLUG, series_id, now=NOW)

    assert set(watching(store)) == {"Red Rising", "Golden Son", "Morning Star"}


def test_unwatching_also_removes_a_paused_volume(store: Store) -> None:
    series_id = red_rising(store)
    series_watch.watch(store, SLUG, series_id, now=NOW)
    book_id = _deactivate(store, "Morning Star", removed=False)

    series_watch.unwatch(store, SLUG, series_id, now=NOW)

    (relation,) = [r for r in store.relations_of(SLUG, book_id) if r.kind == "watching"]
    assert json.loads(relation.details)["removed"] is True


def test_a_watched_series_survives_being_merged_into_another(store: Store) -> None:
    """Sie beobachtet „Robert Hunter" (OverDrive). Später verbindet eine
    DNB-Antwort sie mit der älteren Reihe „Ein Hunter-und-Garcia-Thriller":
    die Beobachtung und ihre Bände gehen mit."""
    from ebook_watchlist.dnb import Record

    store.save_dnb("9783000000201", Record(
        title="Der Kruzifix-Killer", series="Ein Hunter-und-Garcia-Thriller",
        series_index="1", author="Carter, Chris"), NOW)
    seen(store, volume("9783000000202", "Der Vollstrecker", "2", author="Chris Carter",
                       series="Robert Hunter"))
    hunter = max(r.id for r in store.series_rows())
    series_watch.watch(store, SLUG, hunter, now=NOW)

    seen(store, volume("9783000000201", "Der Kruzifix-Killer", "1", author="Chris Carter",
                       series="Robert Hunter"))

    (merged,) = store.series_rows()
    assert series_watch.watched(store, SLUG) == {merged.id}
    assert watching(store)["Der Vollstrecker"] == {"series": merged.id}
    series_watch.unwatch(store, SLUG, merged.id, now=NOW)
    assert "Der Vollstrecker" not in watching(store)
