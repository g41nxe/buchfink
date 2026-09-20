"""OverDrive als zweite Bibliothek (voebb.overdrive.com).

Kein Test hier greift ins Netz. Die Fixtures sind ganze Antworten der
Thunder-Schnittstelle, aufgezeichnet am 2026-09-11; wenn sich die Gestalt
ändert, werden sie neu aufgenommen statt von Hand nachgebessert (ADR 14).
"""

from __future__ import annotations

import json

import pytest

from conftest import overdrive_fixture as fixture
from ebook_watchlist.config import WatchlistEntry
from ebook_watchlist.matching import Confidence
from ebook_watchlist.models import Availability, MatchReason
from ebook_watchlist.sources.base import SourceStructureError
from ebook_watchlist.sources.overdrive import parse
from ebook_watchlist.sources.overdrive.source import OverdriveSource, title_id_from_url


class StubClient:
    """Antwortet immer dasselbe und merkt sich, wonach gefragt wurde."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.text


def source(text: str = "") -> OverdriveSource:
    return OverdriveSource(client=StubClient(text))


# --- ein Titel --------------------------------------------------------------


def test_a_title_is_read_out_of_the_json() -> None:
    detail = parse.parse_title(json.loads(fixture("title.json")))

    assert detail.title == "Der Zeitenläufer (Dark Matter)"
    assert detail.author == "Blake Crouch"
    assert detail.isbn == "9783641171421"


def test_a_lent_out_title_is_unavailable_not_unknown() -> None:
    """Eine Lizenz, keine frei, acht Vormerkungen — verliehen heißt: er kommt
    zurück."""
    detail = parse.parse_title(json.loads(fixture("title.json")))

    assert (detail.owned_copies, detail.available_copies, detail.holds) == (1, 0, 8)
    assert detail.availability is Availability.UNAVAILABLE


def test_a_title_the_library_does_not_own_is_unknown() -> None:
    """Verliehen verspricht eine Rückkehr. Ohne eine einzige Lizenz gibt es
    nichts, was zurückkäme — das ist keine Auskunft über Verfügbarkeit."""
    item = json.loads(fixture("title.json")) | {"ownedCopies": 0, "availableCopies": 0}

    assert parse.parse_title(item).availability is Availability.UNKNOWN


def test_a_title_without_copy_counts_is_a_structure_change() -> None:
    """Eine fehlende Zahl ist kein leerer Wert, sondern ein Umbau. Sie still
    als "nichts verfügbar" zu lesen wäre der eine Fehler, den dieses Werkzeug
    nicht machen darf (ADR 7)."""
    item = json.loads(fixture("title.json"))
    del item["ownedCopies"]

    with pytest.raises(SourceStructureError, match="ownedCopies"):
        parse.parse_title(item)


def test_a_title_without_a_title_is_refused() -> None:
    item = json.loads(fixture("title.json")) | {"title": ""}

    with pytest.raises(SourceStructureError):
        parse.parse_title(item)


# --- die Suche --------------------------------------------------------------


def test_the_search_yields_its_hits() -> None:
    gefunden = parse.parse_search(fixture("search-hits.json"))

    assert [(c.title, c.author, c.title_id) for c in gefunden] == [
        ("Der Zeitenläufer (Dark Matter)", "Blake Crouch", "3222096")
    ]


def test_no_hits_is_an_answer_not_a_failure() -> None:
    """Der Katalog hat nachgesehen und führt ihn nicht. Das ist eine Auskunft."""
    assert parse.parse_search(fixture("search-no-hits.json")) is None


def test_a_response_without_a_hit_list_is_loud() -> None:
    """Ohne diese Unterscheidung sähe ein Umbau der Schnittstelle genauso aus
    wie "heute nichts gefunden" — und niemand merkte es je."""
    with pytest.raises(SourceStructureError, match="items"):
        parse.parse_search(json.dumps({"totalItems": 0}))


def test_something_that_is_not_json_is_loud() -> None:
    with pytest.raises(SourceStructureError, match="kein JSON"):
        parse.parse_search("<html>Wartungsarbeiten</html>")


# --- Zuordnung --------------------------------------------------------------


def test_the_german_edition_is_found_through_its_isbn() -> None:
    """Der Fall, an dem die zweite Bibliothek hängt: die Onleihe führt "Dark
    Matter" nicht, OverDrive führt es als "Der Zeitenläufer (Dark Matter)".

    Über den Titel geht das nicht: der Normalisierer streicht die Klammer als
    Ausgabenrauschen, und übrig bleiben "dark matter" gegen "zeitenlaufer" —
    Wert 26 bei einer Schwelle von 85. Die Kennung trägt es, und zwar mit der
    Mechanik, die beam längst benutzt."""
    quelle = source(fixture("search-hits.json"))

    resolution = quelle.resolve(
        WatchlistEntry(title="Dark Matter", author="Blake Crouch", isbn="9783641171421")
    )

    assert resolution.confidence is Confidence.AUTO_ACCEPT
    assert resolution.reason == "Kennung stimmt überein"
    assert resolution.accepted.payload == "https://voebb.overdrive.com/media/3222096"


def test_without_an_isbn_the_renamed_edition_stays_unmatched() -> None:
    """Die ehrliche Grenze, und sie steht hier, damit sie nicht in Vergessenheit
    gerät: ohne Kennung findet der Titelvergleich dieses Buch nicht. Von den
    fünfzehn beobachteten Büchern tragen dreizehn eine ISBN — die zwei übrigen
    bleiben auf den Titel angewiesen."""
    quelle = source(fixture("search-hits.json"))

    resolution = quelle.resolve(WatchlistEntry(title="Dark Matter", author="Blake Crouch"))

    assert resolution.confidence is not Confidence.AUTO_ACCEPT


def test_a_candidate_brings_its_cover() -> None:
    """Bei einer offenen Zuordnung entscheidet das Auge, welcher Treffer der
    richtige ist (Ticket 41). Die Karte trägt das Bild längst — weitergereicht
    wurde es nicht, und in der Auswahl stand ein Platzhalter."""
    quelle = source(fixture("search-hits.json"))

    resolution = quelle.resolve(
        WatchlistEntry(title="Dark Matter", author="Blake Crouch", isbn="9783641171421")
    )

    assert resolution.accepted.cover_url is not None


def test_an_unknown_title_resolves_to_nothing() -> None:
    quelle = source(fixture("search-no-hits.json"))

    assert quelle.resolve(WatchlistEntry(title="Gibt es nicht", author="Niemand")) is None


def test_the_query_carries_title_and_surname() -> None:
    quelle = source(fixture("search-hits.json"))

    quelle.resolve(WatchlistEntry(title="Dark Matter", author="Blake Crouch"))

    _, params = quelle.client.requests[0]
    assert params["query"] == "Dark Matter Crouch"
    # Nur deutsche EPUB-E-Books, wie bei der Onleihe.
    assert params["format"] == "ebook-epub-adobe"
    assert params["language"] == "de"


# --- Prüfung ----------------------------------------------------------------


def test_an_unresolved_entry_is_skipped_not_guessed() -> None:
    quelle = source(fixture("title.json"))

    assert quelle.check(WatchlistEntry(title="Dark Matter", author="Blake Crouch")) is None
    assert quelle.client.requests == []


def test_a_resolved_entry_becomes_an_observation() -> None:
    quelle = source(fixture("title.json"))
    eintrag = WatchlistEntry(
        title="Dark Matter",
        author="Blake Crouch",
        resolved_links={"overdrive": "https://voebb.overdrive.com/media/3222096"},
    )

    beobachtung = quelle.check(eintrag)

    assert beobachtung.source_item_id == "3222096"
    # Der Titel, wie OverDrive ihn nennt — eine falsche Zuordnung muss sichtbar
    # werden (ADR 9).
    assert beobachtung.title == "Der Zeitenläufer (Dark Matter)"
    assert beobachtung.match_reason is MatchReason.WATCHLIST
    assert beobachtung.availability is Availability.UNAVAILABLE
    assert beobachtung.reservation_count == 8
    assert beobachtung.isbn == "9783641171421"
    assert beobachtung.url == "https://voebb.overdrive.com/media/3222096"


def test_a_link_we_cannot_key_is_refused() -> None:
    """Der Snapshot ist auf die Nummer geschlüsselt. Eine erfundene spaltete
    die Geschichte eines Titels still in zwei."""
    quelle = source(fixture("title.json"))
    eintrag = WatchlistEntry(
        title="Dark Matter", resolved_links={"overdrive": "https://voebb.overdrive.com/media/"}
    )

    with pytest.raises(SourceStructureError, match="Titelnummer"):
        quelle.check(eintrag)


def test_a_vanished_title_skips_that_entry_instead_of_failing_the_source() -> None:
    from ebook_watchlist.http import NotFound

    class Weg:
        def get(self, url, params=None):
            raise NotFound(url)

    quelle = OverdriveSource(client=Weg())
    eintrag = WatchlistEntry(
        title="Dark Matter", resolved_links={"overdrive": "https://voebb.overdrive.com/media/1"}
    )

    assert quelle.check(eintrag) is None


def test_the_title_id_comes_out_of_the_reader_facing_url() -> None:
    assert title_id_from_url("https://voebb.overdrive.com/media/3222096") == "3222096"
    assert title_id_from_url("https://voebb.overdrive.com/media/3222096/") == "3222096"
    assert title_id_from_url("https://voebb.overdrive.com/media/keine-nummer") is None
