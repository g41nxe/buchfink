"""Die Geschmacksform und die Formüberdeckung (#79, docs/research/urteil-methode.md).

Die Form wird aus den bewerteten Büchern der Leserin gelernt, das Getippte ist
der Startwert. Geprüft wird das Verhalten, das die Ziele Z1 bis Z12 verlangen,
nicht einzelne Prozentzahlen: die Parameter stehen im Bewertungsschema und
dürfen sich ändern.
"""

from __future__ import annotations

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.portrait import CLEAR, DEFINING, MARGINAL, Portrait, Trait, load_vocabulary
from ebook_watchlist.taste_form import RatedBook, book_terms, learn, overlap

pytestmark = needs_vocabulary


@pytest.fixture(scope="module")
def wort():
    return load_vocabulary()


@pytest.fixture(scope="module")
def gewichte():
    return load_weights()


def steckbrief(*terms: str, genre: str | None = None, weights: dict | None = None) -> Portrait:
    return Portrait(
        known=True,
        fingerprint="probe",
        genre=genre,
        traits=tuple(
            Trait(t, f"Satz zu {t}.", "wissen", (weights or {}).get(t, CLEAR)) for t in terms
        ),
    )


def gelesen(titel: str, zeichen: int, portrait: Portrait, wort, gewichte) -> RatedBook:
    return RatedBook(titel, zeichen, book_terms(portrait, wort, gewichte), portrait.genre)


#: Getippt: düster und hart gemocht, gemächlich dagegen.
GETIPPT = ReadingProfile(
    facets=(Facet(("brooding", "harsh"), ("Leichenblässe", "Sharp Objects")),),
    counterweights=(Counterweight(("leisurely",), None, ("Herr der Ringe",)),),
    liked=(Liked("brooding"), Liked("harsh")),
)
THRILLER = steckbrief("brooding", "gritty", "menacing", "intensifying", genre="Thriller")
EPOS = steckbrief("world_building", "sweeping", "leisurely", "ensemble", genre="Fantasy")


def urteil(portrait, profil, rated, wort, gewichte):
    return overlap(portrait, profil, learn(profil, rated, wort, gewichte), wort, gewichte)


# --- kein Urteil -----------------------------------------------------------------


def test_a_book_the_model_does_not_know_gets_no_judgement(wort, gewichte) -> None:
    assert urteil(Portrait(known=False, fingerprint="x"), GETIPPT, (), wort, gewichte) is None


def test_a_form_that_knows_only_story_patterns_does_not_judge(wort, gewichte) -> None:
    """Ohne ein einziges gemochtes Merkmal lässt sich das Wesentliche nicht
    beurteilen; zurückgehalten würde sonst jedes Buch (#78). Ein Fund ohne
    Urteil bleibt sichtbar (ADR 7)."""
    nur_muster = ReadingProfile(facets=(), counterweights=(), liked=(Liked("riddle"),))

    assert urteil(steckbrief("brooding", "riddle"), nur_muster, (), wort, gewichte) is None


def test_without_anything_liked_there_is_no_judgement(wort, gewichte) -> None:
    """Ohne Profil wird nicht geurteilt (ADR 33, Punkt 8)."""
    leer = ReadingProfile(facets=(), counterweights=())

    assert urteil(THRILLER, leer, (), wort, gewichte) is None


# --- was die Form lernt -------------------------------------------------------------


def test_the_families_of_a_facet_start_as_liked(wort, gewichte) -> None:
    """Eine Facette ist eine Kombination gemochter Merkmale: ein Profil, das nur
    Facetten kennt, urteilt trotzdem."""
    nur_facette = ReadingProfile(facets=GETIPPT.facets, counterweights=())

    assert urteil(steckbrief("brooding", "gritty"), nur_facette, (), wort, gewichte) is not None


def test_a_liked_book_lifts_what_it_carries(wort, gewichte) -> None:
    buch = steckbrief("world_building", "thought_provoking", "intricate")
    ohne = urteil(buch, GETIPPT, (), wort, gewichte)
    mit = urteil(buch, GETIPPT, (gelesen("Otherland", 1, buch, wort, gewichte),), wort, gewichte)

    assert mit.share > ohne.share


def test_a_disappointing_book_pulls_down_what_it_carries(wort, gewichte) -> None:
    gemocht = gelesen("Leichenblässe", 1, THRILLER, wort, gewichte)
    enttaeuscht = gelesen("Herr der Ringe", -1, EPOS, wort, gewichte)
    buch = steckbrief("brooding", "gritty", "sweeping", "ensemble")

    ohne = urteil(buch, GETIPPT, (gemocht,), wort, gewichte)
    mit = urteil(buch, GETIPPT, (gemocht, enttaeuscht), wort, gewichte)

    assert mit.share < ohne.share


@pytest.mark.parametrize("gemittelt", [True, False])
def test_the_same_disappointing_book_twice_does_not_reject_twice(wort, gewichte,
                                                                  gemittelt) -> None:
    """Gemittelt (Rocchio) wie beim Stärksten je Merkmal (MultiNeg): ein zweites
    gleiches enttäuschendes Buch ändert die Ablehnung nicht."""
    from dataclasses import replace

    gewichte = replace(gewichte, rejection_mean=gemittelt)
    gemocht = gelesen("Leichenblässe", 1, THRILLER, wort, gewichte)
    eins = gelesen("Herr der Ringe", -1, EPOS, wort, gewichte)
    zwei = gelesen("Das Rad der Zeit", -1, EPOS, wort, gewichte)
    buch = steckbrief("brooding", "gritty", "sweeping", "ensemble")

    einmal = urteil(buch, GETIPPT, (gemocht, eins), wort, gewichte)
    zweimal = urteil(buch, GETIPPT, (gemocht, eins, zwei), wort, gewichte)

    assert zweimal.share == pytest.approx(einmal.share, abs=0.05)


def test_the_weight_in_the_book_counts(wort, gewichte) -> None:
    """Prägend zählt mehr als am Rand (Z3)."""
    praegend = steckbrief("brooding", "sad", "dramatic", weights={"brooding": DEFINING})
    am_rand = steckbrief("brooding", "sad", "dramatic", weights={"brooding": MARGINAL})

    assert (
        urteil(praegend, GETIPPT, (), wort, gewichte).share
        > urteil(am_rand, GETIPPT, (), wort, gewichte).share
    )


def test_what_the_form_knows_nothing_about_does_not_count_against(wort, gewichte) -> None:
    """Familien, zu denen es keine Angabe gibt, zählen weder dafür noch dagegen (Z2)."""
    kurz = steckbrief("brooding", "gritty")
    lang = steckbrief("brooding", "gritty", "lyrical", "romantic", "quirky")

    assert urteil(lang, GETIPPT, (), wort, gewichte).share == pytest.approx(
        urteil(kurz, GETIPPT, (), wort, gewichte).share
    )


def test_a_thin_description_stays_careful(wort, gewichte) -> None:
    """Ein einziges gemochtes Merkmal ist kein Beweis (Z6): es reicht nicht fürs Tor."""
    duenn = steckbrief("brooding")

    assert urteil(duenn, GETIPPT, (), wort, gewichte).stars < gewichte.gate_stars


def test_a_full_facet_adds_to_the_overlap(wort, gewichte) -> None:
    ohne_facette = ReadingProfile(facets=(), counterweights=GETIPPT.counterweights,
                                  liked=GETIPPT.liked)
    buch = steckbrief("brooding", "gritty", "menacing")

    assert (
        urteil(buch, GETIPPT, (), wort, gewichte).share
        > urteil(buch, ohne_facette, (), wort, gewichte).share
    )


def test_a_genre_counterweight_only_counts_in_its_genre(wort, gewichte) -> None:
    profil = ReadingProfile(
        facets=(),
        counterweights=(Counterweight(("big_world",), "Fantasy", ("Herr der Ringe",)),),
        liked=(Liked("big_world"), Liked("thought_provoking")),
    )
    fantasy = steckbrief("world_building", "thought_provoking", genre="Fantasy")
    sf = steckbrief("world_building", "thought_provoking", genre="Science-Fiction")

    assert (
        urteil(fantasy, profil, (), wort, gewichte).share
        < urteil(sf, profil, (), wort, gewichte).share
    )


def test_a_liked_story_pattern_lifts_the_book(wort, gewichte) -> None:
    mit_muster = ReadingProfile(facets=(), counterweights=(),
                                liked=(Liked("brooding"), Liked("pursuit")))
    ohne_muster = ReadingProfile(facets=(), counterweights=(), liked=(Liked("brooding"),))
    buch = steckbrief("brooding", "gritty", "pursuit")

    assert (
        urteil(buch, mit_muster, (), wort, gewichte).share
        > urteil(buch, ohne_muster, (), wort, gewichte).share
    )


# --- die Gründe der Leserin (Z10) ----------------------------------------------------


def test_what_the_reader_says_was_not_there_teaches_nothing(wort, gewichte) -> None:
    """Der Schwarm: das Modell nennt ihn spannungsgeladen, die Leserin fand ihn
    gemächlich. Ohne ihr Wort lehrte das enttäuschende Buch, Spannung abzulehnen,
    die sie an einem gemochten Buch gelernt hat."""
    spannend = ReadingProfile(facets=(), counterweights=(), liked=GETIPPT.liked)
    gemocht = gelesen("Leichenblässe", 1, THRILLER, wort, gewichte)
    schwarm = steckbrief("intensifying", "world_building", "thought_provoking")
    wie_beschrieben = gelesen("Der Schwarm", -1, schwarm, wort, gewichte)
    wie_erlebt = RatedBook("Der Schwarm", -1, wie_beschrieben.terms, None,
                           dropped=("nerve_racking",))
    buch = steckbrief("intensifying", "menacing")

    ohne = urteil(buch, spannend, (gemocht, wie_beschrieben), wort, gewichte)
    mit = urteil(buch, spannend, (gemocht, wie_erlebt), wort, gewichte)

    assert mit.share > ohne.share


def test_what_the_reader_adds_counts_against_like_a_defining_term(wort, gewichte) -> None:
    gemocht = gelesen("Leichenblässe", 1, THRILLER, wort, gewichte)
    schwarm = steckbrief("world_building", "thought_provoking")
    ohne_grund = gelesen("Der Schwarm", -1, schwarm, wort, gewichte)
    mit_grund = RatedBook("Der Schwarm", -1, ohne_grund.terms, None, added=("leisurely",))
    buch = steckbrief("brooding", "gritty", "leisurely")
    profil = ReadingProfile(facets=(), counterweights=(), liked=GETIPPT.liked)

    ohne = urteil(buch, profil, (gemocht, ohne_grund), wort, gewichte)
    mit = urteil(buch, profil, (gemocht, mit_grund), wort, gewichte)

    assert mit.share < ohne.share
    assert "dagegen: gemächlich" in [z.line for z in mit.reasons]


# --- die Begründung -------------------------------------------------------------------


def test_the_reason_names_the_facet_what_is_liked_and_what_is_against(wort, gewichte) -> None:
    buch = steckbrief("brooding", "gritty", "leisurely")
    zeilen = [z.line for z in urteil(buch, GETIPPT, (), wort, gewichte).reasons if not z.detail]

    assert zeilen[0] == "gezeichnete Figur · hart"
    assert "dagegen: gemächlich" in zeilen


def test_the_reason_carries_the_sentence_from_the_portrait(wort, gewichte) -> None:
    zeilen = urteil(steckbrief("brooding", "gritty"), GETIPPT, (), wort, gewichte).reasons

    assert any(z.detail and z.text == "Satz zu brooding." for z in zeilen)


def test_what_is_against_carries_its_sentence_like_a_facet(wort, gewichte) -> None:
    zeilen = list(urteil(steckbrief("brooding", "leisurely"), GETIPPT, (), wort, gewichte).reasons)
    dagegen = next(i for i, z in enumerate(zeilen) if z.kind == "dagegen")

    assert zeilen[dagegen + 1].line == "Satz zu leisurely."


def test_a_family_the_vocabulary_forgot_does_not_break_the_reason(wort, gewichte) -> None:
    """Die Familien sind ein Arbeitsstand; ein altes Profil bleibt lesbar."""
    alt = ReadingProfile(
        facets=(Facet(("harsh", "gibtsnichtmehr")),),
        counterweights=(),
        liked=(Liked("harsh"), Liked("gibtsnichtmehr")),
    )

    zeilen = [z.line for z in urteil(THRILLER, alt, (), wort, gewichte).reasons]

    assert "hart" in zeilen


def test_a_genre_rule_names_its_genre(wort, gewichte) -> None:
    profil = ReadingProfile(
        facets=(),
        counterweights=(Counterweight(("big_world",), "Fantasy", ("Herr der Ringe",)),),
        liked=(Liked("thought_provoking"),),
    )
    buch = steckbrief("world_building", "thought_provoking", genre="Fantasy")

    zeilen = [z.line for z in urteil(buch, profil, (), wort, gewichte).reasons]

    assert "dagegen: große Welt (bei Fantasy)" in zeilen


def test_the_reason_says_when_nothing_liked_is_touched(wort, gewichte) -> None:
    buch = steckbrief("lyrical", "romantic", "leisurely")
    zeilen = [z.kind for z in urteil(buch, GETIPPT, (), wort, gewichte).reasons]

    assert "keine" in zeilen


# --- das Schema ----------------------------------------------------------------------


def test_the_gate_threshold_is_read_from_the_rating_scheme(gewichte) -> None:
    assert gewichte.gate_stars == 3
    assert [s for s, _ in gewichte.stars_from] == [5, 4, 3, 2]
