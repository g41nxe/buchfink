"""The two-tier deal rule."""

from __future__ import annotations

import pytest

from ebook_watchlist.config import Settings
from ebook_watchlist.deals import DEAL, STRONG_DEAL, deal_flags
from ebook_watchlist.models import MatchReason, Observation

PROFILE = Settings(slug="t", name="T")  # 5,00 € / 10,00 € / 25 %


def observation(price: int | None, original: int | None = None) -> Observation:
    return Observation(
        source="beam",
        source_item_id="1",
        title="Ein Titel",
        match_reason=MatchReason.WATCHLIST,
        price_cents=price,
        original_price_cents=original,
    )


@pytest.mark.parametrize("price", [99, 499])
def test_cheap_outright_needs_no_argument(price: int) -> None:
    assert deal_flags(observation(price), None, PROFILE) == (STRONG_DEAL,)


def test_free_is_filler_not_the_best_bargain_on_the_shelf() -> None:
    """Every free title in a real Run was a bundle or a giveaway. Badging those
    as the strongest deal on the page emptied the badge of meaning (ADR 19)."""
    assert deal_flags(observation(0), None, PROFILE) == ()


def test_a_standing_mid_range_price_is_not_a_deal() -> None:
    """The whole point of the second tier: 9,99 € forever is not news."""
    assert deal_flags(observation(999), observation(999), PROFILE) == ()


def test_a_real_drop_inside_the_band_is_a_deal() -> None:
    assert deal_flags(observation(699), observation(1299), PROFILE) == (DEAL,)


def test_a_token_drop_is_not_enough() -> None:
    assert deal_flags(observation(950), observation(999), PROFILE) == ()


def test_a_struck_original_price_also_counts_as_evidence() -> None:
    """Not reachable on beam-shop, but other shops do show one."""
    assert deal_flags(observation(699, original=1299), None, PROFILE) == (DEAL,)


def test_above_the_band_is_never_a_deal() -> None:
    assert deal_flags(observation(1499), observation(2999), PROFILE) == ()


def test_strong_deal_wins_over_deal() -> None:
    assert deal_flags(observation(299), observation(1299), PROFILE) == (STRONG_DEAL,)


def test_a_price_rise_is_not_a_deal() -> None:
    assert deal_flags(observation(899), observation(699), PROFILE) == ()


def test_no_price_no_flags() -> None:
    assert deal_flags(observation(None), observation(1299), PROFILE) == ()


def test_thresholds_come_from_the_profile() -> None:
    generous = Settings(
        slug="t", name="T", strong_deal_max_cents=1500, deal_max_cents=3000, min_discount_pct=10
    )
    assert deal_flags(observation(1499), None, generous) == (STRONG_DEAL,)
    assert deal_flags(observation(1800), observation(2000), generous) == (DEAL,)
