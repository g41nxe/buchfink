"""Die Spinnen: die Geschmacksform im Kreis, das Buch darübergelegt (#79).

Seit dem 26.09.2026 vollständig: jede Familie hat einen festen Platz, die
Plätze stehen in Sektoren je Dimension, und statt einer Fläche zeigt ein Balken
je Familie, wie gemocht oder abgelehnt sie ist (docs/research/spinne-darstellung.md).
"""

from __future__ import annotations

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.taste_form import TasteForm, learn
from ebook_watchlist.web.spider import SECTOR_ORDER, book_spiders, reader_spiders

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


def places(spider):
    return {p.family_id: p for p in spider.places}


def order(spider, sector):
    return [p.family_id for p in spider.places if p.sector == sector]


# --- jede Familie hat ihren Platz -----------------------------------------------------


def test_every_family_has_a_place_known_or_not(vocabulary, weights) -> None:
    """Eine Spinne, der Achsen fehlen, täuscht Vollständigkeit vor (26.09.2026)."""
    terms, patterns = reader_spiders(form(vocabulary, weights), vocabulary)
    trait_families = {vocabulary.family_of(t).id for t in vocabulary.terms
                      if not vocabulary.is_pattern(vocabulary.family_of(t).id)}
    pattern_families = {vocabulary.family_of(t).id for t in vocabulary.terms
                        if vocabulary.is_pattern(vocabulary.family_of(t).id)}

    assert set(places(terms)) == trait_families
    assert set(places(patterns)) == pattern_families
    known = {p.family_id for p in terms.places if p.known}
    assert known == {"brooding", "harsh", "menacing", "thought_provoking", "leisurely"}


def test_an_unknown_family_is_an_empty_place_not_indifference(vocabulary, weights) -> None:
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)
    unknown = places(terms)["funny"]

    assert not unknown.known and unknown.bar_to is None and unknown.dot is None


def test_the_sectors_follow_the_dimensions_in_a_fixed_order(vocabulary, weights) -> None:
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)

    assert [s.name for s in terms.sectors] == list(SECTOR_ORDER)
    angles = [p.angle for p in terms.places]
    assert angles == sorted(angles) and 0 < angles[0] and angles[-1] < 360


def test_a_family_of_two_dimensions_stands_at_their_border(vocabulary, weights) -> None:
    """*rasant* (Tempo und Handlung) am Ende von Tempo, *anspruchsvoll* (Stil und
    Handlung) am Anfang von Stil — neben der Dimension, zu der es auch gehört."""
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)

    assert order(terms, "Tempo")[-1] == "fast"
    assert order(terms, "Stil")[0] == "demanding"


def test_opposites_stand_side_by_side(vocabulary, weights) -> None:
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)
    tempo = order(terms, "Tempo")
    style = order(terms, "Stil")

    assert abs(tempo.index("fast") - tempo.index("leisurely")) == 1
    assert abs(style.index("demanding") - style.index("casual")) == 1


# --- Balken statt Fläche --------------------------------------------------------------


def test_liking_goes_out_and_rejection_goes_in(vocabulary, weights) -> None:
    terms, _ = reader_spiders(form(vocabulary, weights), vocabulary)
    liked, rejected = places(terms)["harsh"], places(terms)["leisurely"]

    assert liked.bar_radius > terms.r_zero > rejected.bar_radius
    assert liked.tone == "accent" and rejected.tone == "danger"


def test_a_trait_is_marked_only_where_it_contradicts_its_family(vocabulary) -> None:
    """Abstufungen sagen „etwas weniger als die Familie" und blieben Unordnung;
    ein Widerspruch sagt, dass der Balken für dieses Wort nicht stimmt."""
    known = frozenset({"big_world", "funny", "brooding", "harsh"})
    taste = TasteForm(
        family={"big_world": -0.4, "funny": 1.0, "brooding": 0.8, "harsh": 0.5},
        term={"world_building": 0.3, "amusing": 0.58},
        known=known,
    )

    terms, _ = reader_spiders(taste, vocabulary)

    assert len(places(terms)["big_world"].ticks) == 1
    assert places(terms)["funny"].ticks == ()


def test_too_little_known_draws_no_spider(vocabulary, weights) -> None:
    narrow = ReadingProfile(facets=(), counterweights=(), liked=(Liked("brooding"), Liked("quest")))

    terms, patterns = reader_spiders(form(vocabulary, weights, narrow), vocabulary)

    assert terms is None and patterns is None


# --- das Buch darüber ------------------------------------------------------------------


def test_the_book_is_a_track_outside_the_rim(vocabulary, weights) -> None:
    book = Portrait(known=True, fingerprint="x", traits=(
        Trait("gritty", "S.", "wissen", "defining"),
        Trait("leisurely", "S.", "wissen", "clear"),
        Trait("lyrical", "S.", "wissen", "clear"),
        Trait("pursuit", "S.", "wissen"),
    ))

    terms, patterns = book_spiders(book, form(vocabulary, weights), vocabulary, weights)
    by_id = places(terms)

    # Getragen: eine Spur außen, je länger, desto stärker.
    assert by_id["harsh"].track_length > by_id["leisurely"].track_length > 0
    # Nicht getragen: keine Spur, der Balken tritt zurück.
    assert by_id["menacing"].track_length == 0 and by_id["menacing"].dimmed
    # Getragen, aber der Form unbekannt: ein hohler Kreis, und es zählt nicht.
    assert by_id["lyrical"].hollow is not None and terms.unknown == 1
    assert places(patterns)["pursuit"].carried


def test_the_bar_keeps_the_family_value_and_a_tick_shows_the_verdicts(vocabulary, weights) -> None:
    """Dieselbe Familie sieht auf Profil- und Buchseite gleich aus (Qu & Hullman);
    womit das Urteil rechnete, zeigt ein Querstrich, wo es abweicht."""
    taste = TasteForm(family={"harsh": 0.2, "brooding": 1.0, "menacing": 0.8},
                      term={"gritty": -0.5}, known=frozenset({"harsh", "brooding", "menacing"}))
    book = Portrait(known=True, fingerprint="x", traits=(Trait("gritty", "S.", "wissen"),))

    terms, _ = book_spiders(book, taste, vocabulary, weights)
    harsh = places(terms)["harsh"]

    assert harsh.value == pytest.approx(0.2)
    assert harsh.verdict_value == pytest.approx(-0.5) and harsh.verdict_tick is not None


def test_unknown_families_are_counted_over_both_spiders(vocabulary, weights) -> None:
    from ebook_watchlist.web.spider import unknown_families

    book = Portrait(known=True, fingerprint="x", traits=(
        Trait("gritty", "S.", "wissen"), Trait("lyrical", "S.", "wissen"),
        Trait("revenge", "S.", "wissen"),
    ))

    assert unknown_families(book, form(vocabulary, weights), vocabulary, weights) == 2


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
    # Die Legende erklärt die Balken und den leeren Platz.
    assert "nach außen: gemocht" in body and "noch unbekannt" in body
    # Auf dem Telefon die Liste darunter, nach Dimension.
    assert "data-spider-list" in body
