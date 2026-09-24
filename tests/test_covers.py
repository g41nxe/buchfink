"""Titelbilder — einmal geholt, danach lokal (Ticket 15).

Kein Test hier geht ins Netz.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from conftest import beam_fixture, beam_tiles, describe, give_profile, needs_vocabulary
from ebook_watchlist.covers import MIN_BYTES, CoverStore, file_name
from ebook_watchlist.http import FetchError, NotFound, RateLimited
from ebook_watchlist.sources.beam import parse as beam_parse

BEAM = Path(__file__).parent / "fixtures" / "beam"
NOW = datetime(2026, 9, 4, 20, 0)

IMAGE = b"\xff\xd8\xff" + b"x" * MIN_BYTES  # gross genug, um kein Platzhalter zu sein


class StubClient:
    """Zaehlt, wie oft geholt wurde — der Punkt der ganzen Uebung."""

    def __init__(self, payload: bytes | Exception = IMAGE) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


# --- aus den Seiten lesen ---------------------------------------------------


def test_every_tile_carries_a_cover() -> None:
    tiles = beam_tiles("search-hits.html")
    with_cover = [tile for tile in tiles if tile.cover_url]

    assert len(with_cover) == len(tiles) == 48
    assert all(url.startswith("https://") for url in (tile.cover_url for tile in with_cover))


def test_the_address_comes_from_the_srcset_not_the_placeholder_pixel() -> None:
    """Das Theme laedt die Bilder nach; im ``src`` steht nur ein Pixel."""
    tiles = beam_tiles("search-hits.html")
    krieg = next(tile for tile in tiles if tile.product_id == "606983")

    assert krieg.cover_url == (
        "https://www.beam-shop.de/media/image/5b/f2/e2/9783104911854_200x200.jpg"
    )
    assert "pixel.jpg" not in (krieg.cover_url or "")


def test_the_detail_page_offers_the_larger_one() -> None:
    detail = beam_parse.parse_detail(beam_fixture("product-detail.html"))
    assert detail.cover_url is not None
    assert "600x600" in detail.cover_url


def test_a_page_without_an_image_simply_has_none() -> None:
    html = (
        '<html><body><div class="product--details">'
        '<meta itemprop="price" content="9.99"></div></body></html>'
    )
    assert beam_parse.parse_detail(html).cover_url is None


# --- ablegen ----------------------------------------------------------------


def test_the_name_is_the_address_hashed(tmp_path: Path) -> None:
    name = file_name("https://example.invalid/a/9783104911854_200x200.jpg")
    assert name.endswith(".jpg")
    # Keine Buch-Id im Namen: dasselbe Bild ist eine Datei, gleichgueltig ob
    # es an einem Vorschlag oder an einer book-Zeile haengt.
    assert "17" not in name.split(".")[0][:2]


def test_a_changed_cover_becomes_a_new_file() -> None:
    """Sonst zeigte ein alter Verweis stillschweigend auf ein anderes Bild."""
    first = file_name("https://example.invalid/alt.jpg")
    second = file_name("https://example.invalid/neu.jpg")
    assert first != second


def test_it_is_fetched_once_and_then_read_from_disk(tmp_path: Path) -> None:
    store = CoverStore(tmp_path / "covers")
    client = StubClient()

    name = store.fetch(client, "https://example.invalid/a.jpg")
    assert name is not None
    assert store.has(name)
    assert len(client.calls) == 1

    assert store.fetch(client, "https://example.invalid/a.jpg") == name
    assert len(client.calls) == 1  # nicht noch einmal


def test_a_placeholder_pixel_is_not_kept(tmp_path: Path) -> None:
    """Shopware liefert ein 1x1-Pixel, solange das echte Bild fehlt."""
    store = CoverStore(tmp_path / "covers")
    assert store.fetch(StubClient(b"tiny"), "https://example.invalid/a.jpg") is None
    assert not (tmp_path / "covers").exists() or not any((tmp_path / "covers").iterdir())


@pytest.mark.parametrize("failure", [FetchError("weg"), NotFound("weg")])
def test_a_missing_image_is_not_a_reason_to_fail_a_run(tmp_path: Path, failure: Exception) -> None:
    """Ein Buch ohne Bild ist ein Buch mit einem Platzhalter."""
    store = CoverStore(tmp_path / "covers")
    assert store.fetch(StubClient(failure), "https://example.invalid/a.jpg") is None


def test_throttling_is_passed_through(tmp_path: Path) -> None:
    """Da hat der Shop ausdruecklich Halt gesagt — das gilt fuer alles Weitere."""
    store = CoverStore(tmp_path / "covers")
    with pytest.raises(RateLimited):
        store.fetch(StubClient(RateLimited("429")), "https://example.invalid/a.jpg")


# --- ein Bild darf keinen Lauf kosten (Review-Befund 3) ---------------------


def test_a_refusal_by_the_shop_is_a_fetch_error(tmp_path: Path) -> None:
    """403 ist die Antwort, mit der ein Shop aussperrt. Sie kam bis hierher als
    ``requests.HTTPError`` an — den fängt dieser Weg nicht, und der Lauf starb
    daran."""
    store = CoverStore(tmp_path / "covers")
    assert store.fetch(StubClient(FetchError("403")), "https://example.invalid/a.jpg") is None


def test_one_broken_image_does_not_stop_the_others(tmp_path: Path, monkeypatch) -> None:
    """Dieselbe Überlegung wie bei einer einzelnen Quelle: was hier schiefgeht,
    darf höchstens dieses eine Bild kosten."""
    import requests

    from ebook_watchlist import paths
    from ebook_watchlist.covers import fetch_for_books
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.store import Store

    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    store = Store(paths.db_path())
    first = store.find_or_create_book(isbn=None, title="Eins", now=NOW)
    second = store.find_or_create_book(isbn=None, title="Zwei", now=NOW)

    class Blocking:
        def __init__(self) -> None:
            self.calls = 0

        def get_bytes(self, url: str) -> bytes:
            self.calls += 1
            if self.calls == 1:
                raise requests.HTTPError("403 Client Error")
            return IMAGE

    def seen(book_id: int) -> Observation:
        return Observation(
            source="beam",
            source_item_id=str(book_id),
            title="Egal",
            match_reason=MatchReason.WATCHLIST,
            book_id=book_id,
            cover_url=f"https://example.invalid/{book_id}.jpg",
        )

    client = Blocking()
    fetch_for_books(store, client, [seen(first.id), seen(second.id)])

    assert client.calls == 2
    assert store.book(first.id).cover_file is None
    assert store.book(second.id).cover_file is not None


def test_the_cover_address_survives_the_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Sie stand in der Kachel, wurde ausgelesen, gesetzt — und beim Speichern
    weggeworfen, weil es die Spalte nicht gab. Für Watchlist-Titel fiel das nie
    auf: dort holt derselbe Lauf das Bild. Für eine Entdeckung war sie weg."""
    from ebook_watchlist import paths
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.store import Store

    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    store = Store(paths.db_path())
    beobachtung = Observation(
        source="beam",
        source_item_id="1",
        title="Ein Fund",
        match_reason=MatchReason.GENRE_CATEGORY,
        cover_url="https://beam.invalid/media/9783104911854_200x200.jpg",
    )
    run = store.start_run("t", "cli", NOW)
    store.append(run, "t", [beobachtung], NOW)

    zurueck = store.latest_observations("t", [("beam", "1")])[("beam", "1")]

    assert zurueck.cover_url == beobachtung.cover_url


def test_the_same_image_is_one_file_for_a_find_and_for_a_book(tmp_path: Path) -> None:
    """Waere die Buch-Id Teil des Namens, wuerde dasselbe Cover ein zweites Mal
    geholt, sobald aus dem Vorschlag ein Buch wird."""
    store = CoverStore(tmp_path / "covers")
    client = StubClient()
    url = "https://example.invalid/9783104911854_200x200.jpg"

    als_vorschlag = store.fetch(client, url)  # noch keine book-Zeile
    als_buch = store.fetch(client, url)  # jetzt beobachtet

    assert als_vorschlag == als_buch
    assert len(client.calls) == 1


# --- der Stapel: nur fuer die, die stehen bleiben --------------------------


@needs_vocabulary
def test_only_the_pile_costs_an_image(data_dir: Path) -> None:
    """Unter drei Sternen steht ein Vorschlag gar nicht mehr im Stapel — ein
    Bild dafuer zu holen waere eine Anfrage fuer etwas, das niemand sieht."""
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.run import _fetch_suggestion_covers
    from ebook_watchlist.store import Store

    store, settings = Store(paths.db_path()), load_settings()

    def fund(item_id: str) -> Observation:
        return Observation(
            source="beam",
            source_item_id=item_id,
            title=f"Fund {item_id}",
            author="Wer Auch Immer",
            match_reason=MatchReason.GENRE_CATEGORY,
            price_cents=399,
            blurb="Ein Schiff, allein im Dunkeln.",
            cover_url=f"https://example.invalid/{item_id}.jpg",
        )

    run_id = store.start_run(settings.slug, "cli", NOW)
    store.append(run_id, settings.slug, [fund("bleibt"), fund("faellt")], NOW)
    give_profile(store)
    describe(store, "item:beam:faellt", 1, "")

    client = StubClient()
    _fetch_suggestion_covers(store, settings, client)

    assert client.calls == ["https://example.invalid/bleibt.jpg"]
    assert paths.covers_dir().joinpath(file_name(client.calls[0])).exists()


def test_a_suggestion_without_an_address_costs_nothing(data_dir: Path) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.run import _fetch_suggestion_covers
    from ebook_watchlist.store import Store

    store, settings = Store(paths.db_path()), load_settings()
    ohne = Observation(
        source="beam",
        source_item_id="1",
        title="Ohne Bild",
        author="Wer Auch Immer",
        match_reason=MatchReason.GENRE_CATEGORY,
        price_cents=399,
        blurb="Ein Schiff, allein im Dunkeln.",
    )
    run_id = store.start_run(settings.slug, "cli", NOW)
    store.append(run_id, settings.slug, [ohne], NOW)

    client = StubClient()
    _fetch_suggestion_covers(store, settings, client)
    assert client.calls == []


def test_the_detail_page_cover_is_kept_when_the_blurb_is_fetched(data_dir: Path) -> None:
    """Die Detailseite wird fuer den Klappentext ohnehin geholt und traegt das
    groessere Bild. Es dort fallen zu lassen hiesse, dieselbe Seite spaeter ein
    zweites Mal zu holen."""
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.evidence import gather as _with_evidence
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.sources.base import Item
    from ebook_watchlist.store import Store

    store = Store(paths.db_path())
    settings = load_settings()

    beobachtung = Observation(
        source="beam",
        source_item_id="7",
        title="Ein Fund",
        match_reason=MatchReason.GENRE_CATEGORY,
        blurb="Anriss …",
        cover_url="https://beam.invalid/klein_200x200.jpg",
    )

    class Quelle:
        name = "beam"

        def item(self, source_item_id: str) -> Item:
            return Item(
                source_item_id=source_item_id,
                title="Ein Fund",
                blurb="Der ganze Klappentext, deutlich laenger als der Anriss.",
                cover_url="https://beam.invalid/gross_600x600.jpg",
            )

    zurueck = _with_evidence(store, settings, [beobachtung], [Quelle()])

    assert zurueck[0].cover_url == "https://beam.invalid/gross_600x600.jpg"
    gespeichert = store.latest_observations(settings.slug, [("beam", "7")])[("beam", "7")]
    assert gespeichert.cover_url == "https://beam.invalid/gross_600x600.jpg"


def test_the_candidates_of_an_open_choice_get_their_images(data_dir: Path) -> None:
    """Ticket 41 haengt die Bildadresse an jeden Kandidaten — vergleichen ist
    eine Frage ans Auge —, aber geholt hat sie niemand: Cover kommen aus
    Beobachtungen, und ein Kandidat ist keine. Dass es zu funktionieren schien,
    lag an Bildern, die beim Bauen der Entwuerfe von Hand im Ordner landeten."""
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.covers import fetch_for_candidates
    from ebook_watchlist.models import LinkOutcome
    from ebook_watchlist.relations import RelationKind
    from ebook_watchlist.store import Store

    store, settings = Store(paths.db_path()), load_settings()
    buch = store.find_or_create_book(isbn=None, title="Dark Matter", author="Blake Crouch", now=NOW)
    store.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    store.put_book_source(
        buch.id,
        "beam",
        outcome=str(LinkOutcome.UNSURE),
        url=None,
        resolved_at=NOW,
        reason="der gesuchte Titel steckt im gefundenen",
        candidates=[
            {"title": "Der Zeitenläufer", "author": "Crouch", "url": "https://x/1",
             "cover_url": "https://example.invalid/mit.jpg"},
            {"title": "Ohne Bild", "author": "Crouch", "url": "https://x/2", "cover_url": None},
        ],
    )

    client = StubClient()
    fetch_for_candidates(store, settings.slug, client)

    assert client.calls == ["https://example.invalid/mit.jpg"]
    assert paths.covers_dir().joinpath(file_name(client.calls[0])).exists()


def test_an_image_already_on_disk_costs_no_request(data_dir: Path) -> None:
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.covers import CoverStore, fetch_for_candidates
    from ebook_watchlist.models import LinkOutcome
    from ebook_watchlist.relations import RelationKind
    from ebook_watchlist.store import Store

    store, settings = Store(paths.db_path()), load_settings()
    url = "https://example.invalid/schon-da.jpg"
    covers = CoverStore(paths.covers_dir())
    covers.directory.mkdir(parents=True, exist_ok=True)
    covers.path(file_name(url)).write_bytes(b"x" * 5000)

    buch = store.find_or_create_book(isbn=None, title="Egal", author="Wer", now=NOW)
    store.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    store.put_book_source(
        buch.id, "beam", outcome=str(LinkOutcome.UNSURE), url=None, resolved_at=NOW,
        reason="unklar",
        candidates=[{"title": "Egal", "author": "Wer", "url": "https://x/1", "cover_url": url}],
    )

    client = StubClient()
    fetch_for_candidates(store, settings.slug, client)

    assert client.calls == []


# --- ein besseres Bild ersetzt ein schlechteres (#10) -----------------------


def jpeg(breite: int, hoehe: int) -> bytes:
    """Ein JPEG-Kopf mit SOF0 — mehr liest ``pixels`` nicht."""
    sof = b"\xff\xc0\x00\x11\x08" + hoehe.to_bytes(2, "big") + breite.to_bytes(2, "big")
    return b"\xff\xd8" + b"\xff\xe0\x00\x04ab" + sof + b"\x03" + b"x" * MIN_BYTES


def png(breite: int, hoehe: int) -> bytes:
    ihdr = breite.to_bytes(4, "big") + hoehe.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + ihdr + b"x" * MIN_BYTES


def test_the_size_is_read_from_the_header() -> None:
    from ebook_watchlist.covers import pixels

    assert pixels(jpeg(134, 200)) == 134 * 200
    assert pixels(png(600, 600)) == 600 * 600
    assert pixels(b"GIF89a" + b"x" * MIN_BYTES) is None


class ByAddress:
    """Liefert je Adresse ein anderes Bild und zaehlt mit."""

    def __init__(self, bilder: dict[str, bytes]) -> None:
        self.bilder = bilder
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        return self.bilder[url]


def _gesehen(book_id: int, url: str):
    from ebook_watchlist.models import MatchReason, Observation

    return Observation(source="beam", source_item_id=str(book_id), title="Egal",
                       match_reason=MatchReason.WATCHLIST, book_id=book_id, cover_url=url)


@pytest.fixture
def buchlager(tmp_path: Path, monkeypatch):
    from ebook_watchlist import paths
    from ebook_watchlist.store import Store

    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    return Store(paths.db_path())


def test_a_larger_cover_replaces_a_smaller_one(buchlager) -> None:
    """Das erste Bild gewann bisher fuer immer: *Dark Matter* sass auf einer
    Kachel von 134x200 fest, obwohl Shop und OverDrive groessere liefern."""
    from ebook_watchlist.covers import fetch_for_books

    buch = buchlager.find_or_create_book(isbn=None, title="Dark Matter", now=NOW)
    klein, gross = "https://example.invalid/klein.jpg", "https://example.invalid/gross.jpg"
    client = ByAddress({klein: jpeg(134, 200), gross: jpeg(600, 600)})

    fetch_for_books(buchlager, client, [_gesehen(buch.id, klein)])
    fetch_for_books(buchlager, client, [_gesehen(buch.id, gross)])

    assert buchlager.book(buch.id).cover_file == file_name(gross)


def test_a_smaller_cover_does_not_replace_a_larger_one(buchlager) -> None:
    from ebook_watchlist.covers import fetch_for_books

    buch = buchlager.find_or_create_book(isbn=None, title="Dark Matter", now=NOW)
    klein, gross = "https://example.invalid/klein.jpg", "https://example.invalid/gross.jpg"
    client = ByAddress({klein: jpeg(134, 200), gross: jpeg(600, 600)})

    fetch_for_books(buchlager, client, [_gesehen(buch.id, gross)])
    fetch_for_books(buchlager, client, [_gesehen(buch.id, klein)])

    assert buchlager.book(buch.id).cover_file == file_name(gross)


def test_the_same_address_costs_nothing(buchlager) -> None:
    """Dieselbe Adresse ist dasselbe Bild — kein Abruf, kein Vergleich."""
    from ebook_watchlist.covers import fetch_for_books

    buch = buchlager.find_or_create_book(isbn=None, title="Dark Matter", now=NOW)
    adresse = "https://example.invalid/eins.jpg"
    client = ByAddress({adresse: jpeg(600, 600)})

    fetch_for_books(buchlager, client, [_gesehen(buch.id, adresse)])
    fetch_for_books(buchlager, client, [_gesehen(buch.id, adresse)])

    assert client.calls == [adresse]


def test_every_source_gets_its_chance_not_only_the_first(buchlager) -> None:
    """Je Lauf zaehlte nur die erste Beobachtung eines Buchs. Bei *Dark
    Matter* kommt OverDrive mit einem kleinen Bild vor dem Shop mit 600x600 —
    das kleine wurde verworfen, das grosse nie gefragt."""
    from ebook_watchlist.covers import fetch_for_books

    buch = buchlager.find_or_create_book(isbn=None, title="Dark Matter", now=NOW)
    alt, klein, gross = ("https://example.invalid/kachel.jpg",
                         "https://example.invalid/overdrive.jpg",
                         "https://example.invalid/detail.jpg")
    client = ByAddress({alt: jpeg(134, 200), klein: jpeg(100, 150), gross: jpeg(600, 600)})
    fetch_for_books(buchlager, client, [_gesehen(buch.id, alt)])

    fetch_for_books(buchlager, client, [_gesehen(buch.id, klein), _gesehen(buch.id, gross)])

    assert buchlager.book(buch.id).cover_file == file_name(gross)


def test_the_narrow_run_fetches_the_candidate_images_too(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der enge Lauf kann die Frage selbst aufwerfen — "Welches Buch ist das
    richtige?" —, holte aber nur die Bilder der Bücher. Die Auswahl stand
    danach bis zum nächsten Rundgang als Reihe gezeichneter Rücken da."""
    from ebook_watchlist import single
    from ebook_watchlist.config import WatchlistEntry

    geholt: list[str] = []
    monkeypatch.setattr(
        single, "_entry_for", lambda *a, **k: WatchlistEntry(title="Egal", author="Wer")
    )

    class Quelle:
        name = "beam"

        def watch(self, entries, context):
            return []

    monkeypatch.setattr(single, "build_sources", lambda settings, client: [Quelle()])
    monkeypatch.setattr(
        single, "fetch_for_candidates", lambda store, slug, client: geholt.append(slug)
    )

    single.check_one(1)

    assert geholt == ["test"]
