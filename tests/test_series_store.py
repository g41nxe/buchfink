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
    from ebook_watchlist.catalog.series import mid_series_finder

    seen(store, at_overdrive("9783000000301", "Die Chroniken", "1", author="Eine Autorin"))
    book = store.find_or_create_book(isbn="9783000000301", title="Erster Teil",
                                     author="Eine Autorin", now=NOW)
    store.put_relation("test", book.id, "owned", now=NOW)
    namesake = at_overdrive("9783000000304", "Die Chroniken", "4", author="Ein Anderer")
    seen(store, namesake)

    assert mid_series_finder(store, "test")(namesake)


def test_her_own_books_make_their_series_followed(store: Store) -> None:
    """Die Ausnahme „eine Reihe, die sie schon liest" vergleicht Schlüssel."""
    from ebook_watchlist.catalog.series import mid_series_finder

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


def at_beam(isbn: str, title: str, subtitle: str | None, *,
            author: str = "Tad Williams") -> Observation:
    return Observation(source="beam", source_item_id=isbn[-4:], title=title, subtitle=subtitle,
                       author=author, isbn=isbn, match_reason=MatchReason.PROFILE_AUTHOR,
                       observed_at=NOW)


def test_the_title_files_a_series_of_its_own(store: Store) -> None:
    """Der vierte Zeuge aus ADR 35, gebaut in ADR 38: ein Untertitel „Bobby
    Dollar 3" legt die Reihe an wie ein Name der Onleihe."""
    seen(store, at_beam("9783608108361", "Spät dran am Jüngsten Tag", "Bobby Dollar 3"),
         at_beam("9783608101270", "Otherland. Band 2", "Fluss aus blauem Feuer"),
         at_beam("9783608108781", "Die Hexenholzkrone 1", None))

    assert known(store) == {"9783608108361": ("bobby dollar", "3"),
                            "9783608101270": ("otherland", "2")}
    (entry,) = [e for e in store.series_entries_of("9783608108361")]
    assert entry.origin == "title"


def test_every_other_witness_outranks_the_title(store: Store) -> None:
    seen(store, at_beam("9783608105735", "Die dunklen Gassen des Himmels", "Bobby Dollar 2"))
    seen(store, Observation(source="onleihe", source_item_id="1", title="Die dunklen Gassen",
                            author="Tad Williams", isbn="9783608105735", series="Bobby Dollar",
                            series_index="1", match_reason=MatchReason.PROFILE_AUTHOR,
                            observed_at=NOW))

    assert known(store)["9783608105735"] == ("bobby dollar", "1")


# --- Eine Sammelausgabe erbt die Reihe seiner Bände (ADR 38) ----------------------

def nesbo(isbn: str, title: str, *, source: str = "beam", series: str | None = None,
          volume: str | None = None, subtitle: str | None = None) -> Observation:
    return Observation(source=source, source_item_id=isbn[-4:], title=title, subtitle=subtitle,
                       author="Jo Nesbø", isbn=isbn, series=series, series_index=volume,
                       match_reason=MatchReason.PROFILE_AUTHOR, observed_at=NOW)


def test_a_bundle_inherits_the_series_of_its_volumes(store: Store) -> None:
    """„Kakerlaken / Rotkehlchen": Kakerlaken hängt an Harry Hole, der
    Sammelausgabe nicht — bis sie von ihren Bänden erbt, mit dem Band als Spanne."""
    seen(store, nesbo("9783548920726", "Kakerlaken", source="overdrive",
                      series="Harry Hole", volume="2"),
         nesbo("9783548920665", "Rotkehlchen", source="overdrive",
               series="Harry Hole", volume="3"),
         nesbo("9783843713474", "Kakerlaken / Rotkehlchen",
               subtitle="Zwei Kriminalromane in einem eBook - Band 2 und 3"))

    assert store.series_from_bundles("test") == 1

    assert known(store)["9783843713474"] == ("harry hole", "2–3")
    assert [e.origin for e in store.series_entries_of("9783843713474")] == ["bundle"]
    assert store.contained_volumes("test", "9783843713474", "Kakerlaken / Rotkehlchen",
                                   "Jo Nesbø") == [("9783548920726", "Kakerlaken"),
                                                   ("9783548920665", "Rotkehlchen")]


def test_one_volume_with_a_series_is_enough(store: Store) -> None:
    seen(store, nesbo("9783548920726", "Kakerlaken", source="overdrive",
                      series="Harry Hole", volume="2"),
         nesbo("9783548920665", "Rotkehlchen"),
         nesbo("9783843713474", "Kakerlaken / Rotkehlchen"))

    store.series_from_bundles("test")

    assert known(store)["9783843713474"] == ("harry hole", "2")


def test_the_dnb_names_the_volumes_where_the_title_does_not(store: Store) -> None:
    seen(store, nesbo("9783548920726", "Kakerlaken", source="overdrive",
                      series="Harry Hole", volume="2"),
         nesbo("9783843799999", "Harry Hole: 3in1 Bundle"))
    store.save_dnb("9783843799999", Record(title="Harry Hole: 3in1 Bundle", author="Nesbø, Jo",
                                           contains=("9783548920726", "9783548920665")), NOW)
    store.save_dnb("9783548920665", Record(title="Rotkehlchen", author="Nesbø, Jo"), NOW)

    store.series_from_bundles("test")

    assert known(store)["9783843799999"] == ("harry hole", "2")
    # Die DNB nennt die ISBNs ohne Reihenfolge; verglichen wird die Menge.
    assert sorted(store.contained_volumes("test", "9783843799999", "Harry Hole: 3in1 Bundle",
                                          "Jo Nesbø")) == [("9783548920665", "Rotkehlchen"),
                                                           ("9783548920726", "Kakerlaken")]


def test_a_part_no_source_knows_makes_it_no_bundle(store: Store) -> None:
    """Dieselbe Selbstkorrektur wie beim Preisvergleich (ADR 24)."""
    seen(store, nesbo("9783548920726", "Kakerlaken", source="overdrive",
                      series="Harry Hole", volume="2"),
         nesbo("9783843713474", "Kakerlaken / Psychothriller / Verlagsbestseller"))

    assert store.series_from_bundles("test") == 0
    assert "9783843713474" not in known(store)
    assert store.contained_volumes("test", "9783843713474",
                                   "Kakerlaken / Psychothriller / Verlagsbestseller",
                                   "Jo Nesbø") == []


def test_a_volume_by_another_author_does_not_count(store: Store) -> None:
    seen(store, Observation(source="overdrive", source_item_id="x", title="Kakerlaken",
                            author="Jemand Anders", isbn="9783548920726", series="Harry Hole",
                            series_index="2", match_reason=MatchReason.PROFILE_AUTHOR,
                            observed_at=NOW),
         nesbo("9783548920665", "Rotkehlchen"),
         nesbo("9783843713474", "Kakerlaken / Rotkehlchen"))

    assert store.series_from_bundles("test") == 0
