"""Nicht mitten in einer Reihe anfangen (Einstieg aus dem alten Leseprofil).

Die Regel stand als Prosa in ``leseprofil.yaml`` und ging mit dem alten
Sternemodell verloren (#52). Jetzt rechnet sie der Code, vor dem Tor.
"""

from __future__ import annotations

from dataclasses import replace

from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.series import MidSeries


def find(title: str, *, subtitle: str | None = None, author: str = "Tad Williams",
         isbn: str | None = None) -> Observation:
    return Observation(source="beam", source_item_id="1", title=title, subtitle=subtitle,
                       author=author, isbn=isbn, match_reason=MatchReason.GENRE_CATEGORY)


NOBODY = MidSeries(dnb={}, authors=frozenset(), followed=frozenset())


def test_a_later_volume_named_in_the_title_is_mid_series() -> None:
    assert NOBODY(find("Otherland. Band 2", subtitle="Fluss aus blauem Feuer"))
    assert NOBODY(find("Happy Hour in der Hölle", subtitle="Bobby Dollar 2"))


def test_the_first_volume_and_a_standalone_are_not() -> None:
    assert not NOBODY(find("Otherland. Band 1"))
    assert not NOBODY(find("Der Schwarm", subtitle="Roman"))
    assert not NOBODY(find("Passagier 23"))
    # Eine nackte Zahl im Titel ist oft Teil des Namens: Einzelbände beide.
    assert not NOBODY(find("Station 11"))
    assert not NOBODY(find("Apartment 16"))


def test_the_dnb_knows_the_volume_the_title_hides() -> None:
    """„Immerkalt — Thriller": dritter Band der Immermorde, sagt nur die DNB."""
    series = MidSeries(dnb={"978": ("Immermorde", "3")}, authors=frozenset(),
                       followed=frozenset())

    assert series(find("Immerkalt", subtitle="Thriller", isbn="978"))
    assert not MidSeries(dnb={"978": ("Immermorde", "1")}, authors=frozenset(),
                         followed=frozenset())(find("Immerkalt", isbn="978"))


def test_an_author_she_follows_may_continue_a_series() -> None:
    """„Reihen von Autor:innen, die ich ausdrücklich mag — dort kenne ich den Stand."""
    series = MidSeries(dnb={}, authors=frozenset({"tad williams"}), followed=frozenset())

    assert not series(find("Otherland. Band 2", author="Tad Williams"))
    assert series(find("Shadow. Band 2", author="Jemand Anderes"))


def test_a_series_she_already_reads_may_continue() -> None:
    series = MidSeries(dnb={"978": ("Ein Wayward-Pines-Thriller", "2")},
                       authors=frozenset(), followed=frozenset({"ein wayward-pines-thriller"}))

    assert not series(find("Wayward", author="Blake Crouch", isbn="978"))


def test_a_watchlist_title_is_never_mid_series() -> None:
    watched = replace(find("Otherland. Band 3"), match_reason=MatchReason.WATCHLIST)

    assert not NOBODY(watched)
