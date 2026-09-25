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
def wort():
    return load_vocabulary()


@pytest.fixture(scope="module")
def gewichte():
    return load_weights()


PROFIL = ReadingProfile(
    facets=(Facet(("brooding", "harsh")),),
    counterweights=(Counterweight(("leisurely",)),),
    liked=(Liked("brooding"), Liked("harsh"), Liked("menacing"), Liked("thought_provoking"),
           Liked("pursuit"), Liked("quest"), Liked("escape")),
)


def form(wort, gewichte, profil=PROFIL):
    return learn(profil, (), wort, gewichte)


def test_the_form_is_drawn_as_two_spiders(wort, gewichte) -> None:
    merkmale, muster = reader_spiders(form(wort, gewichte), wort)

    assert {a.family_id for a in merkmale.axes} == {
        "brooding", "harsh", "menacing", "thought_provoking", "leisurely"}
    assert {a.family_id for a in muster.axes} == {"pursuit", "quest", "escape"}


def test_rejection_lies_inside_the_neutral_ring(wort, gewichte) -> None:
    merkmale, _ = reader_spiders(form(wort, gewichte), wort)
    by_id = {a.family_id: a for a in merkmale.axes}

    assert by_id["leisurely"].reader_radius < merkmale.neutral < by_id["harsh"].reader_radius


def test_a_spider_needs_three_axes(wort, gewichte) -> None:
    """Zwei Achsen sind eine Linie, kein Netz — dann gibt es keine Spinne."""
    schmal = ReadingProfile(facets=(), counterweights=(), liked=(Liked("brooding"), Liked("quest")))

    merkmale, muster = reader_spiders(form(wort, gewichte, schmal), wort)

    assert merkmale is None and muster is None


def test_at_most_the_strongest_axes_are_drawn(wort, gewichte) -> None:
    viele = ReadingProfile(facets=(), counterweights=(), liked=tuple(
        Liked(f.id) for f in wort.families if not wort.is_pattern(f.id))[:20])

    merkmale, _ = reader_spiders(form(wort, gewichte, viele), wort)

    assert len(merkmale.axes) == MOST_AXES


def test_the_points_lie_on_their_axes(wort, gewichte) -> None:
    merkmale, _ = reader_spiders(form(wort, gewichte), wort)
    first = merkmale.axes[0]

    # Die erste Achse zeigt nach oben.
    assert first.reader_point[0] == pytest.approx(merkmale.center)
    assert first.reader_point[1] == pytest.approx(merkmale.center - first.reader_radius)
    assert math.isclose(len(merkmale.reader_points.split()), len(merkmale.axes))


def test_the_book_lies_over_the_form(wort, gewichte) -> None:
    buch = Portrait(known=True, fingerprint="x", traits=(
        Trait("gritty", "S.", "wissen", "defining"),
        Trait("leisurely", "S.", "wissen", "clear"),
        Trait("lyrical", "S.", "wissen", "clear"),
        Trait("pursuit", "S.", "wissen"),
    ))

    merkmale, muster = book_spiders(buch, form(wort, gewichte), wort, gewichte)
    by_id = {a.family_id: a for a in merkmale.axes}

    # Was das Buch trägt, ragt über den neutralen Ring; was es nicht trägt, bleibt darauf.
    assert by_id["harsh"].book_radius > by_id["leisurely"].book_radius > merkmale.neutral
    assert by_id["menacing"].book_radius == pytest.approx(merkmale.neutral)
    # Worüber die Form nichts weiß, bekommt keine Achse — es zählt ja nicht (Z2).
    assert "lyrical" not in by_id
    assert merkmale.unknown == 1
    assert "pursuit" in {a.family_id for a in muster.axes}


# --- auf den Seiten ------------------------------------------------------------------


def test_the_profile_page_draws_the_form(data_dir) -> None:
    from fastapi.testclient import TestClient

    from conftest import give_profile
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.store import Store
    from ebook_watchlist.web.app import create_app

    give_profile(Store(paths.db_path()), slug=load_settings().slug, profile=PROFIL)

    body = TestClient(create_app()).get("/profile").text

    assert 'data-spider="Merkmale"' in body and 'data-spider="Erzählmuster"' in body
    assert "egal — innen" in body
