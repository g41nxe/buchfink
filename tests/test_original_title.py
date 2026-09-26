"""Ein Titel in der Originalsprache findet die übersetzte Ausgabe (#77).

Der Anlass: *Scythe* von Neal Shusterman stand auf der Watchlist, und keine
Quelle fand es. OverDrive und der Shop lieferten beide *Die Hüter des Todes*
(ISBN 9783733650155) — die deutsche Ausgabe —, aber der Matcher verglich nur
Titel: „scythe" gegen „die huter des todes", Wert 29 bei einer Schwelle von 85.
Die DNB kennt den Originaltitel einer deutschen Ausgabe (MARC ``240``).

Die Kandidaten unten sind der Suche vom 25.09.2026 nachgebaut: fünf Karten,
alle von Shusterman. Außer der von *Die Hüter des Todes* sind die ISBNs
erfunden — es kommt nur darauf an, dass sie verschieden sind.

Kein Test hier geht ins Netz.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from conftest import overdrive_fixture
from ebook_watchlist.config import WatchlistEntry
from ebook_watchlist.dnb import Dnb, OriginalTitles, Record
from ebook_watchlist.matching import Candidate, Confidence, Query, by_original_title, match
from ebook_watchlist.sources.base import RunContext
from ebook_watchlist.sources.overdrive.source import OverdriveSource
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 26, 6, 0)

GUARDIANS = "9783733650155"
WRATH = "9783733650162"
LEGACY = "9783733650179"
DRY = "9783737341011"
CHAMBER = "9783737341028"

SCYTHE = Query(title="Scythe", author="Neal Shusterman")

CARDS = [
    Candidate(title="Der Zorn der Gerechten", author="Neal Shusterman", identifier=WRATH,
              payload="zorn"),
    Candidate(title="Die Hüter des Todes", author="Neal Shusterman", identifier=GUARDIANS,
              payload="hueter"),
    Candidate(title="Das Vermächtnis der Ältesten", author="Neal Shusterman", identifier=LEGACY,
              payload="erbe"),
    Candidate(title="Dry", author="Neal Shusterman", identifier=DRY, payload="dry"),
    Candidate(title="Die Kammer der Erinnerung", author="Neal Shusterman", identifier=CHAMBER,
              payload="kammer"),
]

ORIGINALS = {
    GUARDIANS: "Scythe",
    WRATH: "Thunderhead",
    LEGACY: "The Toll",
    DRY: "Dry",
    CHAMBER: None,
}


class Lookup:
    """Die DNB als Wörterbuch, und gezählt wird, wonach gefragt wurde."""

    def __init__(self, answers: dict[str, str | None]) -> None:
        self.answers = answers
        self.asked: list[list[str]] = []

    def __call__(self, isbns: Sequence[str]) -> dict[str, str | None]:
        self.asked.append(list(isbns))
        return {isbn: self.answers.get(isbn) for isbn in isbns}


def assign(query: Query, cards: list[Candidate], answers: dict[str, str | None]):
    lookup = Lookup(answers)
    return by_original_title(query, match(query, cards), lookup), lookup


# --- der Fall aus dem Ticket -----------------------------------------------


def test_the_title_alone_does_not_find_the_translation() -> None:
    """Die Ausgangslage, damit sie nicht in Vergessenheit gerät."""
    assert match(SCYTHE, CARDS).confidence is Confidence.NO_MATCH


def test_scythe_finds_the_german_edition_through_its_original_title() -> None:
    resolution, _ = assign(SCYTHE, CARDS, ORIGINALS)

    assert resolution.confidence is Confidence.AUTO_ACCEPT
    assert resolution.accepted.identifier == GUARDIANS
    # Die Begründung sagt, *wie* zugeordnet wurde — sonst sähe eine
    # Zuordnung „Scythe" → „Die Hüter des Todes" auf der Buchseite aus wie ein
    # Fehler.
    assert "Originaltitel" in resolution.reason
    assert "Scythe" in resolution.reason


def test_the_dnb_title_finds_it_when_the_original_title_is_missing() -> None:
    """Gemessen am 26.09.2026: der Datensatz der deutschen Ausgabe nennt keinen
    Originaltitel, aber seinen Titel „Scythe – Die Hüter des Todes"."""
    resolution, _ = assign(SCYTHE, CARDS, {GUARDIANS: ("Scythe – Die Hüter des Todes",)})

    assert resolution.confidence is Confidence.AUTO_ACCEPT
    assert resolution.accepted.identifier == GUARDIANS
    assert "Scythe" in resolution.reason


def test_the_same_book_twice_is_still_one_book() -> None:
    """Dieselbe ISBN auf zwei Karten — zwei Formate derselben Ausgabe — ist
    kein Zweifel, sondern ein Buch."""
    doubled = [*CARDS, Candidate(title="Die Hüter des Todes", author="Neal Shusterman",
                                  identifier=GUARDIANS, payload="hueter-2")]

    resolution, _ = assign(SCYTHE, doubled, ORIGINALS)

    assert resolution.confidence is Confidence.AUTO_ACCEPT
    assert resolution.accepted.payload == "hueter"


def test_an_original_title_that_hits_two_books_asks() -> None:
    """„Dark Matter" ist ein Originaltitel für zwei Bücher. Still eines davon
    zu nehmen wäre genau die falsche Zuordnung, die monatelang beobachtet
    wird (ADR 9)."""
    twice = {**ORIGINALS, LEGACY: "Scythe"}

    resolution, _ = assign(SCYTHE, CARDS, twice)

    assert resolution.confidence is Confidence.PROVISIONAL
    assert resolution.accepted is None
    assert {c.identifier for c in resolution.indistinguishable} == {GUARDIANS, LEGACY}


def test_a_nearly_matching_original_title_asks() -> None:
    """Dieselbe Schwelle wie beim Titel: ähnlich ist eine Frage, gleich eine
    Antwort."""
    fast = {**ORIGINALS, GUARDIANS: "Scythes"}

    resolution, _ = assign(SCYTHE, CARDS, fast)

    assert resolution.confidence is Confidence.PROVISIONAL


# --- Reihen ----------------------------------------------------------------


def test_the_series_name_is_not_the_title() -> None:
    """*Scythe* ist Band 1 von *Arc of a Scythe*. Nennt die DNB die Reihe als
    Originaltitel, trifft sie jeden Band — und keiner davon ist gemeint."""
    series = {**ORIGINALS, GUARDIANS: "Arc of a Scythe", WRATH: "Arc of a Scythe"}

    resolution, _ = assign(SCYTHE, CARDS, series)

    assert resolution.confidence is Confidence.NO_MATCH


def test_a_later_volume_does_not_stand_in_for_the_first() -> None:
    """Ein Treffer auf Band 2 darf Band 1 nicht ersetzen."""
    cards = [Candidate(title="Die Hüter des Todes 2", author="Neal Shusterman",
                        identifier=WRATH, payload="band-2")]

    resolution, _ = assign(SCYTHE, cards, {WRATH: "Scythe"})

    assert resolution.accepted is None


# --- was die DNB gefragt wird ----------------------------------------------


def test_a_matching_title_costs_no_lookup() -> None:
    """Abnahme: der Fund kostet keine DNB-Anfrage, wenn der Titel schon stimmt."""
    cards = [*CARDS, Candidate(title="Scythe", author="Neal Shusterman",
                                 identifier="9781442472426", payload="scythe")]

    resolution, lookup = assign(SCYTHE, cards, ORIGINALS)

    assert resolution.confidence is Confidence.AUTO_ACCEPT
    assert lookup.asked == []


def test_a_nearly_matching_title_costs_no_lookup_either() -> None:
    """Ein Titelwert über der Schwelle ist schon eine Frage an die Leserin,
    und die DNB soll sie nicht beantworten."""
    cards = [Candidate(title="Scythes", author="Neal Shusterman", identifier=WRATH,
                        payload="x")]

    _, lookup = assign(SCYTHE, cards, ORIGINALS)

    assert lookup.asked == []


def test_only_cards_by_the_same_author_with_an_isbn_are_looked_up() -> None:
    cards = [
        *CARDS,
        Candidate(title="Scythe of Doom", author="Jemand Anders", identifier="9780000000001",
                  payload="fremd"),
        Candidate(title="Ohne Nummer", author="Neal Shusterman", payload="ohne"),
    ]

    _, lookup = assign(SCYTHE, cards, ORIGINALS)

    assert len(lookup.asked) == 1
    assert set(lookup.asked[0]) == {GUARDIANS, WRATH, LEGACY, DRY, CHAMBER}


def test_without_an_author_nothing_is_looked_up() -> None:
    """Die Autor:in ist die Hälfte des Belegs: ohne sie bestätigte ein
    gleicher Originaltitel eines fremden Buchs die Zuordnung allein."""
    resolution, lookup = assign(Query(title="Scythe"), CARDS, ORIGINALS)

    assert resolution.accepted is None
    assert lookup.asked == []


# --- das Gedächtnis: erst die Tabelle, dann die DNB ------------------------

TRANSLATION = (
    '<?xml version="1.0"?><searchRetrieveResponse><numberOfRecords>1</numberOfRecords>'
    '<record><datafield tag="240"><subfield code="a">Scythe</subfield></datafield>'
    '<datafield tag="245"><subfield code="a">Die Hüter des Todes</subfield></datafield>'
    '<datafield tag="041"><subfield code="a">ger</subfield></datafield></record>'
    "</searchRetrieveResponse>"
)
EMPTY = (
    '<?xml version="1.0"?><searchRetrieveResponse>'
    "<numberOfRecords>0</numberOfRecords></searchRetrieveResponse>"
)


class Library:
    """Die DNB als Stub: zählt die Anfragen und antwortet der Reihe nach."""

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.asked.append((params or {}).get("query", ""))
        answer = self.answers.pop(0) if self.answers else EMPTY
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def db(store: Store) -> Store:
    return store


def test_a_known_original_title_is_read_from_the_table(db: Store) -> None:
    db.save_dnb(GUARDIANS, Record(title="Die Hüter des Todes", original_title="Scythe"), NOW)
    library = Library()

    title = OriginalTitles(db, Dnb(client=library), budget=5, now=NOW)([GUARDIANS])

    assert title == {GUARDIANS: ("Scythe", "Die Hüter des Todes")}
    assert library.asked == []


def test_a_known_silence_is_not_asked_again(db: Store) -> None:
    db.save_dnb(CHAMBER, None, NOW)
    library = Library()

    title = OriginalTitles(db, Dnb(client=library), budget=5, now=NOW)([CHAMBER])

    assert title == {CHAMBER: ()}
    assert library.asked == []


def test_an_unknown_isbn_is_asked_and_remembered(db: Store) -> None:
    """Die Antwort landet dort, wo der Lauf sie ohnehin abgelegt hätte — der
    nächste Lauf fragt dieselbe ISBN nicht noch einmal (ADR 25)."""
    library = Library(TRANSLATION)

    title = OriginalTitles(db, Dnb(client=library), budget=5, now=NOW)([GUARDIANS])

    assert title[GUARDIANS][0] == "Scythe"
    assert library.asked == [f"WOE={GUARDIANS}"]
    assert db.dnb_facts([GUARDIANS])[GUARDIANS].original_title == "Scythe"
    assert db.dnb_languages()[GUARDIANS] == "ger"


def test_the_budget_holds_during_the_search(db: Store) -> None:
    """Dieselbe Obergrenze je Lauf wie beim Nachschlagen hinter dem Snapshot:
    was die Zuordnung verbraucht, fehlt dort."""
    library = Library()
    title = OriginalTitles(db, Dnb(client=library), budget=2, now=NOW)

    title([GUARDIANS, WRATH, LEGACY])

    assert len(library.asked) == 2
    assert title.spent == 2


def test_a_throttled_library_spends_the_whole_budget(db: Store) -> None:
    """429 heißt Halt — auch für das Nachschlagen hinter dem Snapshot."""
    from ebook_watchlist.http import RateLimited

    library = Library(RateLimited("429"), TRANSLATION)
    title = OriginalTitles(db, Dnb(client=library), budget=5, now=NOW)

    assert title([GUARDIANS, WRATH]) == {}
    assert len(library.asked) == 1
    assert title.spent == 5


def test_without_a_library_only_the_table_answers(db: Store) -> None:
    db.save_dnb(GUARDIANS, Record(original_title="Scythe"), NOW)

    assert OriginalTitles(db)([GUARDIANS, WRATH]) == {GUARDIANS: ("Scythe",)}


# --- im Lauf: eine Quelle, ein Eintrag ------------------------------------


class StubClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.text


def test_dark_matter_is_linked_through_the_dnb(db: Store) -> None:
    """Der zweite reale Fall, mit aufgezeichneten Antworten: OverDrive führt
    „Der Zeitenläufer (Dark Matter)", die DNB sagt zu seiner ISBN „Dark
    Matter". Ohne ISBN am Eintrag blieb das bisher offen (test_overdrive)."""
    from conftest import FIXTURES

    library = Library((FIXTURES / "dnb" / "translation.xml").read_text(encoding="utf-8"))
    context = RunContext(
        profile_slug="test",
        store=db,
        now=NOW,
        original_titles=OriginalTitles(db, Dnb(client=library), budget=5, now=NOW),
    )
    source = OverdriveSource(client=StubClient(overdrive_fixture("search-hits.json")))

    linked = source.linked_entry(WatchlistEntry(title="Dark Matter", author="Blake Crouch"),
                                 context)

    assert linked.resolved_links["overdrive"] == "https://voebb.overdrive.com/media/3222096"
    assert library.asked == ["WOE=9783641171421"]
    link = db.get_book_source(context.book_for(WatchlistEntry(title="Dark Matter",
                                                              author="Blake Crouch")),
                              "overdrive")
    assert '"outcome": "linked"' in link.details
    assert "Originaltitel" in link.details


def test_what_the_search_spent_is_missing_behind_the_snapshot(data_dir) -> None:
    """Ein Budget je Lauf, nicht zwei: das Nachschlagen hinter dem Snapshot
    bekommt, was die Zuordnung übrig gelassen hat."""
    from dataclasses import replace

    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.run import _ask_the_library

    db = Store(paths.db_path())
    run_id = db.start_run("test", "cli", NOW)
    db.append(
        run_id,
        "test",
        [
            Observation(source="beam", source_item_id=str(n), title=f"Buch {n}",
                        match_reason=MatchReason.GENRE_CATEGORY, isbn=f"978000000000{n}")
            for n in range(5)
        ],
        NOW,
    )
    library = Library()

    _ask_the_library(db, library, replace(load_settings(), dnb_budget=5), spent=3)

    assert len(library.asked) == 2


def test_a_linked_title_costs_no_dnb_request_in_the_run(db: Store) -> None:
    library = Library()
    context = RunContext(
        profile_slug="test",
        store=db,
        now=NOW,
        original_titles=OriginalTitles(db, Dnb(client=library), budget=5, now=NOW),
    )
    source = OverdriveSource(client=StubClient(overdrive_fixture("search-hits.json")))

    source.linked_entry(WatchlistEntry(title="Der Zeitenläufer", author="Blake Crouch"), context)

    assert library.asked == []
