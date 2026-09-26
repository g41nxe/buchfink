"""Wonach die beiden Listen sortieren (#37).

Geprüft wird die Reihenfolge selbst, nicht die Seite: die Schlüssel sind reine
Vergleichsfunktionen, und was sie tun, soll ohne HTTP-Client nachlesbar sein.
Dass die Wahl auch in der Oberfläche ankommt, steht in ``test_web_watchlist``
und ``test_web_triage``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from ebook_watchlist.web import sorting


@dataclass(frozen=True)
class Row:
    """Genau die Felder, die ein Schlüssel anfasst."""

    title: str
    needs_attention: bool = False
    borrowable: bool = False
    price_cents: int | None = None
    added_at: datetime | None = None
    observed_at: datetime | None = None
    percent: int | None = None
    reason: str = "genre_category"


def names(orders, rows, slug):
    return [row.title for row in sorting.apply(orders, rows, slug)]


def test_the_default_is_the_first_order_of_the_list():
    """Die Voreinstellung ist ein benannter Eintrag, kein Sonderfall daneben."""
    assert sorting.resolve(sorting.WATCHLIST, None) is sorting.WATCHLIST[0]
    assert sorting.resolve(sorting.SUGGESTIONS, None) is sorting.SUGGESTIONS[0]


def test_an_unknown_key_falls_back_instead_of_failing():
    """Ein Tippfehler in der Adresse ist kein Grund, die Liste zu verweigern
    (ADR 7)."""
    assert sorting.resolve(sorting.WATCHLIST, "gibtsnicht") is sorting.WATCHLIST[0]


def test_the_default_stays_out_of_the_address():
    """Sonst hängt `?sortiert=offen` an jedem Verweis der Seite."""
    order, in_the_address = sorting.chosen(sorting.WATCHLIST, None)

    assert order is sorting.WATCHLIST[0]
    assert in_the_address == ""


def test_a_chosen_key_belongs_in_the_address():
    order, in_the_address = sorting.chosen(sorting.WATCHLIST, "preis")

    assert order.slug == "preis"
    assert in_the_address == "preis"


def test_both_lists_name_price_and_availability_alike():
    """Was gleich heißt, soll gleich heißen — in beiden Listen."""
    watchlist = {order.slug: order.label for order in sorting.WATCHLIST}
    suggestions = {order.slug: order.label for order in sorting.SUGGESTIONS}
    for slug in ("preis", "frei"):
        assert watchlist[slug] == suggestions[slug]


def test_every_key_has_its_own_slug():
    for orders in (sorting.WATCHLIST, sorting.SUGGESTIONS):
        slugs = [order.slug for order in orders]
        assert len(slugs) == len(set(slugs))


# --- Watchlist ---------------------------------------------------------


def test_the_default_puts_open_assignments_first_then_the_title():
    rows = [
        Row("Zenit"),
        Row("Anfang"),
        Row("Mitte", needs_attention=True),
    ]
    assert names(sorting.WATCHLIST, rows, "offen") == ["Mitte", "Anfang", "Zenit"]


def test_sorting_by_price_ignores_that_something_is_open():
    """Die gewählte Reihenfolge gilt wörtlich.

    Das ist die Entscheidung des Tickets: ein offener Eintrag steht dann
    mittendrin. Verloren geht er nicht — die Leiste über der Liste zählt ihn
    und filtert auf ihn.
    """
    rows = [
        Row("Teuer", price_cents=1999),
        Row("Offen und teuer", needs_attention=True, price_cents=2999),
        Row("Billig", price_cents=199),
    ]
    assert names(sorting.WATCHLIST, rows, "preis") == [
        "Billig",
        "Teuer",
        "Offen und teuer",
    ]


def test_a_title_without_a_price_goes_last_not_first():
    """Kein Preis ist nicht null Euro.

    Eine Bibliothek nennt keinen; mit 0 Cent stünde sie vor jedem Schnäppchen
    und behauptete etwas, das niemand gesagt hat.
    """
    rows = [Row("Ohne"), Row("Mit", price_cents=499)]
    assert names(sorting.WATCHLIST, rows, "preis") == ["Mit", "Ohne"]


def test_borrowable_titles_come_first():
    rows = [Row("Verliehen"), Row("Frei", borrowable=True)]
    assert names(sorting.WATCHLIST, rows, "frei") == ["Frei", "Verliehen"]


def test_the_newest_addition_is_on_top():
    rows = [
        Row("Alt", added_at=datetime(2026, 1, 1)),
        Row("Neu", added_at=datetime(2026, 9, 1)),
        Row("Mittel", added_at=datetime(2026, 5, 1)),
    ]
    assert names(sorting.WATCHLIST, rows, "neu") == ["Neu", "Mittel", "Alt"]


def test_a_row_without_a_timestamp_goes_last_not_first():
    """"Kein Zeitpunkt" ist nicht "uralt".

    Ohne diesen Rang landete eine Zeile ohne Auskunft am einen oder anderen
    Ende der Reihe, je nachdem wie man den fehlenden Wert ersetzt — und das
    ist genau die Sorte Zufall, die das Ticket beenden soll.
    """
    rows = [Row("Ohne"), Row("Mit", added_at=datetime(2026, 1, 1))]
    assert names(sorting.WATCHLIST, rows, "neu") == ["Mit", "Ohne"]


def test_the_title_breaks_every_tie():
    """Darum gibt es "Titel" nicht als eigene Wahl."""
    for slug in (order.slug for order in sorting.WATCHLIST):
        rows = [Row("beta"), Row("Alpha")]
        assert names(sorting.WATCHLIST, rows, slug) == ["Alpha", "beta"]


# --- Vorschläge --------------------------------------------------------


def test_the_stack_shows_the_best_match_first_and_the_unjudged_last():
    """Die Zahl ordnet, die Sterne fassen zusammen (ADR 33): zwei Bücher mit
    denselben fünf Sternen stehen nach ihrer Prozentzahl."""
    rows = [
        Row("Ohne Urteil"),
        Row("Drei", percent=51),
        Row("Fuenf tiefer", percent=82),
        Row("Fuenf hoeher", percent=97),
    ]
    assert names(sorting.SUGGESTIONS, rows, "sterne") == [
        "Fuenf hoeher",
        "Fuenf tiefer",
        "Drei",
        "Ohne Urteil",
    ]


def test_the_author_channel_comes_before_the_shelf():
    rows = [
        Row("Thema", reason="genre_category"),
        Row("Autorin", reason="profile_author"),
    ]
    assert names(sorting.SUGGESTIONS, rows, "anlass") == ["Autorin", "Thema"]


def test_the_last_seen_find_is_on_top():
    rows = [
        Row("Gestern", observed_at=datetime(2026, 9, 21)),
        Row("Heute", observed_at=datetime(2026, 9, 22)),
    ]
    assert names(sorting.SUGGESTIONS, rows, "neu") == ["Heute", "Gestern"]


@pytest.mark.parametrize("slug", [order.slug for order in sorting.SUGGESTIONS])
def test_every_suggestion_key_survives_an_empty_row(slug):
    """Kein Schlüssel darf an einem Fund scheitern, der nichts weiß."""
    assert names(sorting.SUGGESTIONS, [Row("Leer")], slug) == ["Leer"]
