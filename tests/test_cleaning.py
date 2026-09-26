"""Die Aufräumarbeit an dem, was die Quellen liefern (Ticket 16).

Jeder Fall unten stammt aus einem echten Lauf vom 2026-09-04.
"""

from __future__ import annotations

import pytest

from ebook_watchlist.cleaning import (
    author_key,
    clean_blurb,
    is_truncated,
    preferred_spelling,
    without_teaser,
)

# --- Klappentexte ----------------------------------------------------------


def test_the_shops_icon_ligature_never_reaches_the_reader() -> None:
    """Alle 316 Klappentexte eines Laufs endeten so."""
    raw = (
        "Mein Name ist Lea. Ich habe einen geheimnisvollen Beschützer. Doch seine "
        "Freundschaft ist tödlich... Mehr navigate_next"
    )
    cleaned = clean_blurb(raw)
    assert cleaned is not None
    assert "navigate_next" not in cleaned
    assert "Mehr" not in cleaned.split(".")[-1]
    assert cleaned.endswith("tödlich...")


def test_the_ellipsis_survives_because_the_text_really_is_cut_off() -> None:
    """Ein Torso darf nicht wie ein ganzer Klappentext aussehen."""
    cleaned = clean_blurb("Sydney wollte nur etwas Geld verdienen... Mehr navigate_next")
    assert cleaned == "Sydney wollte nur etwas Geld verdienen..."
    assert is_truncated(cleaned)


def test_a_ligature_in_the_middle_is_removed_too() -> None:
    assert clean_blurb("Erst dies navigate_next dann das") == "Erst dies dann das"


@pytest.mark.parametrize("blurb", [None, "", "   "])
def test_nothing_in_nothing_out(blurb: str | None) -> None:
    assert clean_blurb(blurb) is None


def test_a_clean_blurb_is_left_alone() -> None:
    text = "Ein Massaker auf Föhr und Sylt, wie auch mehrfache Grabschändungen."
    assert clean_blurb(text) == text
    assert not is_truncated(text)


# --- Schreibweisen ---------------------------------------------------------


def test_three_spellings_are_one_person() -> None:
    """So stand er im Snapshot: 33-mal, 15-mal und einmal."""
    assert author_key("Jo Nesbø") == author_key("Jo Nesbo") == author_key("Nesbø, Jo")


def test_the_spelling_with_the_diacritic_wins() -> None:
    assert preferred_spelling(["Jo Nesbo", "Jo Nesbø", "Nesbø, Jo"]) == "Jo Nesbø"


def test_given_name_first_beats_sort_order() -> None:
    assert preferred_spelling(["Dusse, Karsten", "Karsten Dusse"]) == "Karsten Dusse"
    assert preferred_spelling(["Scalzi, John", "John Scalzi"]) == "John Scalzi"


def test_frequency_does_not_decide() -> None:
    """Eine falsche Schreibweise wird nicht richtig, weil ein Shop sie
    häufiger verwendet — hier stünde 'Jo Nesbo' 15-mal gegen einmal."""
    assert preferred_spelling(["Jo Nesbo"] * 15 + ["Jo Nesbø"]) == "Jo Nesbø"


def test_the_choice_is_stable() -> None:
    names = ["Anna Meier", "Anna Meier"]
    assert preferred_spelling(names) == preferred_spelling(list(reversed(names)))


def test_two_different_people_stay_apart() -> None:
    """Was ``author_key`` trennt, führt keine Schreibweisenregel zusammen — die
    Stelle, an der das zählt, ist ``find_or_create_book`` (siehe test_store)."""
    assert author_key("Chris Carter") != author_key("Karsten Dusse")


def test_nothing_to_choose_from() -> None:
    assert preferred_spelling([]) is None


def test_the_cut_only_happens_where_the_text_really_repeats() -> None:
    """„alles anzeigen" kann auch Fliesstext sein. Ohne Probe schnitt die
    Regel mitten im Satz und warf den Anfang weg (Ticket 40)."""
    sentence = "Die Ausstellung will alles anzeigen, was die Stadt verbirgt."

    assert without_teaser(sentence) == sentence


def test_the_teaser_goes_where_the_full_text_repeats_it() -> None:
    doubled = "Der Anfang ... alles anzeigen expand_more Der Anfang und der Rest."

    assert without_teaser(doubled) == "Der Anfang und der Rest."


def test_the_collapse_label_goes_too() -> None:
    """Der Shop hat zwei Aufklapp-Knöpfe: einen vor dem vollen Text und einen
    dahinter. Ticket 40 hat den ersten erwischt; beim zweiten blieb nach dem
    Abstreifen der Ligatur die blosse Beschriftung stehen — in 110 von 2674
    gespeicherten Texten."""
    assert clean_blurb("Ein Satz. weniger anzeigen expand_less") == "Ein Satz."
    assert clean_blurb("Ein Satz. weniger anzeigen") == "Ein Satz."


def test_the_same_words_in_the_middle_of_a_sentence_stay() -> None:
    sentence = "Er wollte weniger anzeigen als nötig, und schwieg."

    assert clean_blurb(sentence) == sentence
