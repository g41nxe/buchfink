"""Author discovery: what a Reference Author has that the Watchlist does not."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from conftest import beam_fixture, beam_tiles
from ebook_watchlist.config import Settings, WatchlistEntry
from ebook_watchlist.http import NotFound
from ebook_watchlist.matching import author_matches
from ebook_watchlist.models import MatchReason
from ebook_watchlist.sources.base import RunContext
from ebook_watchlist.sources.beam.source import BeamSource, author_slug
from ebook_watchlist.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "beam"
NOW = datetime(2026, 9, 4, 6, 0)


def fixture(name: str) -> str:
    return beam_fixture(name)


class RoutingClient:
    """Answers by URL, so the hub / search fallback split can be exercised."""

    def __init__(self, routes: dict[str, str | Exception]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append(url)
        for fragment, outcome in self.routes.items():
            if fragment in url:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected request: {url}")


def source(routes: dict[str, str | Exception]) -> BeamSource:
    return BeamSource(client=RoutingClient(routes))  # type: ignore[arg-type]


# --- slugs ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("author", "slug"),
    [
        ("John Scalzi", "john-scalzi"),
        ("Scalzi, John", "john-scalzi"),
        ("J.R.R. Tolkien", "j.r.r.-tolkien"),
        ("Ursula K. Le Guin", "ursula-k.-le-guin"),
        ("Frank Schätzing", "frank-schaetzing"),
    ],
)
def test_author_slug(author: str, slug: str) -> None:
    assert author_slug(author) == slug


# --- picking the right people out of the noise ----------------------------


def test_both_name_orders_count_as_the_same_person() -> None:
    assert author_matches("John Scalzi", "John Scalzi")
    assert author_matches("John Scalzi", "Scalzi, John")


def test_near_namesakes_are_rejected() -> None:
    """Shopware's fuzzy search offers all of these for the query "Scalzi"."""
    for impostor in [
        "Scali, Lucrezia",
        "Giordano Scalzo, Edgar Nzokwe",
        "Feuchtwanger, Edgar, Scali, Bertil",
        "H. Beam Piper",
        "Jules Verne",
    ]:
        assert not author_matches("John Scalzi", impostor), impostor


@pytest.mark.parametrize(
    ("wanted", "credited"),
    [
        # A longer name is a different person, not a better match. token_set_ratio
        # alone scores every one of these a perfect 100.
        ("Chris Carter", "Chris James Carter"),
        ("Chris Carter", "E. M. Carter"),
        ("S.A. Barnes", "Rodney Barnes"),
        ("S.A. Barnes", "Barnes, Jennifer Lynn"),
        ("S.A. Barnes", "Brad Harmer-Barnes"),
        # Sharing a surname and an initial is not enough either — dropping the
        # initials would reduce both of these to a bare "barnes".
        ("S.A. Barnes", "J.S. Barnes"),
        # A bare given name must not swallow a full one.
        ("Max Barry", "Max & Jakob"),
        ("Max Barry", "Bobby & Max, Hannah Richter"),
    ],
)
def test_a_namesake_is_not_the_author(wanted: str, credited: str) -> None:
    """All eight turned up as real false positives on a live discovery run."""
    assert not author_matches(wanted, credited)


@pytest.mark.parametrize(
    ("wanted", "credited"),
    [
        ("Chris Carter", "Chris Carter"),
        ("Chris Carter", "Carter, Chris"),
        ("S.A. Barnes", "S.A. Barnes"),
        ("Max Barry", "Barry, Max"),
        ("John Scalzi", "Scalzi, John"),
        ("J.R.R. Tolkien", "Tolkien, J.R.R."),
    ],
)
def test_the_author_is_still_recognised_in_either_name_order(wanted: str, credited: str) -> None:
    assert author_matches(wanted, credited)


def test_a_member_of_an_anthology_still_counts() -> None:
    credits = (
        "Joe Haldeman, Julie E. Czerneda, David Brin, Fonda Lee, David Weber, "
        "John Scalzi, Tanya Huff, L. E. Modesitt, Jr., Derek Künsken"
    )
    assert author_matches("John Scalzi", credits)


def test_the_search_fallback_discards_the_noise() -> None:
    """Measured against a real 94-tile result page for the query "Scalzi"."""
    tiles = beam_tiles("search-author-noise.html")
    kept = [tile for tile in tiles if author_matches("John Scalzi", tile.author)]

    assert len(tiles) == 94
    assert 20 < len(kept) < 60
    assert all(author_matches("John Scalzi", tile.author) for tile in kept)


# --- the two lookup paths -------------------------------------------------


def test_a_curated_author_is_read_off_their_own_page() -> None:
    beam = source({"autor-innenwelt/john-scalzi": fixture("author-hub.html")})

    observations = beam.by_author("John Scalzi")

    assert observations
    assert all(o.match_reason is MatchReason.PROFILE_AUTHOR for o in observations)
    assert all(o.source_item_id.isdigit() for o in observations)
    assert "search" not in " ".join(beam.client.requests)  # type: ignore[attr-defined]


def test_an_uncurated_author_falls_back_to_search() -> None:
    beam = source(
        {
            "autor-innenwelt/": NotFound("404"),
            "search": fixture("search-author-noise.html"),
        }
    )

    observations = beam.by_author("John Scalzi")

    assert observations
    assert len(observations) < 94  # the noise was filtered out
    requests = beam.client.requests  # type: ignore[attr-defined]
    assert "autor-innenwelt" in requests[0]
    assert "search" in requests[1]


def test_discovered_titles_carry_their_price() -> None:
    beam = source({"autor-innenwelt/john-scalzi": fixture("author-hub.html")})
    observations = beam.by_author("John Scalzi")
    assert any(o.price_cents for o in observations)
    assert all(o.original_price_cents is None for o in observations)


# --- through collect() ----------------------------------------------------


def test_a_watchlisted_title_is_not_also_reported_as_a_discovery(tmp_path: Path) -> None:
    """One item, one Observation per Run — otherwise the next diff has two
    'latest' rows for the same key and cannot tell what changed."""
    beam = source(
        {
            "606983/krieg-der-klone": fixture("product-detail.html"),
            "autor-innenwelt/john-scalzi": fixture("author-hub.html"),
        }
    )
    entry = WatchlistEntry(
        title="Krieg der Klone",
        author="John Scalzi",
        resolved_links={"beam": "https://www.beam-shop.de/x/y/z/606983/krieg-der-klone"},
    )
    settings = Settings(slug="t", name="T", reference_authors=["John Scalzi"])
    context = RunContext(profile_slug="t", store=Store(tmp_path / "s.db"), now=NOW)

    observations = beam.collect(settings, [entry], context)

    ids = [o.source_item_id for o in observations]
    assert len(ids) == len(set(ids))
    watchlisted = [o for o in observations if o.source_item_id == "606983"]
    assert len(watchlisted) == 1
    assert watchlisted[0].match_reason is MatchReason.WATCHLIST
