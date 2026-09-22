from __future__ import annotations

import pytest

from ebook_watchlist.config import Settings
from ebook_watchlist.diff import compare, compute_deltas, suppress_unseeded_interests
from ebook_watchlist.models import Availability, DeltaKind, MatchReason, Observation


def observation(**overrides) -> Observation:
    defaults = dict(
        source="fake",
        source_item_id="1",
        title="Ein Titel",
        match_reason=MatchReason.WATCHLIST,
    )
    return Observation(**{**defaults, **overrides})


def test_a_watchlist_title_is_reported_at_any_price() -> None:
    """The reader named this book. Silence until it happens to be cheap meant
    you could watch a title and never learn it had been found (ADR 19)."""
    deltas = compare(observation(price_cents=999), None)
    assert [d.kind for d in deltas] == [DeltaKind.FIRST_SEEN]
    assert deltas[0].previous is None


def test_a_shelf_find_at_full_price_stays_quiet() -> None:
    shelf = observation(price_cents=999, match_reason=MatchReason.GENRE_CATEGORY)
    assert compare(shelf, None, PROFILE) == []


def test_a_reference_author_at_full_price_waits_for_a_deal_too() -> None:
    """Die Ausnahme für Referenzautor:innen war ausdrücklich vorläufig — bis es
    ein Tor gibt, das nach Relevanz fragt. Das Tor kam mit Ticket 12, die
    Ausnahme blieb, und sie widersprach ADR 19 wörtlich: eine Entdeckung wird
    gemeldet, wenn sie ein Schnäppchen ist, von einer Referenzautorin wie aus
    einem Thema.

    Verloren ist nichts: die Beobachtung wird gespeichert, und der neue Nesbø
    meldet sich an dem Tag, an dem sein Preis fällt."""
    nesbo = observation(
        title="Blutmond", price_cents=1199, match_reason=MatchReason.PROFILE_AUTHOR
    )
    assert compare(nesbo, None, PROFILE) == []


@pytest.mark.parametrize(
    "reason", [MatchReason.PROFILE_AUTHOR, MatchReason.GENRE_CATEGORY]
)
def test_a_discovery_that_is_a_bargain_is_the_news(reason: MatchReason) -> None:
    deltas = compare(observation(price_cents=399, match_reason=reason), None, PROFILE)
    assert [d.kind for d in deltas] == [DeltaKind.FIRST_SEEN]


def test_a_discovery_is_only_news_once() -> None:
    before = observation(price_cents=999, match_reason=MatchReason.GENRE_CATEGORY)
    assert compare(before, before) == []


def test_unchanged_is_not_a_delta() -> None:
    before = observation(price_cents=999, availability=Availability.UNAVAILABLE)
    assert compare(before, before) == []


def test_becoming_available_is_a_delta() -> None:
    previous = observation(availability=Availability.UNAVAILABLE, reservation_count=3)
    current = observation(availability=Availability.AVAILABLE)
    assert [d.kind for d in compare(current, previous)] == [DeltaKind.BECAME_AVAILABLE]


def test_price_drop_and_rise_are_distinguished() -> None:
    previous = observation(price_cents=1299)
    assert [d.kind for d in compare(observation(price_cents=999), previous)] == [
        DeltaKind.PRICE_DROP
    ]
    assert [d.kind for d in compare(observation(price_cents=1499), previous)] == [
        DeltaKind.PRICE_RISE
    ]


def test_only_notifiable_kinds_reach_the_digest() -> None:
    """A price rise and a title going away are recorded, but they are not news."""
    previous = {
        ("fake", "1"): observation(price_cents=999),
        ("fake", "2"): observation(source_item_id="2", availability=Availability.AVAILABLE),
    }
    current = [
        observation(price_cents=1299),
        observation(source_item_id="2", availability=Availability.UNAVAILABLE),
    ]
    assert compute_deltas(current, previous) == []


def test_missing_field_on_one_side_is_not_a_delta() -> None:
    previous = observation(price_cents=None)
    assert compare(observation(price_cents=999), previous) == []


# --- a watchlist title that is already cheap ------------------------------

PROFILE = Settings(slug="t", name="T")  # Strong Deal unter 5,00 EUR


def test_an_already_cheap_watchlist_title_is_reported_on_sight() -> None:
    """Waiting for a 3,99 EUR title to get cheaper still would be a strange way
    to answer 'tell me when it is a bargain'."""
    deltas = compare(observation(price_cents=399), None, PROFILE)
    assert [d.kind for d in deltas] == [DeltaKind.FIRST_SEEN]


def test_a_watchlist_title_needs_no_bargain_to_be_worth_saying() -> None:
    assert [d.kind for d in compare(observation(price_cents=1499), None, PROFILE)] == [
        DeltaKind.FIRST_SEEN
    ]


def test_without_a_profile_a_discovery_cannot_clear_the_bar() -> None:
    """No thresholds, no way to call anything a deal — so the channel that
    depends on one stays silent rather than guessing."""
    cheap = observation(price_cents=399, match_reason=MatchReason.GENRE_CATEGORY)
    assert compare(cheap, None) == []


def test_the_cheap_title_is_reported_once_not_every_run() -> None:
    cheap = observation(price_cents=399)
    assert compare(cheap, cheap, PROFILE) == []


def test_a_discovery_with_no_price_is_not_a_bargain() -> None:
    priceless = observation(price_cents=None, match_reason=MatchReason.GENRE_CATEGORY)
    assert compare(priceless, None, PROFILE) == []


def test_seeding_never_swallows_a_watchlist_bargain() -> None:
    """Interessen werden still angesät; ein Watchlist-Eintrag hat keines und
    darf davon nicht verschluckt werden."""
    deltas = compute_deltas([observation(price_cents=399)], {}, PROFILE)
    assert suppress_unseeded_interests(deltas, origin={}, seeded=set()) == deltas


def test_a_price_drop_on_a_shelf_find_needs_the_same_bar() -> None:
    """Strict at the front door, open at the back was the hole: a title kept
    quiet at 11,99 € must not be announced for slipping to 11,49 €."""
    shelf = observation(price_cents=1149, match_reason=MatchReason.GENRE_CATEGORY)
    before = observation(price_cents=1199, match_reason=MatchReason.GENRE_CATEGORY)
    assert compare(shelf, before, PROFILE) == []

    real = observation(price_cents=399, match_reason=MatchReason.GENRE_CATEGORY)
    assert [d.kind for d in compare(real, before, PROFILE)] == [DeltaKind.PRICE_DROP]


def test_a_watchlist_price_drop_is_always_worth_saying() -> None:
    assert [d.kind for d in compare(
        observation(price_cents=1149), observation(price_cents=1199), PROFILE
    )] == [DeltaKind.PRICE_DROP]
