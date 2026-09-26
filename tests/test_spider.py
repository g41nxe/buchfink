"""Die Spinnen: die Geschmacksform als Netz, das Buch darübergelegt (#79)."""

from __future__ import annotations

import math

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.taste_form import learn
from ebook_watchlist.web.spider import MOST_AXES, book_spiders, reader_spiders

pytestmark = needs_vocabulary


@pytest.fixture(scope="module")
def vocabulary():
    return load_vocabulary()


@pytest.fixture(scope="module")
def weights():
    return load_weights()


PROFILE = ReadingProfile(
    facets=(Facet(("brooding", "harsh")),),
    counterweights=(Counterweight(("leisurely",)),),
    liked=(Liked("brooding"), Liked("harsh"), Liked("menacing"), Liked("thought_provoking"),
           Liked("pursuit"), Liked("quest"), Liked("escape")),
)


def form(vocabulary, weights, profile=PROFILE):
    return learn(profile, (), vocabulary, weights)


def test_the_form_is_drawn_as_two_spiders(vocabulary, weights) -> None:
    terms, patterns = reader_spiders(form(vocabulary, weights), vocabulary)

    assert {a.family_id for a in terms.axes} == {
        "brooding", "harsh", "menacing", "thought_provoking", "leisurely"}
    assert {a.family_id for a in patterns.axes} == {"pursuit", "quest", "escape"}


def test_rejection_lies_inside_the_neutral_ring(vocabulary, weights) -> None:
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)
    by_id = {a.family_id: a for a in terms.axes}

    assert by_id["leisurely"].reader_radius < terms.neutral < by_id["harsh"].reader_radius


def test_a_spider_needs_three_axes(vocabulary, weights) -> None:
    """Zwei Achsen sind eine Linie, kein Netz — dann gibt es keine Spinne."""
    narrow = ReadingProfile(facets=(), counterweights=(), liked=(Liked("brooding"), Liked("quest")))

    terms, patterns = reader_spiders(form(vocabulary, weights, narrow), vocabulary)

    assert terms is None and patterns is None


def test_at_most_the_strongest_axes_are_drawn(vocabulary, weights) -> None:
    many = ReadingProfile(facets=(), counterweights=(), liked=tuple(
        Liked(f.id) for f in vocabulary.families if not vocabulary.is_pattern(f.id))[:20])

    terms, _ = reader_spiders(form(vocabulary, weights, many), vocabulary)

    assert len(terms.axes) == MOST_AXES


def test_the_points_lie_on_their_axes(vocabulary, weights) -> None:
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)
    first = terms.axes[0]

    # Die erste Achse zeigt nach oben.
    assert first.reader_point[0] == pytest.approx(terms.center)
    assert first.reader_point[1] == pytest.approx(terms.center - first.reader_radius)
    assert math.isclose(len(terms.reader_points.split()), len(terms.axes))


def test_the_book_lies_over_the_form(vocabulary, weights) -> None:
    book = Portrait(known=True, fingerprint="x", traits=(
        Trait("gritty", "S.", "wissen", "defining"),
        Trait("leisurely", "S.", "wissen", "clear"),
        Trait("lyrical", "S.", "wissen", "clear"),
        Trait("pursuit", "S.", "wissen"),
    ))

    terms, patterns = book_spiders(book, form(vocabulary, weights), vocabulary, weights)
    by_id = {a.family_id: a for a in terms.axes}

    # Was das Buch trägt, ragt über den neutralen Ring; was es nicht trägt, bleibt darauf.
    assert by_id["harsh"].book_radius > by_id["leisurely"].book_radius > terms.neutral
    assert by_id["menacing"].book_radius == pytest.approx(terms.neutral)
    # Worüber die Form nichts weiß, bekommt keine Achse — es zählt ja nicht (Z2).
    assert "lyrical" not in by_id
    assert terms.unknown == 1
    assert "pursuit" in {a.family_id for a in patterns.axes}


# --- auf den Seiten ------------------------------------------------------------------


def test_the_profile_page_draws_the_form(data_dir) -> None:
    from fastapi.testclient import TestClient

    from conftest import give_profile
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.store import Store
    from ebook_watchlist.web.app import create_app

    give_profile(Store(paths.db_path()), slug=load_settings().slug, profile=PROFILE)

    body = TestClient(create_app()).get("/profile").text

    assert 'data-spider="Merkmale"' in body and 'data-spider="Erzählmuster"' in body
    # Die Legende erklärt den Ring: außen gemocht, innen abgelehnt.
    assert "außen: gemocht" in body and "innen: abgelehnt" in body


def test_the_book_spider_shows_the_value_the_verdict_used(vocabulary, weights) -> None:
    """Die Spinne zeigt je Achse, womit das Urteil gerechnet hat: den Wert des
    Merkmals, das das Buch trägt — nicht den seiner Familie."""
    from ebook_watchlist.taste_form import TasteForm

    form = TasteForm(family={"harsh": 0.2, "brooding": 1.0, "menacing": 0.8},
                     term={"gritty": -0.5}, known=frozenset({"harsh", "brooding", "menacing"}))
    book = Portrait(known=True, fingerprint="x", traits=(Trait("gritty", "S.", "wissen"),))

    terms, _ = book_spiders(book, form, vocabulary, weights)

    assert {a.family_id: a.value for a in terms.axes}["harsh"] == -0.5


def test_unknown_families_are_counted_over_both_spiders(vocabulary, weights) -> None:
    from ebook_watchlist.web.spider import unknown_families

    book = Portrait(known=True, fingerprint="x", traits=(
        Trait("gritty", "S.", "wissen"), Trait("lyrical", "S.", "wissen"),
        Trait("revenge", "S.", "wissen"),
    ))

    assert unknown_families(book, form(vocabulary, weights), vocabulary, weights) == 2
