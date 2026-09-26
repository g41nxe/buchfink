"""Warum ein Buch angezeigt wird — in Worten (Ticket 14)."""

from __future__ import annotations

import pytest

from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.reasons import short_why, thema_name, why_shown


def observation(**overrides) -> Observation:
    defaults = dict(
        source="beam",
        source_item_id="1",
        title="Ein Titel",
        match_reason=MatchReason.GENRE_CATEGORY,
    )
    return Observation(**{**defaults, **overrides})


def test_a_watchlist_title_says_so() -> None:
    assert why_shown(observation(match_reason=MatchReason.WATCHLIST)) == (
        "steht auf deiner Watchlist"
    )


def test_an_author_reason_names_the_connection_to_the_reader() -> None:
    """"von Simon Beckett, dem du folgst" sagt mehr als "Autor:in"."""
    seen = observation(match_reason=MatchReason.PROFILE_AUTHOR, author="Simon Beckett")
    assert why_shown(seen) == "neu von Simon Beckett, der du folgst"


def test_an_author_reason_without_a_name_still_reads() -> None:
    seen = observation(match_reason=MatchReason.PROFILE_AUTHOR, author=None)
    assert why_shown(seen) == "neu von einer Autor:in, der du folgst"


def test_the_reader_facing_word_is_thema_not_regal() -> None:
    seen = observation(category="belletristik/krimi-thriller/psychothriller")
    assert why_shown(seen) == "neu im Thema Psychothriller"


def test_the_raw_shelf_path_never_reaches_the_reader() -> None:
    seen = observation(category="belletristik/krimi-thriller/psychothriller")
    assert "belletristik" not in why_shown(seen)


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("belletristik/horror-mystery/horror-mystery-allgemein", "Horror & Mystery"),
        ("belletristik/science-fiction/space-opera", "Space Opera"),
        ("/belletristik/science-fiction/military-sf/", "Military SF"),
        # Unbekanntes wird lesbar gemacht, nicht geraten.
        ("belletristik/krimi-thriller/regionalkrimi", "Regionalkrimi"),
        ("belletristik/etwas/ganz-neues-hier", "Ganz neues hier"),
        (None, None),
        ("", None),
    ],
)
def test_a_shelf_path_becomes_a_readable_name(category: str | None, expected: str) -> None:
    assert thema_name(category) == expected


def test_a_theme_without_a_category_does_not_pretend_to_know_one() -> None:
    assert why_shown(observation(category=None)) == "neu in einem Thema, dem du folgst"


def test_the_short_form_fits_a_label() -> None:
    """Die Pille nennt das Thema selbst, ohne das Wort "Thema" davor — die
    Farbe (Bernstein) sagt in ihrem Kontext schon, dass es eines ist."""
    assert short_why(observation(match_reason=MatchReason.WATCHLIST)) == "Watchlist"
    assert short_why(observation(match_reason=MatchReason.PROFILE_AUTHOR)) == "Autor:in"
    assert short_why(observation(category="a/b/psychothriller")) == "Psychothriller"


def test_the_short_form_falls_back_to_thema_without_a_readable_name() -> None:
    """Ohne Kategorie bleibt "Thema" die einzig ehrliche Auskunft."""
    assert short_why(observation(category=None)) == "Thema"


def test_a_library_collection_keeps_its_name_and_says_it_can_be_borrowed() -> None:
    """Lucky Day ist kein Shop-Pfad, sondern ein Name — und die Sammlung einer
    Bibliothek heißt: sofort ausleihbar (#74)."""
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.reasons import short_why, why_shown

    fund = Observation(source="overdrive", source_item_id="1", title="Der Hausmann",
                       match_reason=MatchReason.GENRE_CATEGORY, category="Lucky Day")

    assert short_why(fund) == "Lucky Day"
    assert why_shown(fund) == "sofort ausleihbar aus „Lucky Day“"
