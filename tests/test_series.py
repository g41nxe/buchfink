"""Nicht mitten in einer Reihe anfangen (Einstieg aus dem alten Leseprofil).

Die Regel stand als Prosa in ``leseprofil.yaml`` und ging mit dem alten
Sternemodell verloren (#52). Jetzt rechnet sie der Code, vor dem Tor.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.series import MidSeries, series_key


def find(title: str, *, subtitle: str | None = None, author: str = "Tad Williams",
         isbn: str | None = None, series: str | None = None,
         series_index: str | None = None) -> Observation:
    return Observation(source="beam", source_item_id="1", title=title, subtitle=subtitle,
                       author=author, isbn=isbn, series=series, series_index=series_index,
                       match_reason=MatchReason.GENRE_CATEGORY)


NOBODY = MidSeries(known={}, authors=frozenset(), followed=frozenset())


@pytest.mark.parametrize(("name", "key"), [
    ("Die Cormoran-Strike-Reihe", "cormoran strike"),
    ("Ein Wayward-Pines-Thriller", "wayward pines"),
    ("Ein Harry-Hole-Krimi", "harry hole"),
    ("Red Rising Saga", "red rising"),
    ("Achtsam morden-Reihe", "achtsam morden"),
    ("Southern-Reach-Trilogie", "southern reach"),
    ("Washington Poe und Tilly Bradshaw ermitteln", "washington poe und tilly bradshaw"),
    ("Art Mayer-Serie", "art mayer"),
    ("Scythe", "scythe"),
    ("Die Flüsse-von-London-Reihe (Peter Grant)", "flüsse von london"),
    ("Seifert und Theurer - Thriller", "seifert und theurer"),
])
def test_a_series_name_has_one_key(name: str, key: str) -> None:
    """Jede Quelle schreibt die Reihe anders; der Schlüssel ist derselbe (ADR 35)."""
    assert series_key(name) == key


def test_a_name_that_is_only_a_suffix_keeps_itself() -> None:
    """„Die Reihe" ist kein leerer Schlüssel."""
    assert series_key("Die Reihe") == "reihe"


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
    series = MidSeries(known={"978": ("immermorde", "3")}, authors=frozenset(),
                       followed=frozenset())

    assert series(find("Immerkalt", subtitle="Thriller", isbn="978"))
    assert not MidSeries(known={"978": ("immermorde", "1")}, authors=frozenset(),
                         followed=frozenset())(find("Immerkalt", isbn="978"))


def test_the_library_names_the_volume_itself() -> None:
    """OverDrive nennt den Band in der Trefferliste (#83); *Ein Schrei, den
    niemand hört* ist Band 1 und bleibt."""
    assert NOBODY(find("Morning Star", series="Red Rising Saga", series_index="3"))
    assert not NOBODY(find("Ein Schrei, den niemand hört",
                           series="Detective Robert Kett", series_index="1"))


def test_the_stored_volume_outranks_the_finds_own() -> None:
    """Was zur ISBN gespeichert ist, ist schon nach Herkunft entschieden —
    die DNB vor OverDrive (ADR 35)."""
    series = MidSeries(known={"978": ("red rising", "1")}, authors=frozenset(),
                       followed=frozenset())

    assert not series(find("Red Rising", isbn="978", series="Red Rising Saga",
                           series_index="3"))


def test_an_author_she_follows_may_continue_a_series() -> None:
    """„Reihen von Autor:innen, die ich ausdrücklich mag — dort kenne ich den Stand."""
    series = MidSeries(known={}, authors=frozenset({"tad williams"}), followed=frozenset())

    assert not series(find("Otherland. Band 2", author="Tad Williams"))
    assert series(find("Shadow. Band 2", author="Jemand Anderes"))


def test_a_series_she_already_reads_may_continue() -> None:
    series = MidSeries(known={"978": ("wayward pines", "2")},
                       authors=frozenset(), followed=frozenset({"wayward pines"}))

    assert not series(find("Wayward", author="Blake Crouch", isbn="978"))


def test_a_followed_series_is_recognised_under_another_name() -> None:
    """Onleihe schreibt „Die Cormoran-Strike-Reihe", die eigenen Bücher stehen
    unter „Cormoran Strike" — derselbe Schlüssel."""
    series = MidSeries(known={}, authors=frozenset(), followed=frozenset({"cormoran strike"}))

    assert not series(find("Böses Blut", series="Die Cormoran-Strike-Reihe",
                           series_index="5"))


def test_a_watchlist_title_is_never_mid_series() -> None:
    watched = replace(find("Otherland. Band 3"), match_reason=MatchReason.WATCHLIST)

    assert not NOBODY(watched)
