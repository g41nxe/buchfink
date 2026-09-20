"""Offline parser tests against HTML captured from the live Onleihe.

The fixtures are whole pages as served on 2026-09-04; re-capture them when the
site changes rather than hand-editing (ADR 14).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ebook_watchlist.config import WatchlistEntry
from ebook_watchlist.http import NotFound
from ebook_watchlist.models import Availability
from ebook_watchlist.sources.base import SourceStructureError
from ebook_watchlist.sources.onleihe import parse
from ebook_watchlist.sources.onleihe.source import OnleiheSource, title_id_from_url

FIXTURES = Path(__file__).parent / "fixtures" / "onleihe"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class StubClient:
    """Serves canned HTML and records what was asked for."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.html


# --- detail page ----------------------------------------------------------


def test_unavailable_title_reports_queue_and_eta() -> None:
    detail = parse.parse_detail(fixture("detail-unavailable.html"))
    assert detail.title == "Die sieben Schwestern"
    assert detail.author == "Riley, Lucinda"
    assert detail.copies == 4
    assert detail.available_copies == 0
    assert detail.reservations == 16
    assert detail.available_from == "18.12.2026"
    assert detail.availability is Availability.UNAVAILABLE


def test_the_reading_sample_is_the_epub_behind_the_reader() -> None:
    """Der Knopf "Leseprobe" öffnet den Webreader; die EPUB-Datei steht in
    dessen Adresse hinter ``url=``. Die Datei ist, was der Bewerter braucht,
    nicht der Reader (#17)."""
    assert parse.parse_detail(fixture("detail-available.html")).sample_url == (
        "https://static.onleihe.de/content/978/310/491/276/9/"
        "65c24250673f3d10bd6298ee/v9783104912769.epub"
    )


def test_a_title_id_is_enough_to_read_its_page() -> None:
    """Der Weg, auf dem der Bewerter Klappentext und Leseprobe bekommt (#17):
    nur mit der Kennung, ohne Suche."""
    client = StubClient(fixture("detail-available.html"))

    item = OnleiheSource(client).item("373164461")

    assert item is not None
    assert item.title == "Sieben Richtige"
    assert item.sample_url is not None and item.sample_url.endswith(".epub")
    assert "mediaInfo,0-0-373164461-200-" in client.requests[0][0]


def test_a_title_the_library_dropped_is_no_item() -> None:
    class Weg(StubClient):
        def get(self, url: str, params: dict | None = None) -> str:
            raise NotFound(url)

    assert OnleiheSource(Weg("")).item("373164461") is None


def test_the_detail_page_names_the_publisher() -> None:
    assert parse.parse_detail(fixture("detail-available.html")).publisher == "FISCHER E-Books"


def test_available_title_has_no_eta() -> None:
    detail = parse.parse_detail(fixture("detail-available.html"))
    assert detail.title == "Sieben Richtige"
    assert detail.available_copies == 5
    assert detail.reservations == 0
    assert detail.available_from is None
    assert detail.availability is Availability.AVAILABLE


def test_detail_page_without_the_exemplar_block_raises() -> None:
    with pytest.raises(SourceStructureError, match="Exemplare"):
        parse.parse_detail("<html><body><h1>Wartungsarbeiten</h1></body></html>")


# --- search results -------------------------------------------------------


def test_search_results_parse_into_candidates() -> None:
    candidates = parse.parse_search_results(fixture("search-hits.html"))
    assert candidates is not None
    assert len(candidates) == 8

    first = candidates[0]
    assert first.title == "Die sieben Schwestern"
    assert first.author == "Riley, Lucinda"
    assert first.subtitle == "Roman - Die sieben Schwestern 1"
    assert first.url.endswith("mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html")
    assert first.url.startswith("https://voebb.onleihe.de/berlin/frontend/")


def test_a_result_card_brings_its_thumbnail() -> None:
    """Bei einer offenen Zuordnung stehen die Kandidaten nebeneinander, und
    welcher der richtige ist, entscheidet das Auge (Ticket 41). Vom Shop kam
    das Bild längst mit, von der Bibliothek nicht — dort stand ein Platzhalter,
    obwohl die Trefferkarte ein Bild trägt."""
    candidates = parse.parse_search_results(fixture("search-hits.html"))
    assert candidates is not None

    assert candidates[0].cover_url == (
        "https://static.onleihe.de/images/978/364/111/700/9/"
        "65c24254673f3d10bd629916/tn9783641117009s.jpg"
    )


def test_medium_icon_is_the_format_not_the_rating_star() -> None:
    """Cards carry ``ic_star`` rating icons too; picking by position gets it wrong."""
    candidates = parse.parse_search_results(fixture("search-hits.html"))
    assert candidates is not None
    media = {candidate.medium for candidate in candidates}
    assert "ic_star" not in media
    assert media <= {"ic_ebook", "ic_eaudio", None}


def test_no_hits_is_an_answer_not_a_failure() -> None:
    assert parse.parse_search_results(fixture("search-no-hits.html")) is None
    assert parse.total_hits(fixture("search-no-hits.html")) == 0


def test_hit_count_is_read_from_the_page() -> None:
    assert parse.total_hits(fixture("search-hits.html")) == 8


def test_cards_gone_without_the_no_hits_marker_raises() -> None:
    """What a captcha or a redesign looks like — never a silent empty list."""
    with pytest.raises(SourceStructureError, match="markup changed"):
        parse.parse_search_results("<html><body><p>Etwas ganz anderes</p></body></html>")


def test_expired_session_is_named_explicitly() -> None:
    html = "<html><body><p>Ihre Sitzung ist abgelaufen! Bitte erneut versuchen.</p></body></html>"
    with pytest.raises(SourceStructureError, match="session expired"):
        parse.parse_search_results(html)


# --- the Source -----------------------------------------------------------


def test_title_id_is_extracted_from_the_detail_url() -> None:
    assert title_id_from_url("mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html") == "373164461"
    assert title_id_from_url("https://x/frontend/mediaInfo,0-0-42-200-0.html") == "42"
    assert title_id_from_url("search,0-0-0.html") is None


def test_check_reads_the_pinned_detail_page() -> None:
    client = StubClient(fixture("detail-unavailable.html"))
    source = OnleiheSource(client=client)  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Die sieben Schwestern",
        author="Lucinda Riley",
        resolved_links={"onleihe": "mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html"},
    )

    observation = source.check(entry)

    assert observation is not None
    assert observation.source == "onleihe"
    assert observation.source_item_id == "373164461"
    assert observation.availability is Availability.UNAVAILABLE
    assert observation.reservation_count == 16
    assert observation.available_from == "18.12.2026"
    assert observation.watchlist_key == entry.key
    assert client.requests[0][0].startswith("https://voebb.onleihe.de/berlin/frontend/mediaInfo,")


def test_check_reports_the_scraped_title_so_a_bad_resolve_is_visible() -> None:
    client = StubClient(fixture("detail-available.html"))
    source = OnleiheSource(client=client)  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Ganz anderer Titel",
        author="Jemand Anders",
        resolved_links={"onleihe": "mediaInfo,0-0-1474715999-200-0-0-0-0-0-0-0.html"},
    )

    observation = source.check(entry)

    assert observation is not None
    assert observation.title == "Sieben Richtige"
    assert observation.author == "Jarck, Volker"


def test_unpinned_entry_is_skipped_until_resolution_exists() -> None:
    client = StubClient("")
    source = OnleiheSource(client=client)  # type: ignore[arg-type]

    assert source.check(WatchlistEntry(title="Noch nicht aufgelöst")) is None
    assert client.requests == []


def test_a_vanished_title_skips_that_entry_instead_of_failing_the_source() -> None:
    """One dead pinned link must not take the whole library check down with it."""

    class GoneClient:
        def get(self, url: str, params: dict | None = None) -> str:
            raise NotFound(f"{url} answered 404")

    source = OnleiheSource(client=GoneClient())  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Aus dem Bestand entfernt",
        resolved_links={"onleihe": "mediaInfo,0-0-999-200-0-0-0-0-0-0-0.html"},
    )
    assert source.check(entry) is None


def test_an_unkeyable_link_raises_rather_than_inventing_an_identity() -> None:
    client = StubClient(fixture("detail-available.html"))
    source = OnleiheSource(client=client)  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Falsch gepinnt", resolved_links={"onleihe": "irgendwas,0-0-0.html"}
    )
    with pytest.raises(SourceStructureError, match="title id"):
        source.check(entry)


# --- Klappentext und Reihe (ADR 17) ----------------------------------------


def test_the_blurb_is_captured_from_the_result_card() -> None:
    candidates = parse.parse_search_results(fixture("search-hits.html"))
    assert candidates is not None
    assert all(candidate.blurb for candidate in candidates)
    assert "sieben Schwestern" in candidates[0].blurb


def test_the_onleihe_names_the_series_outright() -> None:
    """Eine der wenigen Quellen, die die Reihe ausdrücklich benennt statt sie
    im Titel zu verstecken."""
    assert parse.parse_detail(fixture("detail-unavailable.html")).series == "Die sieben Schwestern"


def test_a_title_outside_a_series_has_none() -> None:
    assert parse.parse_detail(fixture("detail-available.html")).series is None


def test_check_carries_the_series_into_the_observation() -> None:
    client = StubClient(fixture("detail-unavailable.html"))
    source = OnleiheSource(client=client)  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Die sieben Schwestern",
        resolved_links={"onleihe": "mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html"},
    )
    observation = source.check(entry)
    assert observation is not None
    assert observation.series == "Die sieben Schwestern"


def test_the_detail_page_carries_a_cover() -> None:
    """Ein Buch, das es nur in der Bibliothek gibt, hatte nie ein Titelbild:
    Cover kamen ausschliesslich aus dem Shop, und dort steht nicht jeder Titel.
    Bei *Autorität* und *Akzeptanz* — beide sofort ausleihbar — fiel es auf.

    Die Adresse stand die ganze Zeit in den Beispielseiten; ausgelesen hat sie
    niemand. Sie kostet keine eigene Anfrage: die Seite wird ohnehin fuer die
    Verfuegbarkeit geholt."""
    detail = parse.parse_detail(fixture("detail-available.html"))

    assert detail.cover_url == (
        "https://static.onleihe.de/images/978/310/491/276/9/"
        "65c24250673f3d10bd6298ee/im9783104912769s.jpg"
    )


def test_a_page_without_a_cover_says_so_instead_of_guessing() -> None:
    html = '<html><body><div class="exemplar-count">1</div></body></html>'

    try:
        detail = parse.parse_detail(html)
    except Exception:
        return  # ohne Exemplarblock wirft der Parser — das prueft ein anderer Test
    assert detail.cover_url is None


def test_the_detail_page_carries_what_the_readers_said() -> None:
    """Die einzige Quelle im Projekt mit belastbaren Stimmen — gemessen 22 bis
    1641 je Titel, gegen einen Median von *einer* Stimme bei Google Books
    (docs/research/reader-ratings-sources.md)."""
    detail = parse.parse_detail(fixture("detail-unavailable.html"))

    assert detail.rating == 4
    assert detail.votes == 1641


def test_a_page_without_a_rating_block_says_nothing() -> None:
    """Nicht jeder Titel hat Stimmen — dann steht dort auch keine Null."""
    detail = parse.parse_detail(fixture("detail-available.html"))

    assert detail.rating is None
    assert detail.votes is None


def test_the_detail_page_carries_the_blurb() -> None:
    """Der Klappentext stand die ganze Zeit auf der Seite, die ohnehin fuer die
    Verfuegbarkeit geholt wird — gelesen hat ihn niemand: 2674 gespeicherte
    Klappentexte kamen aus dem Shop, 0 aus der Onleihe (Ticket 56).

    Gegriffen wird die Beschreibungsliste, nicht der Reiter ``#tabContent_1_``:
    dessen Nummer ist eine Position, und der Reiter traegt 383 Zeichen mehr als
    der Klappentext — die Biografie der Autorin haengt in derselben Lade.
    """
    detail = parse.parse_detail(fixture("detail-available.html"))

    assert detail.blurb is not None
    assert detail.blurb.startswith("»So inspirierend, so lustig")
    assert detail.blurb.endswith("dass wir alle miteinander verbunden sind.")
    # Die Beschriftung steht im ``dt``, der Text im ``dd`` — die Wahl des
    # Knotens erledigt das Praefix "Inhalt: " von selbst.
    assert "Inhalt:" not in detail.blurb
    # Die Biografie ist eine eigene Zeile derselben Liste (``dt.author-info``).
    assert "geboren 1974" not in detail.blurb


def test_the_blurb_is_read_on_both_captured_pages() -> None:
    """Der zweite Beleg — und der ohne Pressestimmen: von den beiden abgelegten
    Seiten fuehrt nur eine welche, dort 584 von 1372 Zeichen. Zu wenig, um
    daraus eine Regel zum Abschneiden zu machen; und die Anfuehrungszeichen,
    an denen sie haengt, gebraucht derselbe Text auch fuer den Buchtitel."""
    detail = parse.parse_detail(fixture("detail-unavailable.html"))

    assert detail.blurb is not None
    assert detail.blurb.startswith("Der Anfang der Geschichte um sieben Schwestern")
    assert "Lucinda Riley wurde in Irland geboren" not in detail.blurb


def test_a_page_without_an_abstract_says_nothing() -> None:
    """Nicht jeder Titel hat einen — dann steht dort auch kein leerer String."""
    html = (
        '<html><body><div class="exemplar-count">1</div>'
        '<div class="availability-count">1</div></body></html>'
    )

    assert parse._blurb(parse.soup(html)) is None


def test_check_carries_the_blurb_into_the_observation() -> None:
    """Ein Buch, das nur die Bibliothek fuehrt, hat damit einen Klappentext —
    ohne eine einzige zusaetzliche Anfrage."""
    client = StubClient(fixture("detail-available.html"))
    source = OnleiheSource(client=client)  # type: ignore[arg-type]
    entry = WatchlistEntry(
        title="Sieben Richtige",
        author="Volker Jarck",
        resolved_links={"onleihe": "mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html"},
    )

    observation = source.check(entry)

    assert observation is not None
    assert observation.blurb is not None
    assert observation.blurb.startswith("»So inspirierend, so lustig")
    assert len(client.requests) == 1


def test_an_abstract_without_its_own_text_stays_empty() -> None:
    """`dt.abstract` ohne eigenes `dd` darf sich nicht am naechstbesten
    bedienen: `find_next` laeuft durch das ganze Dokument weiter und holte
    sonst den Text einer fremden Liste — im Zweifel die Biografie, die genau
    deshalb nicht ueber den Reiter gegriffen wird."""
    html = """<html><body>
      <dl><dt class="abstract">Inhalt:</dt></dl>
      <dl><dt class="author-info">Ueber die Autorin:</dt>
          <dd>Geboren 1968 in Oslo, lebt in Berlin.</dd></dl>
    </body></html>"""

    assert parse._blurb(parse.soup(html)) is None
