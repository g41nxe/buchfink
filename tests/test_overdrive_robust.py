"""Was OverDrive schicken kann, ohne dass es gemeint ist.

Eine Trefferliste ist voll von Büchern, die uns nichts angehen, und eine
Schnittstelle ändert ihre Gestalt ohne Ankündigung. Beides darf die Quelle
nicht mitreißen — und wo sie doch scheitert, muss sie **sagen, was sich
geändert hat** (ADR 7).

Getrennt von `test_overdrive.py`, weil dort das erwartete Verhalten steht und
hier das unerwartete.
"""

from __future__ import annotations

import json

import pytest

from conftest import overdrive_fixture as fixture
from ebook_watchlist.config import Profile, WatchlistEntry
from ebook_watchlist.sources import registry
from ebook_watchlist.sources.base import SourceStructureError
from ebook_watchlist.sources.overdrive import parse
from ebook_watchlist.sources.overdrive.source import OverdriveSource


class StubClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.text


def treffer(**overrides) -> dict:
    """Ein vollständiger Treffer, aus dem einzelne Felder gebrochen werden."""
    return json.loads(fixture("title.json")) | overrides


def liste(*items: dict) -> str:
    return json.dumps({"totalItems": len(items), "items": list(items)})


# --- ein fremder Nachbar reisst nichts mit ----------------------------------


def test_a_neighbouring_hit_without_copy_counts_does_not_kill_the_source() -> None:
    """Der schwerste Fall: ein Treffer, der uns gar nicht meint, trug keine
    Lizenzzahlen — und riss die Quelle für den ganzen Lauf ab, auch für die
    vierzehn Titel, deren Zuordnung längst stand. Die Onleihe verlangt je
    Karte genau Titel und Link; mehr braucht eine Zuordnung auch hier nicht."""
    fremd = {"id": "999", "title": "Ein ganz anderes Buch"}

    gefunden = parse.parse_search(liste(treffer(), fremd))

    assert [c.title_id for c in gefunden] == ["3222096", "999"]
    assert gefunden[1].isbn is None


def test_a_hit_without_a_title_is_still_loud() -> None:
    """Die Grenze der Nachsicht: ohne Titel ist ein Treffer nicht rankbar, und
    eine Trefferliste ohne Titel ist ein Umbau, keine Eigenheit."""
    with pytest.raises(SourceStructureError, match="ohne Titel"):
        parse.parse_search(liste({"id": "999"}))


def test_a_hit_without_a_number_is_still_loud() -> None:
    """Der Snapshot ist darauf geschlüsselt — eine erfundene Nummer spaltete
    die Geschichte eines Titels still in zwei."""
    with pytest.raises(SourceStructureError, match="ohne id"):
        parse.parse_search(liste({"title": "Ein Buch"}))


# --- fremde Gestalt wird benannt, nicht durchgereicht ------------------------


def test_covers_in_an_unexpected_shape_is_named_not_an_attribute_error() -> None:
    """`covers` als Liste warf einen AttributeError, und der steht im
    Tagesbericht als Panne statt als Auskunft."""
    detail = parse.parse_title(treffer(covers=["etwas", "anderes"]))

    assert detail.cover_url is None


def test_a_description_that_is_not_a_string_does_not_become_one() -> None:
    """Sonst stand `{'text': 'hallo'}` in der Datenbank, im Tagesbericht und im
    Prompt des Bewertungstors."""
    assert parse.parse_title(treffer(description={"text": "hallo"})).blurb is None


def test_every_copy_count_is_checked_not_just_the_first() -> None:
    for feld in ("ownedCopies", "availableCopies", "holdsCount"):
        kaputt = treffer()
        del kaputt[feld]
        with pytest.raises(SourceStructureError, match=feld):
            parse.parse_title(kaputt)


def test_a_response_that_is_not_an_object_is_loud() -> None:
    """200 mit `null` ist eine Antwort, aber keine, die wir lesen können."""
    with pytest.raises(SourceStructureError, match="kein Objekt"):
        parse.payload("null")


# --- die ISBN wird geprueft, nicht geglaubt ---------------------------------


def test_a_hyphenated_isbn_is_normalised() -> None:
    """Der Matcher vergleicht Kennungen zeichengenau: mit Bindestrichen fiele
    die Zuordnung still auf den Titelvergleich zurück, und der findet dieses
    Buch nicht. Schlimmer noch legte eine zweite Schreibweise in
    `books.find_book` eine zweite Buchzeile an."""
    item = treffer(formats=[{"id": "ebook-epub-adobe", "isbn": "978-3-641-17142-1"}])

    assert parse.parse_title(item).isbn == "9783641171421"


def test_something_that_is_not_an_isbn_is_dropped() -> None:
    item = treffer(formats=[{"id": "ebook-epub-adobe", "isbn": "keine-nummer"}])

    assert parse.parse_title(item).isbn is None


# --- Paginierung -------------------------------------------------------------


def test_the_second_page_is_asked_for_as_page_two() -> None:
    """Thunder zählt ab 1, unsere Schleife ab 0. Ohne diesen Test hielt die
    Umrechnung nichts fest — und eine zweite Anfrage auf dieselbe Seite fällt
    niemandem auf."""
    quelle = OverdriveSource(client=StubClient(liste(*[treffer(id=str(i)) for i in range(20)])))

    quelle.resolve(WatchlistEntry(title="Nicht auffindbar", author="Niemand"))

    seiten = [params.get("page") for _, params in quelle.client.requests]
    assert seiten == [None, "2"]


def test_a_short_page_ends_the_search() -> None:
    """Wer weniger als eine volle Seite zurückgibt, hat nichts mehr. Eine
    zweite Anfrage wäre reine Last."""
    quelle = OverdriveSource(client=StubClient(liste(treffer())))

    quelle.resolve(WatchlistEntry(title="Nicht auffindbar", author="Niemand"))

    assert len(quelle.client.requests) == 1


# --- die Registrierung -------------------------------------------------------


def profil(**sources) -> Profile:
    return Profile(slug="t", name="T", sources=sources)


def test_overdrive_is_a_library_not_a_shop() -> None:
    """Fiele es aus `KINDS`, gälte es als Shop: Einkaufswagen-Symbol, und
    `registry.shops()` fragte eine Bibliothek nach Preisen."""
    p = profil(overdrive={}, onleihe={}, beam={})

    assert registry.category(p, "overdrive") == "library"
    assert registry.shops(p) == ["beam"]


def test_each_library_says_which_one_it_is() -> None:
    """Zwei Kacheln "BIBLIOTHEK", die eine "verliehen", die andere "nicht im
    Katalog" — und welche welche war, stand nirgends."""
    p = profil(overdrive={}, onleihe={}, beam={})

    assert registry.label(p, "onleihe") == "Onleihe"
    assert registry.label(p, "overdrive") == "OverDrive"
    # Ein einzelner Shop braucht keinen eigenen Namen: die Art genügt.
    assert registry.label(p, "beam") == "Shop"


# --- zwei Quellen derselben Art (#14) ---------------------------------------


def test_a_second_library_of_the_same_kind_gets_its_own_name() -> None:
    """`voebb: {kind: onleihe}` ist dieselbe Software, aber ein anderer
    Verbund. Die Tabelle kennt nur "onleihe" — wie die zweite heisst, sagt die
    Einrichtung, denn der Name haengt an ihr."""
    p = profil(onleihe={}, voebb={"kind": "onleihe", "name": "VOEBB"})

    assert registry.label(p, "onleihe") == "Onleihe"
    assert registry.label(p, "voebb") == "VOEBB"


def test_the_table_outranks_the_configuration() -> None:
    """Das Werkzeug kennt die Plattformen, die es unterstuetzt; die
    Einrichtung springt nur ein, wo die Tabelle nichts weiss."""
    p = profil(onleihe={"name": "Meine Bibliothek"})

    assert registry.label(p, "onleihe") == "Onleihe"


def test_a_named_shop_keeps_its_name() -> None:
    """Ein zweiter Shop hiesse sonst wie der erste: "Shop"."""
    p = profil(beam={}, tolino={"kind": "beam", "name": "Tolino"})

    assert registry.label(p, "beam") == "Shop"
    assert registry.label(p, "tolino") == "Tolino"
