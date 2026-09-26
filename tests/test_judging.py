"""Das Urteil über einen Fund, gerechnet statt gespeichert (#48)."""

from __future__ import annotations

import pytest

from conftest import STAR_TERMS, judging_profile, needs_vocabulary
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.judging import Verdict, judge, load_judge, readers_verdict
from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary

pytestmark = needs_vocabulary


@pytest.fixture(scope="module")
def vocabulary():
    return load_vocabulary()


@pytest.fixture(scope="module")
def weights():
    return load_weights()


def portrait(vocabulary, *terms: str, pitch: str | None = "Ein Buch.") -> Portrait:
    return Portrait(
        known=True,
        fingerprint=fingerprint(vocabulary),
        pitch=pitch,
        traits=tuple(Trait(t, f"Satz zu {t}", "wissen") for t in terms),
    )


PROFILE = ReadingProfile(
    facets=(Facet(("brooding", "harsh"), ("Leichenblässe", "Sharp Objects")),),
    counterweights=(Counterweight(("leisurely",), None, ("Herr der Ringe",)),),
    liked=(Liked("brooding"), Liked("harsh")),
)


def test_a_book_that_carries_a_whole_facet_is_judged_high(vocabulary, weights) -> None:
    verdict = judge(portrait(vocabulary, "brooding", "gritty"), PROFILE, vocabulary, weights)

    assert verdict is not None
    assert verdict.stars >= 4 and verdict.percent >= 55
    assert verdict.pitch == "Ein Buch."
    assert verdict.reasons


def test_the_counterweight_pulls_a_book_down(vocabulary, weights) -> None:
    plain = judge(portrait(vocabulary, "brooding", "gritty"), PROFILE, vocabulary, weights)
    against = judge(
        portrait(vocabulary, "brooding", "gritty", "leisurely"), PROFILE, vocabulary, weights
    )

    assert against.percent < plain.percent


def test_nothing_is_judged_without_a_profile(vocabulary, weights) -> None:
    assert judge(portrait(vocabulary, "harsh"), None, vocabulary, weights) is None


def test_nothing_is_judged_without_a_portrait(vocabulary, weights) -> None:
    assert judge(None, PROFILE, vocabulary, weights) is None


def test_a_book_the_model_does_not_know_is_not_judged(vocabulary, weights) -> None:
    unknown = Portrait(known=False, fingerprint=fingerprint(vocabulary))

    assert judge(unknown, PROFILE, vocabulary, weights) is None


def test_a_verdict_withholds_below_the_threshold_only() -> None:
    assert Verdict(stars=2).withholds(3)
    assert not Verdict(stars=3).withholds(3)


def test_her_own_stars_are_marked_as_hers() -> None:
    verdict = readers_verdict(5)

    assert verdict.by_reader and verdict.percent is None and verdict.stars == 5


# --- viele auf einmal (#48) ---------------------------------------------------------


def test_the_judge_needs_a_profile_in_the_database(store) -> None:
    assert load_judge(store, "test") is None


def test_the_judge_carries_the_threshold_of_the_scheme(store, vocabulary) -> None:
    from datetime import datetime

    store.put_reading_profile("test", PROFILE, cause="Test", now=datetime(2026, 9, 24, 12, 0))

    judge_ = load_judge(store, "test")

    assert judge_ is not None and judge_.threshold == 3
    assert judge_.stamp == fingerprint(vocabulary)


def test_the_judge_takes_the_first_subject_that_has_a_portrait(store, vocabulary, weights) -> None:
    from datetime import datetime

    store.put_reading_profile("test", PROFILE, cause="Test", now=datetime(2026, 9, 24, 12, 0))
    judge_ = load_judge(store, "test")
    store.put_portrait("book:7", portrait(vocabulary, "brooding", "gritty"),
                       now=datetime(2026, 9, 24, 12, 0))

    portraits = judge_.portraits(store, ["isbn:1", "book:7"])
    verdict = judge_.verdict_among(portraits, ["isbn:1", "book:7"])

    assert set(portraits) == {"book:7"}
    assert verdict is not None and verdict.stars >= 4
    assert judge_.verdict_among(portraits, ["isbn:1"]) is None


def test_the_youngest_portrait_of_a_subject_wins(store, vocabulary) -> None:
    from datetime import datetime

    store.put_portrait("isbn:1", portrait(vocabulary, "leisurely", pitch="alt"),
                       now=datetime(2026, 9, 24, 12, 0))
    store.put_portrait("isbn:1", portrait(vocabulary, "gritty", pitch="neu"),
                       now=datetime(2026, 9, 24, 13, 0))

    found = store.portraits_for(["isbn:1"], fingerprint(vocabulary))

    assert found["isbn:1"].pitch == "neu"


@pytest.mark.parametrize("stars", [1, 2, 3, 4, 5])
def test_the_test_profile_steers_the_stars_exactly(vocabulary, weights, stars) -> None:
    """Die Web-Tests verlassen sich darauf, dass ``describe`` genau diese Sterne
    liefert."""
    verdict = judge(portrait(vocabulary, *STAR_TERMS[stars]), judging_profile(),
                    vocabulary, weights)

    assert verdict.stars == stars


# --- die Form lernt aus den bewerteten Büchern (#79) ------------------------------------


def _read_book(store, vocabulary, title: str, kind: str, *terms: str, isbn: str | None = None,
             details: dict | None = None) -> int:
    from datetime import datetime

    now = datetime(2026, 9, 26, 12, 0)
    book = store.find_or_create_book(isbn=isbn, title=title, author="A", now=now)
    subject = f"isbn:{isbn}" if isbn else f"book:{book.id}"
    store.put_portrait(subject, portrait(vocabulary, *terms), now=now)
    store.put_relation("test", book.id, kind, active=True, now=now, **(details or {}))
    return book.id


def test_the_judge_learns_from_the_rated_books(store, vocabulary) -> None:
    """Ein gemochtes Buch hebt, was es trägt — auch was nicht angetippt ist."""
    from datetime import datetime

    store.put_reading_profile("test", PROFILE, cause="Test", now=datetime(2026, 9, 26, 12, 0))
    book = portrait(vocabulary, "brooding", "world_building", "thought_provoking")
    before = load_judge(store, "test").verdict(book)

    _read_book(store, vocabulary, "Otherland", "liked", "world_building", "thought_provoking",
             isbn="9783000000001")
    after = load_judge(store, "test").verdict(book)

    assert after.percent > before.percent


def test_the_judge_reads_her_reasons_from_the_rating(store, vocabulary) -> None:
    from datetime import datetime

    from ebook_watchlist.judging import rated_books

    store.put_reading_profile("test", PROFILE, cause="Test", now=datetime(2026, 9, 26, 12, 0))
    _read_book(store, vocabulary, "Der Schwarm", "disliked", "intensifying", "world_building",
             details={"reasons": {"add": ["leisurely"], "drop": ["nerve_racking"],
                                  "here": ["big_world"]}})

    (swarm,) = rated_books(store, "test", vocabulary, load_weights(), fingerprint(vocabulary))

    assert swarm.sign == -1
    assert swarm.added == ("leisurely",)
    assert set(swarm.dropped) == {"nerve_racking", "big_world"}
