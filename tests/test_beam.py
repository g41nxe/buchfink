"""Offline tests against HTML captured from the live beam-shop on 2026-09-04."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import beam_detail, beam_fixture, beam_tiles
from ebook_watchlist.config import WatchlistEntry
from ebook_watchlist.matching import Confidence
from ebook_watchlist.models import MatchReason
from ebook_watchlist.sources.base import SourceStructureError
from ebook_watchlist.sources.beam import parse
from ebook_watchlist.sources.beam import selectors as sel
from ebook_watchlist.sources.beam.source import BeamSource

FIXTURES = Path(__file__).parent / "fixtures" / "beam"


def fixture(name: str) -> str:
    return beam_fixture(name)


class ScriptedClient:
    def __init__(self, *pages: str) -> None:
        self.pages = list(pages)
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]


def source(*pages: str) -> BeamSource:
    return BeamSource(client=ScriptedClient(*pages))  # type: ignore[arg-type]


# --- prices ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("9,99 €", 999),
        ("9,99\xa0€", 999),  # the shop uses a non-breaking space
        ("4,99 €", 499),
        ("0,99 €", 99),
        ("1.234,56 €", 123456),  # de-DE thousands separator
        ("kostenlos", None),
        ("", None),
    ],
)
def test_parse_price(text: str, cents: int | None) -> None:
    assert parse.parse_price(text) == cents


# --- listing tiles --------------------------------------------------------


def test_search_results_parse_into_tiles() -> None:
    tiles = beam_tiles("search-hits.html")
    assert len(tiles) == 48

    first = tiles[0]
    assert first.title == "Krieg der Klone"
    assert first.author == "John Scalzi"
    assert first.price_cents == 499
    assert first.product_id == "606983"
    assert first.order_number == "SW9783104911854450914"
    assert first.url.endswith("/606983/krieg-der-klone")


def test_the_title_excludes_the_subtitle() -> None:
    """The link's own text runs title and subtitle together."""
    tiles = beam_tiles("category-new-arrivals.html")
    starwars = next(tile for tile in tiles if tile.product_id == "1278797")
    assert starwars.title == "Star Wars™ - Die Verschollenen"
    assert starwars.subtitle and "Jubiläum" in starwars.subtitle


def test_the_leading_name_particle_is_stripped_from_the_author() -> None:
    tiles = beam_tiles("category-new-arrivals.html")
    starwars = next(tile for tile in tiles if tile.product_id == "1278797")
    assert starwars.author == "Zahn, Timothy"


def test_the_product_url_drops_the_category_context_param() -> None:
    tiles = beam_tiles("category-new-arrivals.html")
    assert all("?" not in tile.url for tile in tiles)
    assert all(tile.url.startswith("https://www.beam-shop.de/") for tile in tiles)


def test_badges_are_deduplicated_across_layout_slots() -> None:
    """A tile repeats its badge markup once per slot; the set must not."""
    tiles = beam_tiles("category-new-arrivals.html")
    starwars = next(tile for tile in tiles if tile.product_id == "1278797")
    assert starwars.badges == {sel.BADGE_PREORDER, sel.BADGE_NEW}
    assert starwars.is_preorder
    assert starwars.is_new


def test_no_results_is_an_answer_not_a_failure() -> None:
    assert beam_tiles("search-no-results.html") == []


def test_a_page_with_neither_tiles_nor_the_message_raises() -> None:
    with pytest.raises(SourceStructureError, match="listing markup changed"):
        parse.parse_tiles("<html><body><p>Wartungsarbeiten</p></body></html>")


def test_total_pages_is_read_off_the_listing() -> None:
    assert parse.total_pages(fixture("category-new-arrivals.html")) == 236
    assert parse.total_pages(fixture("author-hub.html")) == 2
    assert parse.total_pages(fixture("search-no-results.html")) is None


# --- product detail page --------------------------------------------------


def test_detail_price_comes_from_the_main_product_not_a_recommendation() -> None:
    """The page carries well over a hundred cross-sell tiles with the same classes."""
    detail = beam_detail("product-detail.html")
    assert detail.title == "Krieg der Klone"
    assert detail.price_cents == 499


def test_the_detail_page_names_its_reading_sample() -> None:
    """Die Leseprobe als EPUB — das einzige Stück vom Buch selbst, das vor dem
    Kauf zu haben ist (#17). Eine Anfrage mehr, und nur für den Bewerter."""
    assert beam_detail("product-detail.html").sample_url == (
        "https://www.beam-shop.de/media/unknown/e8/45/19/"
        "9783104911854_8cd11dc5-4f26-402e-b60a-3686864c1b1d.epub"
    )


def test_the_shops_keywords_leave_out_author_and_title() -> None:
    """Die Schlagwörter nennen Motive und Vergleichstitel ("Dune", "The
    Expanse"). Autor und Titel stehen auch darin, und die weiß der Bewerter
    schon (#17)."""
    keywords = beam_detail("product-detail.html").keywords

    assert "Space Opera" in keywords
    assert "The Expanse" in keywords
    assert "John Scalzi" not in keywords
    assert "Krieg der Klone" not in keywords
    assert len(keywords) == len(set(keywords))


def test_the_detail_page_names_the_publisher() -> None:
    """Der Verlag entscheidet, ob ein Stern für Selbstverlag abgeht (#28)."""
    assert beam_detail("product-detail.html").publisher == "FISCHER E-Books"


def test_a_detail_page_without_the_product_block_raises() -> None:
    with pytest.raises(SourceStructureError, match="detail markup changed"):
        parse.parse_detail("<html><body><h1>Beam Shop</h1></body></html>")


def test_a_detail_page_without_a_price_raises() -> None:
    html = '<html><body><div class="product--details"><h2>Titel</h2></div></body></html>'
    with pytest.raises(SourceStructureError, match="machine-readable price"):
        parse.parse_detail(html)


# --- the Source -----------------------------------------------------------


def test_resolution_ignores_search_rank_and_re_matches_every_tile() -> None:
    beam = source(fixture("search-hits.html"))
    resolution = beam.resolve(WatchlistEntry(title="Krieg der Klone", author="John Scalzi"))

    assert resolution is not None
    assert resolution.confidence is Confidence.AUTO_ACCEPT, resolution.reason
    assert resolution.accepted is not None
    assert resolution.accepted.payload.endswith("/606983/krieg-der-klone")


def test_a_query_the_shop_cannot_serve_is_not_sent() -> None:
    """Shopware silently returns nothing below four characters."""
    beam = source(fixture("search-hits.html"))
    assert beam.search("abc") == []
    assert beam.client.requests == []  # type: ignore[attr-defined]


def test_no_search_results_means_not_stocked() -> None:
    beam = source(fixture("search-no-results.html"))
    assert beam.resolve(WatchlistEntry(title="Gibt es nicht", author="Niemand")) is None


def test_check_reads_the_price_off_the_pinned_product_page() -> None:
    beam = source(fixture("product-detail.html"))
    entry = WatchlistEntry(
        title="Krieg der Klone",
        author="John Scalzi",
        resolved_links={
            "beam": "https://www.beam-shop.de/belletristik/science-fiction/"
            "science-fiction-allgemein/606983/krieg-der-klone"
        },
    )

    observation = beam.check(entry)

    assert observation is not None
    assert observation.source == "beam"
    assert observation.source_item_id == "606983"
    assert observation.price_cents == 499
    assert observation.match_reason is MatchReason.WATCHLIST
    assert observation.watchlist_key == entry.key


def test_the_struck_price_is_always_absent_here() -> None:
    """German fixed-book-price law: the shop never renders one."""
    beam = source(fixture("product-detail.html"))
    entry = WatchlistEntry(
        title="Krieg der Klone",
        resolved_links={"beam": "https://www.beam-shop.de/x/y/z/606983/krieg-der-klone"},
    )
    observation = beam.check(entry)
    assert observation is not None
    assert observation.original_price_cents is None


# --- Klappentext (ADR 17) --------------------------------------------------


def test_the_blurb_is_captured_from_the_listing_page() -> None:
    """Vier von sieben Achsen des Maßstabs hängen daran, und er kostet keinen
    eigenen Request — er liegt im HTML, das der Run ohnehin holt."""
    tiles = beam_tiles("category-new-arrivals.html")

    assert all(tile.blurb for tile in tiles)
    starwars = next(tile for tile in tiles if tile.product_id == "1278797")
    assert "Luke Skywalker" in starwars.blurb


def test_a_tile_without_a_teaser_simply_has_none() -> None:
    html = (
        '<div class="listing"><div class="product--box" data-ordernumber="X">'
        '<a class="product--title" href="/a/b/1/x" title="Titel"></a>'
        '<button data-note-article="1"></button></div></div>'
    )
    assert parse.parse_tiles(html)[0].blurb is None


def test_the_blurb_is_taken_once_not_twice() -> None:
    """Der Shop rendert Anriss und vollen Text untereinander; der Browser zeigt
    immer nur einen davon. ``get_text()`` ueber den Elternknoten nahm beides —
    110 der 116 langen Klappentexte standen deshalb doppelt in der Datenbank
    (Ticket 40)."""
    detail = beam_detail("product-detail.html")

    assert detail.blurb is not None
    assert "alles anzeigen" not in detail.blurb.lower()
    # Der erste Satz genau einmal, nicht zweimal.
    assert detail.blurb.count("Die ersten drei Romane") == 1


def test_a_short_blurb_has_no_full_node_and_survives() -> None:
    """Kurze Klappentexte haben kein ``description--full``. Ohne Rueckfall auf
    den Anriss stuende dort ab sofort gar nichts."""
    html = (
        '<html><head><link rel="canonical" href="https://www.beam-shop.de/a"></head>'
        '<body><div class="product--details"><h1 class="product--title">T</h1>'
        '<meta itemprop="price" content="4.99">'
        '<div itemprop="description"><div class="description--preview">'
        "Ein kurzer Text.</div></div></div></body></html>"
    )

    assert parse.parse_detail(html).blurb == "Ein kurzer Text."


def test_a_renamed_node_still_does_not_double_the_text() -> None:
    """Benennt der Shop die Klassen um, faellt der Parser auf den Elternknoten
    zurueck — dann faengt der Schnitt am Aufklapp-Knopf es auf. Die schwaechere
    Regel, aber immer noch verlustfrei."""
    html = (
        '<html><head><link rel="canonical" href="https://www.beam-shop.de/a"></head>'
        '<body><div class="product--details"><h1 class="product--title">T</h1>'
        '<meta itemprop="price" content="4.99">'
        '<div itemprop="description"><div class="teaser">Der Anfang ...</div>'
        '<span>alles anzeigen</span><div class="rest">Der Anfang und der Rest.'
        "</div></div></div></body></html>"
    )

    assert parse.parse_detail(html).blurb == "Der Anfang und der Rest."


def test_an_empty_full_node_does_not_swallow_the_blurb() -> None:
    """Nur auf „Knoten da?" zu pruefen reichte nicht: ein leerer
    ``description--full`` liess den Klappentext ganz verschwinden — und ein
    Buch ohne Klappentext holt ``_with_evidence`` bei jedem Lauf erneut."""
    html = (
        '<html><head><link rel="canonical" href="https://www.beam-shop.de/a"></head>'
        '<body><div class="product--details"><h1 class="product--title">T</h1>'
        '<meta itemprop="price" content="4.99">'
        '<div itemprop="description"><div class="description--preview">'
        'Ein kurzer Text.</div><div class="description--full"></div>'
        "</div></div></body></html>"
    )

    assert parse.parse_detail(html).blurb == "Ein kurzer Text."


def test_a_bundle_page_has_a_cover_too() -> None:
    """Die Paketseite zeigt die Titelbilder ihrer Baende mit schlichtem ``src``,
    ohne das ``srcset`` einer Einzelausgabe. Gesucht wurde nur nach ``srcset``
    — die *Wayward Pines-Trilogie* blieb deshalb ohne Bild, obwohl drei auf
    der Seite standen. Genommen wird das erste: es ist der erste Band."""
    html = """<html><body><div class="product--details">
      <h1 class="product--title">Wayward Pines-Trilogie</h1>
      <meta itemprop="price" content="10.97">
      <img src="https://www.beam-shop.de/media/image/d8/b8/01/9783641253226_600x600.jpg">
      <img src="https://www.beam-shop.de/media/image/c3/9b/c9/9783641253233_600x600.jpg">
    </div></body></html>"""

    assert parse.parse_detail(html).cover_url == (
        "https://www.beam-shop.de/media/image/d8/b8/01/9783641253226_600x600.jpg"
    )


def test_the_detail_page_carries_the_page_count() -> None:
    """Der Umfang, für das Erkennen von Kurzgeschichten (#73)."""
    assert beam_detail("product-detail.html").pages == 800
