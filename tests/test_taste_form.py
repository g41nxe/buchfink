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
from ebook_watchlist.taste_form import RatedBook, TasteForm, book_terms, learn, overlap

pytestmark = needs_vocabulary


@pytest.fixture(scope="module")
def vocabulary():
    return load_vocabulary()


@pytest.fixture(scope="module")
def weights():
    return load_weights()


def portrait(*terms: str, genre: str | None = None, weights: dict | None = None) -> Portrait:
    return Portrait(
        known=True,
        fingerprint="probe",
        genre=genre,
        traits=tuple(
            Trait(t, f"Satz zu {t}.", "wissen", (weights or {}).get(t, CLEAR)) for t in terms
        ),
    )


def read_book(title: str, icons: int, portrait: Portrait, vocabulary, weights) -> RatedBook:
    return RatedBook(title, icons, book_terms(portrait, vocabulary, weights), portrait.genre)


#: Getippt: düster und hart gemocht, gemächlich dagegen.
TAPPED = ReadingProfile(
    facets=(Facet(("brooding", "harsh"), ("Leichenblässe", "Sharp Objects")),),
    counterweights=(Counterweight(("leisurely",), None, ("Herr der Ringe",)),),
    liked=(Liked("brooding"), Liked("harsh")),
)
THRILLER = portrait("brooding", "gritty", "menacing", "intensifying", genre="Thriller")
EPIC = portrait("world_building", "sweeping", "leisurely", "ensemble", genre="Fantasy")


def verdict(portrait, profile, rated, vocabulary, weights):
    form = learn(profile, rated, vocabulary, weights)
    return overlap(portrait, profile, form, vocabulary, weights)


# --- kein Urteil -----------------------------------------------------------------


def test_a_book_the_model_does_not_know_gets_no_judgement(vocabulary, weights) -> None:
    assert verdict(Portrait(known=False, fingerprint="x"), TAPPED, (), vocabulary, weights) is None


def test_a_form_that_knows_only_story_patterns_does_not_judge(vocabulary, weights) -> None:
    """Ohne ein einziges gemochtes Merkmal lässt sich das Wesentliche nicht
    beurteilen; zurückgehalten würde sonst jedes Buch (#78). Ein Fund ohne
    Urteil bleibt sichtbar (ADR 7)."""
    pattern_only = ReadingProfile(facets=(), counterweights=(), liked=(Liked("riddle"),))

    assert verdict(portrait("brooding", "riddle"), pattern_only, (), vocabulary, weights) is None


def test_without_anything_liked_there_is_no_judgement(vocabulary, weights) -> None:
    """Ohne Profil wird nicht geurteilt (ADR 33, Punkt 8)."""
    empty = ReadingProfile(facets=(), counterweights=())

    assert verdict(THRILLER, empty, (), vocabulary, weights) is None


# --- was die Form lernt -------------------------------------------------------------


def test_the_families_of_a_facet_start_as_liked(vocabulary, weights) -> None:
    """Eine Facette ist eine Kombination gemochter Merkmale: ein Profil, das nur
    Facetten kennt, urteilt trotzdem."""
    facet_only = ReadingProfile(facets=TAPPED.facets, counterweights=())

    assert verdict(portrait("brooding", "gritty"), facet_only, (), vocabulary, weights) is not None


def test_scaling_to_the_strongest_liking_does_not_break(vocabulary, weights) -> None:
    """``voll_ab_quantil: 1.0`` heißt: auf die stärkste Vorliebe skalieren. Der
    Index lief dabei eins hinter die Liste (Recherche zur Spinne, 26.09.2026)."""
    from dataclasses import replace

    strongest = replace(weights, full_quantile=1.0)
    otherland = read_book("Otherland", 1, portrait("world_building", "intricate"),
                          vocabulary, strongest)

    form = learn(TAPPED, (otherland,), vocabulary, strongest)

    assert max(form.family.values()) == pytest.approx(1.0)


def test_a_liked_book_lifts_what_it_carries(vocabulary, weights) -> None:
    book = portrait("world_building", "thought_provoking", "intricate")
    without = verdict(book, TAPPED, (), vocabulary, weights)
    otherland = read_book("Otherland", 1, book, vocabulary, weights)
    with_it = verdict(book, TAPPED, (otherland,), vocabulary, weights)

    assert with_it.share > without.share


def test_a_disappointing_book_pulls_down_what_it_carries(vocabulary, weights) -> None:
    liked = read_book("Leichenblässe", 1, THRILLER, vocabulary, weights)
    disappointed = read_book("Herr der Ringe", -1, EPIC, vocabulary, weights)
    book = portrait("brooding", "gritty", "sweeping", "ensemble")

    without = verdict(book, TAPPED, (liked,), vocabulary, weights)
    with_it = verdict(book, TAPPED, (liked, disappointed), vocabulary, weights)

    assert with_it.share < without.share


@pytest.mark.parametrize("averaged", [True, False])
def test_the_same_disappointing_book_twice_does_not_reject_twice(vocabulary, weights,
                                                                  averaged) -> None:
    """Gemittelt (Rocchio) wie beim Stärksten je Merkmal (MultiNeg): ein zweites
    gleiches enttäuschendes Buch ändert die Ablehnung nicht."""
    from dataclasses import replace

    weights = replace(weights, rejection_mean=averaged)
    liked = read_book("Leichenblässe", 1, THRILLER, vocabulary, weights)
    one = read_book("Herr der Ringe", -1, EPIC, vocabulary, weights)
    two = read_book("Das Rad der Zeit", -1, EPIC, vocabulary, weights)
    book = portrait("brooding", "gritty", "sweeping", "ensemble")

    once = verdict(book, TAPPED, (liked, one), vocabulary, weights)
    twice = verdict(book, TAPPED, (liked, one, two), vocabulary, weights)

    assert twice.share == pytest.approx(once.share, abs=0.05)


def test_the_weight_in_the_book_counts(vocabulary, weights) -> None:
    """Prägend zählt mehr als am Rand (Z3)."""
    defining = portrait("brooding", "sad", "dramatic", weights={"brooding": DEFINING})
    at_margin = portrait("brooding", "sad", "dramatic", weights={"brooding": MARGINAL})

    assert (
        verdict(defining, TAPPED, (), vocabulary, weights).share
        > verdict(at_margin, TAPPED, (), vocabulary, weights).share
    )


def test_what_the_form_knows_nothing_about_does_not_count_against(vocabulary, weights) -> None:
    """Familien, zu denen es keine Angabe gibt, zählen weder dafür noch dagegen (Z2)."""
    short = portrait("brooding", "gritty")
    long = portrait("brooding", "gritty", "lyrical", "romantic", "quirky")

    assert verdict(long, TAPPED, (), vocabulary, weights).share == pytest.approx(
        verdict(short, TAPPED, (), vocabulary, weights).share
    )


def test_a_thin_description_stays_careful(vocabulary, weights) -> None:
    """Ein einziges gemochtes Merkmal ist kein Beweis (Z6): es reicht nicht fürs Tor."""
    thin = portrait("brooding")

    assert verdict(thin, TAPPED, (), vocabulary, weights).stars < weights.gate_stars


def test_a_full_facet_adds_to_the_overlap(vocabulary, weights) -> None:
    without_facet = ReadingProfile(facets=(), counterweights=TAPPED.counterweights,
                                  liked=TAPPED.liked)
    book = portrait("brooding", "gritty", "menacing")

    assert (
        verdict(book, TAPPED, (), vocabulary, weights).share
        > verdict(book, without_facet, (), vocabulary, weights).share
    )


def test_a_genre_counterweight_only_counts_in_its_genre(vocabulary, weights) -> None:
    profile = ReadingProfile(
        facets=(),
        counterweights=(Counterweight(("big_world",), "Fantasy", ("Herr der Ringe",)),),
        liked=(Liked("big_world"), Liked("thought_provoking")),
    )
    fantasy = portrait("world_building", "thought_provoking", genre="Fantasy")
    sf = portrait("world_building", "thought_provoking", genre="Science-Fiction")

    assert (
        verdict(fantasy, profile, (), vocabulary, weights).share
        < verdict(sf, profile, (), vocabulary, weights).share
    )


def test_a_liked_story_pattern_lifts_the_book(vocabulary, weights) -> None:
    with_pattern = ReadingProfile(facets=(), counterweights=(),
                                liked=(Liked("brooding"), Liked("pursuit")))
    without_pattern = ReadingProfile(facets=(), counterweights=(), liked=(Liked("brooding"),))
    book = portrait("brooding", "gritty", "pursuit")

    assert (
        verdict(book, with_pattern, (), vocabulary, weights).share
        > verdict(book, without_pattern, (), vocabulary, weights).share
    )


# --- die Gründe der Leserin (Z10) ----------------------------------------------------


def test_what_the_reader_says_was_not_there_teaches_nothing(vocabulary, weights) -> None:
    """Der Schwarm: das Modell nennt ihn spannungsgeladen, die Leserin fand ihn
    gemächlich. Ohne ihr Wort lehrte das enttäuschende Buch, Spannung abzulehnen,
    die sie an einem gemochten Buch gelernt hat."""
    gripping = ReadingProfile(facets=(), counterweights=(), liked=TAPPED.liked)
    liked = read_book("Leichenblässe", 1, THRILLER, vocabulary, weights)
    swarm = portrait("intensifying", "world_building", "thought_provoking")
    as_described = read_book("Der Schwarm", -1, swarm, vocabulary, weights)
    as_experienced = RatedBook("Der Schwarm", -1, as_described.terms, None,
                           dropped=("nerve_racking",))
    book = portrait("intensifying", "menacing")

    without = verdict(book, gripping, (liked, as_described), vocabulary, weights)
    with_it = verdict(book, gripping, (liked, as_experienced), vocabulary, weights)

    assert with_it.share > without.share


def test_what_the_reader_adds_counts_against_like_a_defining_term(vocabulary, weights) -> None:
    liked = read_book("Leichenblässe", 1, THRILLER, vocabulary, weights)
    swarm = portrait("world_building", "thought_provoking")
    without_reason = read_book("Der Schwarm", -1, swarm, vocabulary, weights)
    with_reason = RatedBook("Der Schwarm", -1, without_reason.terms, None, added=("leisurely",))
    book = portrait("brooding", "gritty", "leisurely")
    profile = ReadingProfile(facets=(), counterweights=(), liked=TAPPED.liked)

    without = verdict(book, profile, (liked, without_reason), vocabulary, weights)
    with_it = verdict(book, profile, (liked, with_reason), vocabulary, weights)

    assert with_it.share < without.share
    assert "dagegen: gemächlich" in [z.line for z in with_it.reasons]


# --- die Begründung -------------------------------------------------------------------


def test_the_reason_names_the_facet_what_is_liked_and_what_is_against(vocabulary, weights) -> None:
    book = portrait("brooding", "gritty", "leisurely")
    lines = [z.line for z in verdict(book, TAPPED, (), vocabulary, weights).reasons if not z.detail]

    assert lines[0] == "gezeichnete Figur · hart"
    assert "dagegen: gemächlich" in lines


def test_the_reason_carries_the_sentence_from_the_portrait(vocabulary, weights) -> None:
    lines = verdict(portrait("brooding", "gritty"), TAPPED, (), vocabulary, weights).reasons

    assert any(z.detail and z.text == "Satz zu brooding." for z in lines)


def test_what_is_against_carries_its_sentence_like_a_facet(vocabulary, weights) -> None:
    result = verdict(portrait("brooding", "leisurely"), TAPPED, (), vocabulary, weights)
    lines = list(result.reasons)
    against = next(i for i, z in enumerate(lines) if z.kind == "dagegen")

    assert lines[against + 1].line == "Satz zu leisurely."


def test_a_family_the_vocabulary_forgot_does_not_break_the_reason(vocabulary, weights) -> None:
    """Die Familien sind ein Arbeitsstand; ein altes Profil bleibt lesbar."""
    old = ReadingProfile(
        facets=(Facet(("harsh", "gibtsnichtmehr")),),
        counterweights=(),
        liked=(Liked("harsh"), Liked("gibtsnichtmehr")),
    )

    lines = [z.line for z in verdict(THRILLER, old, (), vocabulary, weights).reasons]

    assert "hart" in lines


def test_a_genre_rule_names_its_genre(vocabulary, weights) -> None:
    profile = ReadingProfile(
        facets=(),
        counterweights=(Counterweight(("big_world",), "Fantasy", ("Herr der Ringe",)),),
        liked=(Liked("thought_provoking"),),
    )
    book = portrait("world_building", "thought_provoking", genre="Fantasy")

    lines = [z.line for z in verdict(book, profile, (), vocabulary, weights).reasons]

    assert "dagegen: große Welt (bei Fantasy)" in lines


def test_the_reason_says_when_nothing_liked_is_touched(vocabulary, weights) -> None:
    book = portrait("lyrical", "romantic", "leisurely")
    lines = [z.kind for z in verdict(book, TAPPED, (), vocabulary, weights).reasons]

    assert "keine" in lines


# --- das Schema ----------------------------------------------------------------------


def test_the_gate_threshold_is_read_from_the_rating_scheme(weights) -> None:
    assert weights.gate_stars == 3
    assert [s for s, _ in weights.stars_from] == [5, 4, 3, 2]


# --- aus dem Review (#79) -----------------------------------------------------------


MIXED = TasteForm(family={"harsh": 0.2, "brooding": 1.0},
                     term={"violent": 0.6, "gritty": -0.5}, known=frozenset({"harsh", "brooding"}))


@pytest.mark.parametrize("order", [("violent", "gritty"), ("gritty", "violent")])
def test_a_family_is_named_by_its_strongest_term(vocabulary, weights, order) -> None:
    """Nicht nach der Reihenfolge im Steckbrief: das stärkste Merkmal entscheidet."""
    book = portrait("brooding", *order)
    without_facet = ReadingProfile(facets=(), counterweights=(), liked=TAPPED.liked)
    lines = [z.line for z in overlap(book, without_facet, MIXED, vocabulary, weights).reasons]

    assert "hart" in lines and "dagegen: hart" not in lines


def test_an_added_family_the_book_already_carries_counts_once(vocabulary, weights) -> None:
    liked = read_book("Leichenblässe", 1, THRILLER, vocabulary, weights)
    doubled = RatedBook("Leichenblässe", 1, liked.terms, None, added=("brooding",))

    once = learn(TAPPED, (liked,), vocabulary, weights)
    twice = learn(TAPPED, (doubled,), vocabulary, weights)

    assert twice.family == once.family


# --- wie das Urteil entsteht (Wasserfall, 26.09.2026) --------------------------------


@pytest.mark.parametrize("book", [
    THRILLER,
    EPIC,
    portrait("brooding", "gritty", "leisurely", "pursuit", "quest", genre="Thriller"),
    portrait("leisurely", "lyrical"),
])
def test_the_steps_add_up_to_the_verdict(vocabulary, weights, book) -> None:
    """Die Buchseite zeigt, wie die Prozentzahl entsteht. Die Schritte kommen
    aus derselben Rechnung und ergeben genau das Urteil — nicht ungefähr."""
    liked_patterns = ReadingProfile(
        facets=TAPPED.facets, counterweights=TAPPED.counterweights,
        liked=(*TAPPED.liked, Liked("pursuit")),
    )

    result = verdict(book, liked_patterns, (), vocabulary, weights)

    assert result.steps[0].kind == "baseline"
    assert sum(s.delta for s in result.steps) == pytest.approx(result.share)


def test_each_family_of_the_book_is_one_step(vocabulary, weights) -> None:
    result = verdict(THRILLER, TAPPED, (), vocabulary, weights)
    families = [s.family for s in result.steps if s.kind == "family"]

    assert len(families) == len(set(families))
    assert "harsh" in families and "brooding" in families
    assert any(s.kind == "facet" for s in result.steps)
