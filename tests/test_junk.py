"""Der Formfilter (ADR 19) — und vor allem, was er *nicht* wegwerfen darf.

Alle Titel hier stammen aus einem echten Lauf vom 2026-09-04. Der erste Entwurf
des Musters hat "Zahl am Anfang" als Bündelmerkmal genommen und wäre an genau
den Gegenbeispielen unten gescheitert.
"""

from __future__ import annotations

import pytest

from ebook_watchlist.junk import BUNDLE, EPISODE, FREE, is_junk, junk_reason
from ebook_watchlist.models import MatchReason, Observation


def shelf(title: str, price: int | None = 999) -> Observation:
    return Observation(
        source="beam",
        source_item_id="1",
        title=title,
        match_reason=MatchReason.GENRE_CATEGORY,
        price_cents=price,
    )


def by_author(title: str, price: int | None = 999) -> Observation:
    return Observation(
        source="beam",
        source_item_id="1",
        title=title,
        match_reason=MatchReason.PROFILE_AUTHOR,
        price_cents=price,
    )


# --- was Ramsch ist --------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "2 Gruselkrimis: Blutige Tränen / Tiberius Elroy und die Insel des Schreckens",
        "4 Spuk Thriller: Spinnenzauber, Knochenmänner und ein Geisterfalke",
        "Sammelband Standsville, USA - Drei Romane in einem Band",
        "Zwölfmal Dämonenhasser Tony Ballard - Sammelband",
        "Die Therapie & Amokspiel. Ein 2in1-Thriller-Bundle",
    ],
)
def test_a_bundle_on_a_shelf_is_junk(title: str) -> None:
    assert junk_reason(shelf(title)) == BUNDLE


def test_serial_episodes_are_junk_on_a_shelf() -> None:
    assert junk_reason(shelf("Die letzte Einheit - Episode 13: Unten die Erde")) == EPISODE


def test_free_is_junk_wherever_it_comes_from() -> None:
    assert junk_reason(shelf("Irgendwas", price=0)) == FREE
    assert junk_reason(by_author("Irgendwas", price=0)) == FREE


# --- was der Filter in Ruhe lassen muss ------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "5 Cottages - Haus der dunklen Geister",
        "7 Momente in Angst",
        "21 – Fremder Schatten",
        "28m² - Die Probandenstudie",
    ],
)
def test_a_title_that_merely_starts_with_a_number_survives(title: str) -> None:
    """Der Grund, warum das Muster nicht auf die Zahl allein hört."""
    assert not is_junk(shelf(title))


@pytest.mark.parametrize(
    "title",
    [
        "David Hunter: 3in1 Bundle",
        "Achtsam morden (5in1): Alle fünf Romane in einem Bundle",
    ],
)
def test_a_bundle_from_an_author_you_read_is_an_opportunity(title: str) -> None:
    """Simon Beckett und Karsten Dusse sind Referenzautor:innen. Eine Reihe am
    Stück zu bekommen ist genau das, was so jemand sucht — kein Ramsch."""
    assert not is_junk(by_author(title))
    assert is_junk(shelf(title))


def test_a_watchlist_title_is_never_junk() -> None:
    """Wer eine Gesamtausgabe beobachten will, darf das."""
    watched = Observation(
        source="beam",
        source_item_id="1",
        title="Krieg der Klone - Die Trilogie",
        match_reason=MatchReason.WATCHLIST,
        price_cents=1999,
    )
    assert not is_junk(watched)


def test_a_missing_price_is_not_the_same_as_free() -> None:
    assert not is_junk(shelf("Ein Titel", price=None))


# --- Kurzgeschichten (#73) -----------------------------------------------------------


def test_a_short_find_is_a_short_story() -> None:
    from dataclasses import replace

    from ebook_watchlist.junk import SHORT_STORY_PAGES, is_short_story

    assert is_short_story(replace(shelf("BattleTech - Onikuma"), pages=SHORT_STORY_PAGES - 1))
    assert not is_short_story(replace(shelf("Der Schwarm"), pages=SHORT_STORY_PAGES))


def test_without_a_page_count_only_the_title_can_say_short_story() -> None:
    from ebook_watchlist.junk import is_short_story

    assert not is_short_story(shelf("BattleTech - Onikuma"))


def test_a_title_that_says_short_story_is_one_even_without_pages() -> None:
    """„Der Wendepunkt — Eine David-Hunter-Kurzgeschichte" und „Die letzte
    Einheit, Episode 12" standen im Stapel (26.09.2026): beide von
    Autor:innen der Leserin, beide ohne Seitenzahl. Titel und Untertitel sagen
    es; der Klappentext nicht, der spricht von „über 100 Kurzgeschichten"."""
    from dataclasses import replace

    from ebook_watchlist.junk import is_short_story

    assert is_short_story(replace(by_author("Der Wendepunkt"),
                                  subtitle="Eine David-Hunter-Kurzgeschichte"))
    assert is_short_story(by_author(
        "Die letzte Einheit,  - Episode 12: Die kultivierte Kunst, Köpfe zu knacken -"))
    assert not is_short_story(replace(by_author("Die letzte Einheit"), subtitle="Roman",
                                      blurb="Er schrieb über 100 Kurzgeschichten."))


def test_a_short_title_she_chose_herself_stays() -> None:
    """Ein Watchlist-Titel geht immer durch, wie bei den Sammelbänden."""
    from dataclasses import replace

    from ebook_watchlist.junk import is_short_story

    itself = Observation(source="beam", source_item_id="1", title="Kurz",
                         match_reason=MatchReason.WATCHLIST, pages=40)
    assert not is_short_story(itself)
    assert is_short_story(replace(by_author("Kurz"), pages=40))
