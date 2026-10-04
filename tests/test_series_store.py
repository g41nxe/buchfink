"""Die Reihe im Store: ein Schlüssel, Bände je ISBN, Herkunft (ADR 35, #83)."""

from __future__ import annotations

from datetime import datetime

from ebook_watchlist.dnb import Record
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 3, 12, 0)


def known(store: Store) -> dict[str, tuple[str, str | None]]:
    """ISBN -> (Schlüssel, Band), lesbar: `series_known` liefert Ids."""
    keys = {row.id: row.key for row in store.series_rows()}
    return {isbn: (keys[sid], volume) for isbn, (sid, volume) in store.series_known().items()}


def seen(store: Store, *observations: Observation) -> None:
    store.append(store.start_run("test", "cli", NOW), "test", list(observations), NOW)


def at_overdrive(isbn: str, series: str, volume: str | None = None, *,
                 author: str = "Pierce Brown", ref: str | None = None) -> Observation:
    return Observation(source="overdrive", source_item_id=isbn[-4:], title="Ein Band",
                       author=author, isbn=isbn, series=series, series_index=volume,
                       series_ref=ref, match_reason=MatchReason.PROFILE_AUTHOR,
                       observed_at=NOW)


def test_a_sighting_files_its_volume_under_the_isbn(store: Store) -> None:
    seen(store, at_overdrive("9780000000003", "Red Rising Saga", "3", ref="532674"))

    assert known(store) == {"9780000000003": ("red rising", "3")}
    assert store.series_refs("red rising") == {"overdrive": "532674"}


def test_the_dnb_outranks_the_library(store: Store) -> None:
    """Die DNB spricht über genau diese ISBN, OverDrive vielleicht über das Werk."""
    seen(store, at_overdrive("9780000000001", "Red Rising Saga", "3"))
    store.save_dnb("9780000000001", Record(title="Red Rising", series="Red Rising",
                                           series_index="1", author="Brown, Pierce"), NOW)

    assert known(store)["9780000000001"] == ("red rising", "1")


def test_two_names_for_one_isbn_are_one_series(store: Store) -> None:
    """„Ein Hunter-und-Garcia-Thriller" (DNB) und „Robert Hunter" (OverDrive):
    die Regel trifft sie nicht, die gemeinsame ISBN schon."""
    store.save_dnb("9783000000011", Record(title="Der Kruzifix-Killer",
                                           series="Ein Hunter-und-Garcia-Thriller",
                                           series_index="1", author="Carter, Chris"), NOW)
    seen(store,
         at_overdrive("9783000000011", "Robert Hunter", "1", author="Chris Carter"),
         at_overdrive("9783000000022", "Robert Hunter", "2", author="Chris Carter"))

    found = known(store)
    assert found["9783000000022"][0] == found["9783000000011"][0]
    assert found["9783000000022"][1] == "2"


def test_the_same_name_by_two_authors_is_two_series(store: Store) -> None:
    seen(store,
         at_overdrive("9783000000033", "Die Chroniken", "2", author="Eine Autorin"),
         at_overdrive("9783000000044", "Die Chroniken", "2", author="Ein Anderer"))

    rows = store.series_rows()
    assert len([r for r in rows if r.key == "chroniken"]) == 2


def test_an_old_dnb_answer_is_filed_on_the_next_run(store: Store) -> None:
    """Antworten von vor der Reihen-Tabelle bekommen ihre Zuordnung, ohne neu
    zu fragen — derselbe Schritt, der Reihen auf die Bücher schreibt."""
    store.save_dnb("9783000000055", Record(title="Immerkalt", series="Immermorde",
                                           series_index="3"), NOW)
    store.forget_series_entries()  # wie vor ADR 35

    store.series_from_dnb()

    assert known(store)["9783000000055"] == ("immermorde", "3")


def test_her_series_is_not_a_namesake_by_another_author(store: Store) -> None:
    """Sie besitzt einen Band von „Die Chroniken" (A); Band 4 von „Die
    Chroniken" einer anderen Autorin bleibt ein Folgeband (Review 04.10.2026)."""
    from ebook_watchlist.series import mid_series_finder

    seen(store, at_overdrive("9783000000301", "Die Chroniken", "1", author="Eine Autorin"))
    book = store.find_or_create_book(isbn="9783000000301", title="Erster Teil",
                                     author="Eine Autorin", now=NOW)
    store.put_relation("test", book.id, "owned", now=NOW)
    namesake = at_overdrive("9783000000304", "Die Chroniken", "4", author="Ein Anderer")
    seen(store, namesake)

    assert mid_series_finder(store, "test")(namesake)


def test_her_own_books_make_their_series_followed(store: Store) -> None:
    """Die Ausnahme „eine Reihe, die sie schon liest" vergleicht Schlüssel."""
    from ebook_watchlist.series import mid_series_finder

    store.save_dnb("9783000000066", Record(title="Wayward", series="Ein Wayward-Pines-Thriller",
                                           series_index="2"), NOW)
    book = store.find_or_create_book(isbn="9783000000066", title="Wayward",
                                     author="Blake Crouch", now=NOW)
    store.put_relation("test", book.id, "owned", now=NOW)
    later = at_overdrive("9783000000077", "Wayward Pines", "3", author="Blake Crouch")
    seen(store, later)

    assert not mid_series_finder(store, "test")(later)


def test_two_series_that_meet_at_an_isbn_become_one(store: Store) -> None:
    """Erst kennt OverDrive „Robert Hunter" von einem anderen Band, die DNB
    „Ein Hunter-und-Garcia-Thriller" — zwei Reihen. Treffen sie sich an einer
    ISBN, ist es eine, mit allen Bänden und der Adresse."""
    seen(store, at_overdrive("9783000000022", "Robert Hunter", "2", author="Chris Carter",
                             ref="1656"))
    store.save_dnb("9783000000011", Record(title="Der Kruzifix-Killer",
                                           series="Ein Hunter-und-Garcia-Thriller",
                                           series_index="1", author="Carter, Chris"), NOW)
    seen(store, at_overdrive("9783000000011", "Robert Hunter", "1", author="Chris Carter"))

    found = known(store)
    assert found["9783000000022"][0] == found["9783000000011"][0]
    assert len(store.series_rows()) == 1
    assert store.series_refs(found["9783000000011"][0]) == {"overdrive": "1656"}


def test_a_book_names_its_series_and_volume(store: Store) -> None:
    """„Reihe · Band n" überall, wo ein Buch steht (#85)."""
    seen(store, at_overdrive("9780000000003", "Red Rising Saga", "3"),
         at_overdrive("9780000000009", "Red Rising Saga"))

    named = store.series_of(["9780000000003", "9780000000009", "9780000000000"])

    assert named["9780000000003"].label == "Red Rising Saga · Band 3"
    assert named["9780000000009"].label == "Red Rising Saga"
    assert named["9780000000003"].id == named["9780000000009"].id
    assert "9780000000000" not in named


def test_a_series_without_author_joins_the_one_with(store: Store) -> None:
    """Eine DNB-Antwort ohne Autor:in und OverDrive mit Autor:in: eine Reihe —
    aber zwei bekannte verschiedene Autor:innen bleiben zwei (Review 04.10.2026)."""
    store.save_dnb("9783000000066", Record(title="Wayward", series="Ein Wayward-Pines-Thriller",
                                           series_index="2"), NOW)
    seen(store, at_overdrive("9783000000077", "Wayward Pines", "3", author="Blake Crouch"),
         at_overdrive("9783000000088", "Wayward Pines", "1", author="Jemand Anderes"))

    found = known(store)
    assert found["9783000000077"][0] == found["9783000000066"][0] == "wayward pines"
    assert len([r for r in store.series_rows() if r.key == "wayward pines"]) == 2
