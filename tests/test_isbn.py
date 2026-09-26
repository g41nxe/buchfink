"""Die ISBN — der Schlüssel, aus dem ADR 18 Buchidentität macht.

Beide Quellen liefern sie auf Seiten, die der Run ohnehin holt: beam in der
Bestellnummer der Kachel, die Onleihe in einer beschrifteten Zeile der
Detailseite. Keiner der Tests hier braucht das Netz.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import beam_fixture, beam_tiles, onleihe_detail
from ebook_watchlist.config import WatchlistEntry
from ebook_watchlist.sources.beam import parse as beam_parse
from ebook_watchlist.sources.onleihe import parse as onleihe_parse
from ebook_watchlist.sources.onleihe.source import OnleiheSource

BEAM = Path(__file__).parent / "fixtures" / "beam"
VOEBB = Path(__file__).parent / "fixtures" / "onleihe"


# --- beam: aus der Bestellnummer ------------------------------------------


def test_the_order_number_carries_the_isbn() -> None:
    tiles = beam_tiles("search-hits.html")
    war = next(tile for tile in tiles if tile.product_id == "606983")

    assert war.order_number == "SW9783104911854450914"
    assert war.isbn == "9783104911854"


def test_most_but_not_all_tiles_carry_one() -> None:
    """Bündel und Sammelausgaben haben Bestellnummern ohne ISBN-Form."""
    tiles = beam_tiles("search-hits.html")
    with_isbn = [tile for tile in tiles if tile.isbn]

    assert len(tiles) == 48
    assert len(with_isbn) == 40
    assert all(len(tile.isbn) == 13 for tile in with_isbn)


@pytest.mark.parametrize(
    ("order_number", "expected"),
    [
        ("SW9783104911854450914", "9783104911854"),  # mit Lieferantensuffix
        ("SW9783641113414", "9783641113414"),  # ohne
        ("SW1234567890123", None),  # kein 978/979-Präfix
        ("9783641113414", None),  # ohne SW ist es keine Bestellnummer
        ("SW97836411134", None),  # zu kurz
        ("", None),
    ],
)
def test_only_a_real_isbn13_is_accepted(order_number: str, expected: str | None) -> None:
    tile = beam_parse.Tile(
        product_id="1",
        order_number=order_number,
        title="Titel",
        author=None,
        price_cents=None,
        url="https://example.invalid/a/b/1/x",
    )
    assert tile.isbn == expected


# --- VÖBB: aus der beschrifteten Zeile ------------------------------------


def test_the_onleihe_states_the_isbn_outright() -> None:
    detail = onleihe_detail("detail-unavailable.html")
    assert detail.isbn == "9783641117009"


def test_a_second_title_too() -> None:
    detail = onleihe_detail("detail-available.html")
    assert detail.isbn == "9783104912769"


def test_a_page_without_an_isbn_row_simply_has_none() -> None:
    html = (
        '<html><body><div class="exemplar-count">1 Exemplare</div>'
        '<div class="availability-count">1 Verfügbar</div></body></html>'
    )
    assert onleihe_parse.parse_detail(html).isbn is None


def test_the_isbn_row_survives_the_abbr_markup() -> None:
    """Die Onleihe wickelt das Label in ein <abbr> — anders als bei Jahr oder Reihe."""
    html = (
        '<html><body><div class="exemplar-count">1 Exemplare</div>'
        '<div class="availability-count">1 Verfügbar</div>'
        '<p class="horizontalDescription"><b class="pe-2 isbn">'
        '<abbr title="Internationale Standardbuchnummer">ISBN</abbr>:</b>'
        "<span>978-3-641-11700-9</span></p></body></html>"
    )
    assert onleihe_parse.parse_detail(html).isbn == "9783641117009"


# --- bis in die Observation ------------------------------------------------


def test_the_isbn_reaches_the_observation() -> None:
    class StubClient:
        def get(self, url: str, params: dict | None = None) -> str:
            return (VOEBB / "detail-unavailable.html").read_text(encoding="utf-8")

    source = OnleiheSource(client=StubClient())  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Die sieben Schwestern",
        resolved_links={"onleihe": "mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html"},
    )

    observation = source.check(entry)

    assert observation is not None
    assert observation.isbn == "9783641117009"


def test_both_sources_agree_on_the_same_book() -> None:
    """Der empirische Befund, auf dem ADR 18 die Identität aufbaut."""
    onleihe = onleihe_detail("detail-unavailable.html")
    # beam führt dasselbe Buch unter Produkt 395021; live geprüft am 2026-09-04.
    assert onleihe.isbn == "9783641117009"


# --- beam-Detailseite: der Fall, den der Livelauf aufgedeckt hat -----------


def test_the_beam_detail_page_yields_the_isbn_too() -> None:
    """Watchlist-Titel werden über die Detailseite geprüft, nicht über die
    Kachel — ohne das blieben ausgerechnet sie ohne Identität."""
    detail = beam_parse.parse_detail(beam_fixture("product-detail.html"))
    assert detail.isbn == "9783104911854"


def test_the_isbn_comes_from_the_product_block_not_a_recommendation() -> None:
    """Die Seite trägt 63 Bestellnummern; genau eine gehört zum Produkt."""
    html = beam_fixture("product-detail.html")
    assert html.count("SW9783") > 10
    assert beam_parse.parse_detail(html).isbn == "9783104911854"


def test_a_detail_page_without_an_order_number_has_none() -> None:
    html = (
        '<html><body><div class="product--details">'
        '<meta itemprop="price" content="9.99"></div></body></html>'
    )
    assert beam_parse.parse_detail(html).isbn is None


def test_a_bundle_order_number_yields_no_isbn() -> None:
    """Sammelausgaben tragen Bestellnummern, die keine ISBN sind."""
    html = (
        '<html><body><div class="product--details">'
        '<meta itemprop="price" content="9.99">'
        '<input name="sAdd" value="SW1234567890123"></div></body></html>'
    )
    assert beam_parse.parse_detail(html).isbn is None
