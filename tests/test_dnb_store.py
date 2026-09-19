"""Was die DNB-Auskunft in der Datenbank tut (Ticket 42, ADR 25).

Beim Review nach 1.0 fiel auf, dass diese fünf Wege — ``isbns_without_dnb``,
``save_dnb``, ``contained_isbns``, ``prices_by_isbn`` und ``_ask_the_library``
— keinen einzigen Test hatten. Das Auswerten der Antwort war gut geprüft, das
Drumherum gar nicht.

Kein Test hier geht ins Netz.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import update

from ebook_watchlist import paths
from ebook_watchlist.dnb import Record
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import DnbRecordRow, Store

NOW = datetime(2026, 9, 6, 10, 0)
#: Der Slug des Testprofils — nicht "default", das war ein Rateversuch.
SLUG = "test"


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def gesehen(db: Store, isbn: str | None, preis: int | None = 999, nummer: str = "1") -> None:
    run_id = db.start_run(SLUG, "cli", NOW)
    db.append(
        run_id,
        SLUG,
        [
            Observation(
                source="beam",
                source_item_id=nummer,
                title=f"Buch {nummer}",
                match_reason=MatchReason.GENRE_CATEGORY,
                isbn=isbn,
                price_cents=preis,
            )
        ],
        NOW,
    )


# --- wen fragen wir? --------------------------------------------------------


def test_only_isbns_we_have_actually_seen_are_asked_about(db: Store) -> None:
    gesehen(db, "9783644025028")

    assert db.isbns_without_dnb(SLUG, 10) == ["9783644025028"]


def test_an_observation_without_an_isbn_is_never_asked_about(db: Store) -> None:
    """Die DNB antwortet über eine ISBN. Ohne eine gibt es nichts zu fragen."""
    gesehen(db, None)

    assert db.isbns_without_dnb(SLUG, 10) == []


def test_the_isbn_of_a_book_is_asked_before_a_find(db: Store) -> None:
    """Gefragt wurde, was zuletzt gesehen wurde — und jeder Lauf sieht
    Hunderte neuer Funde nach den Watchlist-Titeln. Die ISBNs der eigenen
    Buecher wurden so immer wieder verdraengt: 34 Buecher mit ISBN, einer
    davon mit DNB-Datensatz (#10)."""
    db.find_or_create_book(isbn="9783426306406", title="Autorität", now=NOW)
    gesehen(db, "9783426306406", nummer="1")
    gesehen(db, "9783644025028", nummer="2")  # ein Fund, spaeter gesehen

    assert db.isbns_without_dnb(SLUG, 1) == ["9783426306406"]


def test_the_budget_is_a_hard_limit(db: Store) -> None:
    """Die DNB dokumentiert keine zulässige Anfragefrequenz — deshalb wird der
    Rückstand über mehrere Läufe abgearbeitet (ADR 25)."""
    for nummer in range(5):
        gesehen(db, f"978000000000{nummer}", nummer=str(nummer))

    assert len(db.isbns_without_dnb(SLUG, 2)) == 2


def test_an_answered_isbn_is_not_asked_again(db: Store) -> None:
    gesehen(db, "9783644025028")
    db.save_dnb("9783644025028", Record(title="Ein Buch"), NOW)

    assert db.isbns_without_dnb(SLUG, 10) == []


def test_silence_is_recorded_too(db: Store) -> None:
    """Neun von dreißig kennt die DNB nicht. Ohne diesen Vermerk fragte jeder
    Lauf dieselben erneut — der teuerste denkbare Weg, nichts zu erfahren."""
    gesehen(db, "9783644025028")
    db.save_dnb("9783644025028", None, NOW)

    assert db.isbns_without_dnb(SLUG, 10) == []


def test_an_answer_read_by_an_older_parser_is_asked_again(db: Store) -> None:
    """Originaltitel und Schlagwörter standen immer im Datensatz, nur las sie
    niemand (#17). Ein altes Ja wird deshalb einmal neu gefragt — ein altes
    Nein nicht: was die DNB nicht kannte, kennt sie auch jetzt kaum."""
    gesehen(db, "9783644025028", nummer="1")
    gesehen(db, "9783641171421", nummer="2")
    db.save_dnb("9783644025028", Record(title="Ein Buch"), NOW)
    db.save_dnb("9783641171421", None, NOW)
    with db.session() as session:  # so, wie die Migration alte Zeilen hinterlaesst
        session.execute(update(DnbRecordRow).values(reading=1))
        session.commit()

    assert db.isbns_without_dnb(SLUG, 10) == ["9783644025028"]


def test_original_title_and_keywords_are_kept(db: Store) -> None:
    db.save_dnb(
        "9783641171421",
        Record(
            original_title="Dark Matter",
            keywords=("Quantenphysik", "Der Marsianer"),
            publisher="Goldmann Verlag",
        ),
        NOW,
    )

    fakten = db.dnb_facts(["9783641171421", "9780000000000"])

    assert list(fakten) == ["9783641171421"]
    assert fakten["9783641171421"].original_title == "Dark Matter"
    assert fakten["9783641171421"].keywords == ("Quantenphysik", "Der Marsianer")
    assert fakten["9783641171421"].publisher == "Goldmann Verlag"


# --- was wir aufheben -------------------------------------------------------


def test_the_contained_volumes_survive(db: Store) -> None:
    db.save_dnb(
        "9783644025028",
        Record(title="David Hunter: 3in1 Bundle", contains=("9783644200418", "9783644200616")),
        NOW,
    )

    assert db.contained_isbns("9783644025028") == ("9783644200418", "9783644200616")


def test_asking_twice_does_not_duplicate_the_volumes(db: Store) -> None:
    """Ein zweiter Aufruf darf nichts verdoppeln — dieselbe Regel wie beim
    Import (``ebw seed``)."""
    datensatz = Record(contains=("9783644200418",))
    db.save_dnb("9783644025028", datensatz, NOW)
    db.save_dnb("9783644025028", datensatz, NOW)

    assert db.contained_isbns("9783644025028") == ("9783644200418",)


def test_a_book_the_library_does_not_know_contains_nothing(db: Store) -> None:
    db.save_dnb("9783644025028", None, NOW)

    assert db.contained_isbns("9783644025028") == ()


# --- die Preise, mit denen verglichen wird ----------------------------------


def test_prices_are_looked_up_by_isbn(db: Store) -> None:
    gesehen(db, "9783644200418", preis=999)

    assert db.prices_by_isbn(SLUG, "beam") == {"9783644200418": 999}


def test_the_cheapest_edition_wins(db: Store) -> None:
    """Derselbe Titel kann als mehrere Ausgaben dastehen. Für den Vergleich
    zählt, was der Einzelband **mindestens** kostet."""
    gesehen(db, "9783644200418", preis=1499, nummer="1")
    gesehen(db, "9783644200418", preis=999, nummer="2")

    assert db.prices_by_isbn(SLUG, "beam")["9783644200418"] == 999


def test_a_free_title_is_no_price(db: Store) -> None:
    """Null ist kein Preis, sondern Füllmaterial (ADR 19) — und eine Summe aus
    Nullen wäre ein erfundener Vergleich."""
    gesehen(db, "9783644200418", preis=0)

    assert db.prices_by_isbn(SLUG, "beam") == {}


def test_another_source_is_another_wallet(db: Store) -> None:
    """Preise zweier Shops zu addieren wäre eine Summe, die niemand bezahlen
    kann."""
    gesehen(db, "9783644200418", preis=999)

    assert db.prices_by_isbn(SLUG, "onleihe") == {}


# --- der Schritt im Lauf ----------------------------------------------------


class Bibliothek:
    """Zählt die Anfragen und antwortet der Reihe nach."""

    def __init__(self, *antworten: str | Exception) -> None:
        self.antworten = list(antworten)
        self.gefragt: list[str] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.gefragt.append((params or {}).get("query", ""))
        antwort = self.antworten.pop(0) if self.antworten else LEER
        if isinstance(antwort, Exception):
            raise antwort
        return antwort


LEER = (
    '<?xml version="1.0"?><searchRetrieveResponse>'
    "<numberOfRecords>0</numberOfRecords></searchRetrieveResponse>"
)
MIT_BAND = (
    '<?xml version="1.0"?><searchRetrieveResponse><numberOfRecords>1</numberOfRecords>'
    '<record><datafield tag="245"><subfield code="a">Ein Bundle</subfield></datafield>'
    '<datafield tag="770"><subfield code="i">Enthält</subfield>'
    '<subfield code="z">9783644200418</subfield></datafield></record>'
    "</searchRetrieveResponse>"
)


def test_the_run_asks_at_most_the_budget(db: Store, monkeypatch) -> None:
    """Der Rückstand wird über mehrere Läufe abgearbeitet, nicht an einem Tag."""
    from dataclasses import replace

    from ebook_watchlist.config import load_profile
    from ebook_watchlist.run import _ask_the_library

    for nummer in range(5):
        gesehen(db, f"978000000000{nummer}", nummer=str(nummer))
    client = Bibliothek()

    _ask_the_library(db, client, replace(load_profile(), dnb_budget=2))

    assert len(client.gefragt) == 2


def test_the_run_records_what_it_learned(db: Store) -> None:
    from dataclasses import replace

    from ebook_watchlist.config import load_profile
    from ebook_watchlist.run import _ask_the_library

    gesehen(db, "9783644025028")

    _ask_the_library(db, Bibliothek(MIT_BAND), replace(load_profile(), dnb_budget=5))

    assert db.contained_isbns("9783644025028") == ("9783644200418",)
    assert db.isbns_without_dnb(SLUG, 10) == []


def test_a_throttled_library_stops_the_rest(db: Store) -> None:
    """429 heißt Halt, und zwar für alles Weitere — dieselbe Regel wie beim
    Shop."""
    from dataclasses import replace

    from ebook_watchlist.config import load_profile
    from ebook_watchlist.http import RateLimited
    from ebook_watchlist.run import _ask_the_library

    for nummer in range(3):
        gesehen(db, f"978000000000{nummer}", nummer=str(nummer))
    client = Bibliothek(RateLimited("429"), MIT_BAND, MIT_BAND)

    _ask_the_library(db, client, replace(load_profile(), dnb_budget=5))

    assert len(client.gefragt) == 1


def test_one_broken_answer_does_not_stop_the_others(db: Store) -> None:
    """Der Befund aus dem Review: ein 404 brach den ganzen Stapel ab, obwohl
    er nur diese eine Auskunft kosten darf."""
    from dataclasses import replace

    from ebook_watchlist.config import load_profile
    from ebook_watchlist.http import NotFound
    from ebook_watchlist.run import _ask_the_library

    for nummer in range(3):
        gesehen(db, f"978000000000{nummer}", nummer=str(nummer))
    client = Bibliothek(NotFound("weg"), MIT_BAND, MIT_BAND)

    _ask_the_library(db, client, replace(load_profile(), dnb_budget=5))

    assert len(client.gefragt) == 3


# --- Reihe und Band aufs Buch (#10) -----------------------------------------


def test_the_series_reaches_the_book(db: Store) -> None:
    """Die DNB lieferte die Reihe fuer 33 von 101 ISBNs, auf einer Buch-Zeile
    landete sie nie — 0 von 70. Die Buchseite hat ein Feld dafuer, das
    deshalb immer leer blieb."""
    buch = db.find_or_create_book(isbn="9783426306406", title="Autorität", now=NOW)
    db.save_dnb("9783426306406", Record(series="Southern Reach", series_index="2"), NOW)

    assert db.series_from_dnb() == 1

    gelesen = db.book(buch.id)
    assert (gelesen.series, gelesen.series_index) == ("Southern Reach", "2")


def test_a_series_already_on_the_book_is_kept(db: Store) -> None:
    """Die DNB fuellt Luecken, sie ueberschreibt nichts."""
    buch = db.find_or_create_book(isbn="9783426306406", title="Autorität",
                                  series="Von Hand", now=NOW)
    db.save_dnb("9783426306406", Record(series="Southern Reach", series_index="2"), NOW)

    assert db.series_from_dnb() == 0
    assert db.book(buch.id).series == "Von Hand"


def test_silence_and_a_record_without_series_change_nothing(db: Store) -> None:
    ohne = db.find_or_create_book(isbn="9783426306406", title="Eins", now=NOW)
    stumm = db.find_or_create_book(isbn="9783426306413", title="Zwei", now=NOW)
    db.save_dnb("9783426306406", Record(title="Eins"), NOW)
    db.save_dnb("9783426306413", None, NOW)

    assert db.series_from_dnb() == 0
    assert db.book(ohne.id).series is None
    assert db.book(stumm.id).series is None
