"""Das Urteil über einen Fund, gerechnet statt gespeichert (#48)."""

from __future__ import annotations

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.judging import Verdict, judge, readers_verdict
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
    assert verdict.stars >= 4 and verdict.percent >= 60
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
