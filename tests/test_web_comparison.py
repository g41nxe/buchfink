"""Der Abgleich auf der Buchseite: was das Buch ist, was es von deinem Profil
abdeckt, wie das Urteil entsteht (26.09.2026, Prototypen A–G, gewählt: Wolke,
Brücke, Wasserfall)."""

from __future__ import annotations

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.facets import Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.judging import Judge
from ebook_watchlist.portrait import CLEAR, DEFINING, Portrait, Trait, fingerprint, load_vocabulary
from ebook_watchlist.taste_form import TasteForm
from ebook_watchlist.web.comparison import compare

pytestmark = needs_vocabulary


@pytest.fixture(scope="module")
def vocabulary():
    return load_vocabulary()


@pytest.fixture(scope="module")
def weights():
    return load_weights()


PROFILE = ReadingProfile(facets=(Facet(("brooding", "harsh")),), counterweights=(),
                         liked=(Liked("brooding"), Liked("harsh")))


def judge(vocabulary, weights, family, term=None):
    form = TasteForm(family=family, term=term or {}, known=frozenset(family))
    return Judge(PROFILE, vocabulary, weights, fingerprint(vocabulary), "t", form)


def book(*traits):
    return Portrait(known=True, fingerprint="x",
                    traits=tuple(Trait(t, f"Satz zu {t}.", "wissen", w) for t, w in traits))


def test_the_overview_groups_the_book_by_dimension(vocabulary, weights) -> None:
    j = judge(vocabulary, weights, {"harsh": 1.0, "leisurely": -0.8, "funny": 0.1})
    c = compare(book(("gritty", DEFINING), ("leisurely", CLEAR), ("amusing", CLEAR),
                     ("lyrical", CLEAR)), j)

    by_name = {p.family_id: p for g in c.groups for p in g.pills}
    assert by_name["harsh"].side == "for" and by_name["harsh"].weight_word == "prägend"
    assert by_name["leisurely"].side == "against"
    assert by_name["funny"].side == "indifferent"
    assert by_name["lyrical"].side == "unknown"
    tempo = next(g for g in c.groups if g.dimension == "Tempo")
    assert [p.family_id for p in tempo.pills] == ["leisurely"]


def test_the_bridge_shows_what_is_covered_and_what_is_missing(vocabulary, weights) -> None:
    j = judge(vocabulary, weights, {"harsh": 1.0, "brooding": 0.9, "menacing": 0.8,
                                    "leisurely": -0.8})
    c = compare(book(("gritty", DEFINING), ("leisurely", CLEAR)), j)

    mine = [row.family_id for row in c.bridge.mine]
    assert mine[:3] == ["harsh", "brooding", "menacing"] and mine[-1] == "leisurely"
    linked = {c.bridge.mine[a].family_id for a, _, _ in c.bridge.links}
    assert linked == {"harsh", "leisurely"}
    assert c.bridge.missing == ("gezeichnete Figur", "bedrohlich")


def test_the_waterfall_ends_at_the_verdict(vocabulary, weights) -> None:
    j = judge(vocabulary, weights, {"harsh": 1.0, "brooding": 0.9, "leisurely": -0.8})
    portrait = book(("gritty", DEFINING), ("brooding", CLEAR), ("leisurely", CLEAR))

    c = compare(portrait, j)

    assert c.waterfall[0].label == "Grundwert"
    assert c.waterfall[-1].end == pytest.approx(c.share)
    assert round(c.share * 100) == j.verdict(portrait).percent
    assert any(row.label == "Kombination getroffen" for row in c.waterfall)
    assert any(row.delta < 0 and row.label == "gemächlich" for row in c.waterfall)


def test_equal_values_at_the_cut_all_count(vocabulary, weights) -> None:
    """Acht Familien stehen bei +1,0 (die Krone): wer bei sieben abschneidet, lässt
    eine gleich starke Vorliebe zufällig weg — bei *Achtsam morden* ausgerechnet
    *figurengetrieben*, die das Buch trägt (26.09.2026)."""
    crown = ["harsh", "brooding", "menacing", "funny", "fast", "demanding", "sad", "dark"]
    j = judge(vocabulary, weights, {f: 1.0 for f in crown})
    c = compare(book(("gritty", CLEAR), ("bleak", CLEAR)), j)

    assert {row.family_id for row in c.bridge.mine} >= set(crown)
    assert {c.bridge.mine[a].family_id for a, _, _ in c.bridge.links} == {"harsh", "dark"}
