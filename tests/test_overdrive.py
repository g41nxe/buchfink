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
    found = parse.parse_search(fixture("search-hits.json"))

    assert [(c.title, c.author, c.title_id) for c in found] == [
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
    overdrive = source(fixture("search-hits.json"))

    resolution = overdrive.resolve(
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
    overdrive = source(fixture("search-hits.json"))

    resolution = overdrive.resolve(WatchlistEntry(title="Dark Matter", author="Blake Crouch"))

    assert resolution.confidence is not Confidence.AUTO_ACCEPT


def test_a_candidate_brings_its_cover() -> None:
    """Bei einer offenen Zuordnung entscheidet das Auge, welcher Treffer der
    richtige ist (Ticket 41). Die Karte trägt das Bild längst — weitergereicht
    wurde es nicht, und in der Auswahl stand ein Platzhalter."""
    overdrive = source(fixture("search-hits.json"))

    resolution = overdrive.resolve(
        WatchlistEntry(title="Dark Matter", author="Blake Crouch", isbn="9783641171421")
    )

    assert resolution.accepted.cover_url is not None


def test_an_unknown_title_resolves_to_nothing() -> None:
    overdrive = source(fixture("search-no-hits.json"))

    assert overdrive.resolve(WatchlistEntry(title="Gibt es nicht", author="Niemand")) is None


def test_the_query_carries_title_and_surname() -> None:
    overdrive = source(fixture("search-hits.json"))

    overdrive.resolve(WatchlistEntry(title="Dark Matter", author="Blake Crouch"))

    _, params = overdrive.client.requests[0]
    assert params["query"] == "Dark Matter Crouch"
    # Nur deutsche EPUB-E-Books, wie bei der Onleihe.
    assert params["format"] == "ebook-epub-adobe"
    assert params["language"] == "de"


# --- Sprache bei einem benannten Titel (#77) --------------------------------


class ScriptedClient:
    """Antwortet der Reihe nach; die letzte Antwort gilt für alles Weitere."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]


def card(title: str, author: str, isbn: str, title_id: str, language: str) -> dict:
    """Eine Trefferkarte in der Gestalt der aufgezeichneten, mit anderen Werten.

    Die Suche nach *Scythe* wurde am 25.09.2026 nur im Browser nachgestellt,
    nicht aufgezeichnet — die Karte ist deshalb der aufgezeichneten nachgebaut
    statt erfunden.
    """
    item = json.loads(fixture("search-hits.json"))["items"][0]
    for format_ in item["formats"]:
        if format_.get("isbn"):
            format_["isbn"] = isbn
    names = {"en": "English", "de": "German"}
    return item | {
        "id": title_id,
        "title": title,
        "sortTitle": title,
        "firstCreatorName": author,
        "languages": [{"id": language, "name": names.get(language, language)}],
    }


def answer(*cards: dict) -> str:
    return json.dumps({"items": list(cards), "totalItems": len(cards)})


@pytest.fixture
def context(store):
    from datetime import datetime

    from ebook_watchlist.sources.base import RunContext

    return RunContext(profile_slug="test", store=store, now=datetime(2026, 9, 26, 6, 0))


SCYTHE = WatchlistEntry(title="Scythe", author="Neal Shusterman")
ENGLISH = card("Scythe", "Neal Shusterman", "9781442472426", "1911111", "en")


def test_a_card_says_which_language_it_is_in() -> None:
    found = parse.parse_search(answer(ENGLISH))

    assert found[0].language == "eng"
    # Die aufgezeichnete Karte ist deutsch.
    assert parse.parse_search(fixture("search-hits.json"))[0].language == "ger"


def test_a_named_title_is_searched_once_more_in_every_language(context) -> None:
    """Abnahme: ein englischer Titel, den die Bibliothek nur auf Englisch
    führt, wird gefunden. Der Sprachfilter ist für Funde richtig, für einen
    Titel, den die Leserin selbst benannt hat, nicht (#10, #77)."""
    overdrive = OverdriveSource(client=ScriptedClient(fixture("search-no-hits.json"),
                                                   answer(ENGLISH)))

    linked = overdrive.linked_entry(SCYTHE, context)

    assert linked.resolved_links["overdrive"] == "https://voebb.overdrive.com/media/1911111"
    german_params, all_params = (params for _, params in overdrive.client.requests)
    assert german_params["language"] == "de"
    assert "language" not in all_params
    # Das Format bleibt: ein Hörbuch ist auch in jeder Sprache kein E-Book.
    assert all_params["format"] == "ebook-epub-adobe"


def test_the_language_of_an_accepted_edition_is_remembered(context) -> None:
    """Die Kachel soll sagen können, dass die Ausgabe englisch ist."""
    overdrive = OverdriveSource(client=ScriptedClient(fixture("search-no-hits.json"),
                                                   answer(ENGLISH)))

    overdrive.linked_entry(SCYTHE, context)

    link = context.store.get_book_source(context.book_for(SCYTHE), "overdrive")
    assert json.loads(link.details)["language"] == "eng"


def test_a_german_find_needs_no_second_search(context) -> None:
    """Deutsch zuerst, wie bisher — und wenn das reicht, bleibt es dabei."""
    overdrive = OverdriveSource(client=ScriptedClient(fixture("search-hits.json")))

    overdrive.linked_entry(WatchlistEntry(title="Der Zeitenläufer", author="Blake Crouch"), context)

    assert len(overdrive.client.requests) == 1


def test_nothing_in_any_language_is_still_an_answer(context) -> None:
    overdrive = OverdriveSource(client=ScriptedClient(fixture("search-no-hits.json")))

    assert overdrive.linked_entry(SCYTHE, context) is None
    link = context.store.get_book_source(context.book_for(SCYTHE), "overdrive")
    assert json.loads(link.details)["outcome"] == "not_found"


# --- Prüfung ----------------------------------------------------------------


def test_an_unresolved_entry_is_skipped_not_guessed() -> None:
    overdrive = source(fixture("title.json"))

    assert overdrive.check(WatchlistEntry(title="Dark Matter", author="Blake Crouch")) is None
    assert overdrive.client.requests == []


def test_a_resolved_entry_becomes_an_observation() -> None:
    overdrive = source(fixture("title.json"))
    entry = WatchlistEntry(
        title="Dark Matter",
        author="Blake Crouch",
        resolved_links={"overdrive": "https://voebb.overdrive.com/media/3222096"},
    )

    observation = overdrive.check(entry)

    assert observation.source_item_id == "3222096"
    # Der Titel, wie OverDrive ihn nennt — eine falsche Zuordnung muss sichtbar
    # werden (ADR 9).
    assert observation.title == "Der Zeitenläufer (Dark Matter)"
    assert observation.match_reason is MatchReason.WATCHLIST
    assert observation.availability is Availability.UNAVAILABLE
    assert observation.reservation_count == 8
    assert observation.isbn == "9783641171421"
    assert observation.url == "https://voebb.overdrive.com/media/3222096"


def test_a_link_we_cannot_key_is_refused() -> None:
    """Der Snapshot ist auf die Nummer geschlüsselt. Eine erfundene spaltete
    die Geschichte eines Titels still in zwei."""
    overdrive = source(fixture("title.json"))
    entry = WatchlistEntry(
        title="Dark Matter", resolved_links={"overdrive": "https://voebb.overdrive.com/media/"}
    )

    with pytest.raises(SourceStructureError, match="Titelnummer"):
        overdrive.check(entry)


def test_a_vanished_title_skips_that_entry_instead_of_failing_the_source() -> None:
    from ebook_watchlist.http import NotFound

    class Gone:
        def get(self, url, params=None):
            raise NotFound(url)

    overdrive = OverdriveSource(client=Gone())
    entry = WatchlistEntry(
        title="Dark Matter", resolved_links={"overdrive": "https://voebb.overdrive.com/media/1"}
    )

    assert overdrive.check(entry) is None


def test_the_title_id_comes_out_of_the_reader_facing_url() -> None:
    assert title_id_from_url("https://voebb.overdrive.com/media/3222096") == "3222096"
    assert title_id_from_url("https://voebb.overdrive.com/media/3222096/") == "3222096"
    assert title_id_from_url("https://voebb.overdrive.com/media/keine-nummer") is None


# --- Lucky Day als Vorschlagsquelle (#74) -------------------------------------------------
#
# Aufgezeichnet am 26.09.2026: die Sammlung „Lucky Day" der VÖBB, 15 Titel —
# englisch und deutsch, E-Books und Hörbücher, Belletristik und Sachbuch.


def lucky_day() -> str:
    return fixture("collection-lucky-day.json")


def test_lucky_day_yields_german_fiction_ebooks_only() -> None:
    from ebook_watchlist.sources.overdrive.source import Collection

    discoveries = parse.parse_collection(
        parse.payload(lucky_day()), Collection("1572172", "Lucky Day")
    )

    assert {f.title for f in discoveries} == {"Schaut, wie wir tanzen", "Der Hausmann",
                                        "Steinernes Fleisch"}
    for discovery in discoveries:
        assert discovery.match_reason is MatchReason.GENRE_CATEGORY
        assert discovery.category == "Lucky Day"
        # Lucky Day heißt: sofort ausleihbar, ohne Wartezeit.
        assert discovery.availability is Availability.AVAILABLE
        assert discovery.isbn and discovery.url.startswith("https://voebb.overdrive.com/media/")


def test_a_collection_can_narrow_to_genres() -> None:
    """Die BISAC-Präfixe engen weiter ein: FIC009 ist Fantasy."""
    from ebook_watchlist.sources.overdrive.source import Collection

    discoveries = parse.parse_collection(parse.payload(lucky_day()),
                                   Collection("1572172", "Lucky Day", ("FIC009",)))

    assert [f.title for f in discoveries] == ["Steinernes Fleisch"]


def test_a_collection_without_items_is_a_changed_interface() -> None:
    from ebook_watchlist.sources.overdrive.source import Collection

    with pytest.raises(SourceStructureError):
        parse.parse_collection({"title": "Lucky Day"}, Collection("1572172", "Lucky Day"))


def test_the_run_collects_the_collection_next_to_the_watchlist(tmp_path) -> None:
    from datetime import datetime

    from ebook_watchlist.config import load_settings
    from ebook_watchlist.sources.base import RunContext
    from ebook_watchlist.sources.overdrive.source import Collection
    from ebook_watchlist.store import Store

    client = StubClient(lucky_day())
    overdrive = OverdriveSource(client=client, collections=(Collection("1572172", "Lucky Day"),))
    context = RunContext(profile_slug="t", store=Store(tmp_path / "s.db"),
                         now=datetime(2026, 9, 26, 12, 0))

    discoveries = overdrive.collect(load_settings(), [], context)

    assert len(discoveries) == 3
    assert client.requests[0][0].endswith("/libraries/voebb/collections/1572172")


def test_the_collection_is_read_from_the_settings() -> None:
    from ebook_watchlist.config import ConfigError
    from ebook_watchlist.sources.overdrive.source import Collection
    from ebook_watchlist.sources.registry import _build_overdrive

    overdrive = _build_overdrive("overdrive", {"collections": [
        {"id": 1572172, "name": "Lucky Day", "bisac": ["FIC"]}]}, StubClient(""))

    assert overdrive.collections == (Collection("1572172", "Lucky Day", ("FIC",)),)
    with pytest.raises(ConfigError):
        _build_overdrive("overdrive", {"collections": [{"name": "ohne Nummer"}]}, StubClient(""))



def test_a_broken_collection_costs_the_collection_not_the_watchlist(tmp_path) -> None:
    """Zieht die Bibliothek eine Sammlung zurück, prüft die Quelle weiter (Review)."""
    from datetime import datetime

    from ebook_watchlist.config import load_settings
    from ebook_watchlist.http import NotFound
    from ebook_watchlist.sources.base import RunContext
    from ebook_watchlist.sources.overdrive.source import Collection
    from ebook_watchlist.store import Store

    class Gone:
        def get(self, url, params=None):
            raise NotFound(url)

    quelle = OverdriveSource(client=Gone(), collections=(Collection("1", "Weg"),))
    context = RunContext(profile_slug="t", store=Store(tmp_path / "s.db"),
                         now=datetime(2026, 9, 26, 12, 0))

    assert quelle.collect(load_settings(), [], context) == []



# --- Autor:innen und Themen (#74, Scheibe 3 und 4) ----------------------------------------


def test_an_author_is_searched_among_free_german_ebooks() -> None:
    client = StubClient(fixture("search-hits.json"))
    quelle = OverdriveSource(client=client)

    funde = quelle.by_author("Blake Crouch")

    url, params = client.requests[0]
    assert params["query"] == "Blake Crouch" and params["showOnlyAvailable"] == "true"
    assert params["language"] == "de"
    assert [f.title for f in funde] == ["Der Zeitenläufer (Dark Matter)"]
    assert funde[0].match_reason is MatchReason.PROFILE_AUTHOR
    assert funde[0].isbn


def test_a_book_by_someone_else_is_not_an_author_find() -> None:
    quelle = OverdriveSource(client=StubClient(fixture("search-hits.json")))

    assert quelle.by_author("Simon Beckett") == []


def test_a_genre_category_is_searched_as_newly_added_by_subject() -> None:
    """Thema → OverDrive-Thema: Psychothriller ist Thriller (100)."""
    client = StubClient(fixture("search-hits.json"))
    quelle = OverdriveSource(client=client)

    funde = quelle.by_category("belletristik/krimi-thriller/psychothriller")

    _, params = client.requests[0]
    assert params["subject"] == "100" and params["sortBy"] == "newlyadded"
    assert params["showOnlyAvailable"] == "true"
    assert funde and funde[0].match_reason is MatchReason.GENRE_CATEGORY
    assert funde[0].category == "belletristik/krimi-thriller/psychothriller"


def test_a_genre_without_a_subject_asks_nothing() -> None:
    client = StubClient(fixture("search-hits.json"))

    assert OverdriveSource(client=client).by_category("belletristik/liebesromane") == []
    assert client.requests == []


def test_childrens_books_and_markup_do_not_become_finds() -> None:
    """Das Thema Science-Fiction schließt Kinderbücher ein (Minecraft), und
    manche Titel tragen HTML („Star Wars<sup>TM</sup>")."""
    item = json.loads(fixture("search-hits.json"))["items"][0]
    kind = dict(item, bisacCodes=["JUV039000"])
    markiert = dict(item, title="Star Wars<sup>TM</sup> Herrschaft")

    assert parse.observation_of(kind, source="overdrive",
                                reason=MatchReason.GENRE_CATEGORY) is None
    assert parse.observation_of(markiert, source="overdrive",
                                reason=MatchReason.GENRE_CATEGORY).title == "Star WarsTM Herrschaft"


def test_a_genre_category_find_must_be_fiction() -> None:
    """Im Thema Science-Fiction stand ein Sachbuch über den Ursprung des
    Universums (Lauf vom 26.09.2026): ein Thema der Leserin ist Belletristik."""
    from ebook_watchlist.sources.overdrive.parse import parse_finds

    data = parse.payload(fixture("collection-lucky-day.json"))
    funde = parse_finds(data, source="overdrive", reason=MatchReason.GENRE_CATEGORY,
                        category="belletristik/science-fiction")

    titel = {f.title for f in funde}
    # Ein deutsches E-Book, aber ein Sachbuch (POL) — und eines über Ernährung (CKB).
    assert "Ungleich vereint" not in titel and "Der Glukose-Trick" not in " ".join(titel)
    assert "Der Hausmann" in titel
