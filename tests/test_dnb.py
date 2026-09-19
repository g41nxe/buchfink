"""Die DNB als Auskunft über ein Buch (Ticket 42).

Kein Test hier geht ins Netz: die drei Prüfmuster sind echte SRU-Antworten
vom 06.09.2026.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ebook_watchlist.dnb import Dnb, Record, parse
from ebook_watchlist.http import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "dnb"


def antwort(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- auswerten --------------------------------------------------------------


def test_a_bundle_names_the_isbns_it_contains() -> None:
    """``770 $i Enthält $z`` — MARCs Entsprechung zu ONIX "01 includes".
    Genau das, was der Name "David Hunter: 3in1 Bundle" verschweigt."""
    datensatz = parse(antwort("bundle-3in1.xml"))

    assert datensatz.contains == (
        "9783644200418",
        "9783644200616",
        "9783644204119",
    )


def test_the_sort_marks_around_the_article_are_removed() -> None:
    """Die DNB klammert den Artikel für die Sortierung ein:
    ``&#152;Der&#156; Kruzifix-Killer``. Ungefiltert stünde das im Titel."""
    datensatz = parse(antwort("bundle-slash.xml"))

    assert datensatz.title == "Der Kruzifix-Killer/Der Vollstrecker"


def test_the_subtitle_says_how_many_volumes() -> None:
    """Was der Shop in den Titel quetscht, führt die DNB getrennt — und hier
    steht die Bandzahl im Klartext."""
    datensatz = parse(antwort("bundle-slash.xml"))

    assert datensatz.subtitle == "Zwei Hunter-und-Garcia-Thriller in einem E-Book"


def test_language_is_answered_where_no_source_answers_it() -> None:
    """Kein Shop und keine Bibliothek nennt die Sprache. Ohne sie kann eine
    japanische Ausgabe auf dem Stapel landen (Ticket 31)."""
    assert parse(antwort("bundle-3in1.xml")).language == "ger"


def test_the_series_comes_out_of_490() -> None:
    assert parse(antwort("bundle-3in1.xml")).series == "David Hunter"


def test_a_translation_names_its_original_title() -> None:
    """``240 $a`` ist der Einheitstitel — bei einer Übersetzung der Titel des
    Originals. Mit ihm findet sich das Buch auch dort, wo nur die englische
    Ausgabe steht (#17)."""
    assert parse(antwort("translation.xml")).original_title == "Dark Matter"


def test_the_keywords_are_the_publishers_own_words() -> None:
    """``653`` trägt die Schlagwörter aus dem VLB — Motive und Vergleichstitel,
    die weder der Titel noch der Klappentext nennt (#17). Was in Klammern
    beginnt, ist ein Code für den Handel (Produktform, Warengruppe, BISAC)
    und sagt dem Bewerter nichts."""
    schlagwoerter = parse(antwort("translation.xml")).keywords

    assert "Alternative Realität" in schlagwoerter
    assert "Der Marsianer" in schlagwoerter
    assert not any(wort.startswith("(") for wort in schlagwoerter)


def test_a_book_without_an_original_has_no_original_title() -> None:
    assert parse(antwort("bundle-slash.xml")).original_title is None


def test_the_publisher_comes_out_of_264() -> None:
    """Die Rückfallquelle für den Verlag, wenn die Detailseite ihn nicht nennt (#28)."""
    assert parse(antwort("translation.xml")).publisher == "Goldmann Verlag"


def test_an_unknown_isbn_is_an_empty_record_not_an_error() -> None:
    """Neun von dreißig kennt die DNB nicht. Das ist eine Antwort."""
    datensatz = parse(antwort("nothing.xml"))

    assert datensatz.is_empty
    assert datensatz == Record()


# --- fragen -----------------------------------------------------------------


class StubClient:
    def __init__(self, payload: str | Exception) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.calls.append({"url": url, "params": params or {}})
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_the_isbn_goes_into_the_query() -> None:
    client = StubClient(antwort("bundle-3in1.xml"))

    Dnb(client=client).about("9783644025028")

    assert client.calls[0]["params"]["query"] == "WOE=9783644025028"
    assert client.calls[0]["params"]["recordSchema"] == "MARC21-xml"


def test_an_unknown_book_answers_none() -> None:
    assert Dnb(client=StubClient(antwort("nothing.xml"))).about("9780000000002") is None


def test_an_unreachable_library_does_not_end_a_run() -> None:
    """Dieselbe Zurückhaltung wie bei einem Titelbild: was hier schiefgeht,
    darf höchstens diese eine Auskunft kosten."""
    assert Dnb(client=StubClient(FetchError("weg"))).about("9783644025028") is None


def test_every_question_is_counted() -> None:
    """Die Obergrenze je Lauf setzt der Aufrufer durch — gezählt wird hier,
    weil die DNB keine zulässige Frequenz dokumentiert."""
    dnb = Dnb(client=StubClient(antwort("bundle-3in1.xml")))

    dnb.about("9783644025028")
    dnb.about("9783843714594")

    assert dnb.asked == 2


@pytest.mark.parametrize("name", ["bundle-3in1.xml", "bundle-slash.xml"])
def test_a_real_answer_is_never_empty(name: str) -> None:
    assert not parse(antwort(name)).is_empty
