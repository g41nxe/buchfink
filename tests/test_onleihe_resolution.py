"""Automatic resolution: a bare title and author become a pinned detail page."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ebook_watchlist.config import Settings, WatchlistEntry
from ebook_watchlist.matching import Confidence
from ebook_watchlist.sources.base import RESOLUTION_RETRY_AFTER, RunContext
from ebook_watchlist.sources.onleihe import selectors as sel
from ebook_watchlist.sources.onleihe.source import OnleiheSource
from ebook_watchlist.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "onleihe"
NOW = datetime(2026, 9, 4, 6, 0)

RILEY = "mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ScriptedClient:
    """Answers each GET from a queue, so a multi-page walk can be scripted."""

    def __init__(self, *pages: str) -> None:
        self.pages = list(pages)
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]


@pytest.fixture
def context(tmp_path: Path) -> RunContext:
    return RunContext(profile_slug="test", store=Store(tmp_path / "s.db"), now=NOW)


def source(*pages: str, **kwargs) -> OnleiheSource:
    return OnleiheSource(client=ScriptedClient(*pages), **kwargs)  # type: ignore[arg-type]


# --- the search query -----------------------------------------------------


def test_only_the_surname_goes_into_the_single_search_box() -> None:
    onleihe = source(fixture("search-hits.html"))
    assert onleihe._query_for(WatchlistEntry(title="Der Schwarm", author="Frank Schätzing")) == (
        "Der Schwarm Schätzing"
    )
    assert onleihe._query_for(WatchlistEntry(title="Der Schwarm", author="Schätzing, Frank")) == (
        "Der Schwarm Schätzing"
    )
    assert onleihe._query_for(WatchlistEntry(title="Der Schwarm")) == "Der Schwarm"


def test_the_search_is_a_get_with_the_query_in_the_url() -> None:
    onleihe = source(fixture("search-hits.html"))
    onleihe.resolve(WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley"))

    url, params = onleihe.client.requests[0]  # type: ignore[attr-defined]
    assert url.endswith(sel.SEARCH_PATH)
    assert params["pText"] == "Die sieben Schwestern Riley"
    assert params["cmdId"] == "703"


# --- the resolution decision ----------------------------------------------


def test_a_confident_hit_resolves_to_its_detail_page() -> None:
    onleihe = source(fixture("search-hits.html"))
    resolution = onleihe.resolve(
        WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley")
    )

    assert resolution is not None
    assert resolution.confidence is Confidence.AUTO_ACCEPT, resolution.reason
    assert resolution.accepted is not None
    assert resolution.accepted.payload.endswith(RILEY)


def test_the_ebook_is_preferred_over_the_audiobook_of_the_same_novel() -> None:
    """Both are listed under the identical title and author; without a format
    preference the matcher can only call it a tie and nothing ever resolves."""
    onleihe = source(fixture("search-hits.html"), media=("ic_eaudio",))
    resolution = onleihe.resolve(
        WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley")
    )

    assert resolution is not None
    assert resolution.accepted is not None
    assert not resolution.accepted.payload.endswith(RILEY)


def test_a_format_nobody_stocks_falls_back_instead_of_vanishing() -> None:
    onleihe = source(fixture("search-hits.html"), media=("ic_evideo",))
    resolution = onleihe.resolve(
        WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley")
    )
    assert resolution is not None
    assert resolution.ranked


def test_no_hits_means_not_in_this_catalogue_not_an_error() -> None:
    onleihe = source(fixture("search-no-hits.html"))
    assert onleihe.resolve(WatchlistEntry(title="Project Hail Mary", author="Andy Weir")) is None


def test_a_wrong_looking_hit_is_not_accepted() -> None:
    onleihe = source(fixture("search-hits.html"))
    entry = WatchlistEntry(title="Kochen mit Kräutern", author="Erika Mustermann")
    resolution = onleihe.resolve(entry)

    assert resolution is not None
    assert resolution.confidence is Confidence.NO_MATCH
    assert resolution.accepted is None


def test_resolution_stops_after_the_first_page_when_it_is_already_sure() -> None:
    onleihe = source(fixture("search-hits.html"))
    onleihe.resolve(WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley"))
    assert len(onleihe.client.requests) == 1  # type: ignore[attr-defined]


# --- caching and the attention list ---------------------------------------


def test_a_resolved_link_is_remembered_and_not_searched_again(context: RunContext) -> None:
    onleihe = source(fixture("search-hits.html"))
    entry = WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley")

    first = onleihe.linked_entry(entry, context)
    assert first is not None
    assert first.resolved_links["onleihe"].endswith(RILEY)
    assert len(onleihe.client.requests) == 1  # type: ignore[attr-defined]

    second = onleihe.linked_entry(entry, context)
    assert second is not None
    assert second.resolved_links == first.resolved_links
    assert len(onleihe.client.requests) == 1  # type: ignore[attr-defined]


def test_a_hand_pinned_link_is_never_second_guessed(context: RunContext) -> None:
    onleihe = source(fixture("search-hits.html"))
    entry = WatchlistEntry(
        title="Irgendwas", resolved_links={"onleihe": "mediaInfo,0-0-1-200-0.html"}
    )

    linked = onleihe.linked_entry(entry, context)

    assert linked is entry
    assert onleihe.client.requests == []  # type: ignore[attr-defined]


def test_an_unresolvable_entry_is_named_in_the_digest_and_skipped(context: RunContext) -> None:
    onleihe = source(fixture("search-hits.html"))
    entry = WatchlistEntry(title="Die sieben Schwestern", author="Jemand Anders")

    assert onleihe.linked_entry(entry, context) is None
    assert len(context.attention) == 1
    assert context.attention[0].entry_title == "Die sieben Schwestern"
    assert context.attention[0].source == "onleihe"
    assert context.attention[0].reason


def test_a_failed_lookup_is_not_repeated_on_the_next_run(context: RunContext) -> None:
    onleihe = source(fixture("search-no-hits.html"))
    entry = WatchlistEntry(title="Project Hail Mary", author="Andy Weir")

    assert onleihe.linked_entry(entry, context) is None
    assert len(onleihe.client.requests) == 1  # type: ignore[attr-defined]

    assert onleihe.linked_entry(entry, context) is None
    assert len(onleihe.client.requests) == 1  # type: ignore[attr-defined]
    # A cached miss must not nag every single day.
    assert context.attention == []


def test_a_stale_miss_gets_another_chance(context: RunContext) -> None:
    onleihe = source(fixture("search-no-hits.html"))
    entry = WatchlistEntry(title="Project Hail Mary", author="Andy Weir")
    onleihe.linked_entry(entry, context)

    context.now = NOW + RESOLUTION_RETRY_AFTER + timedelta(seconds=1)
    onleihe.linked_entry(entry, context)

    assert len(onleihe.client.requests) == 2  # type: ignore[attr-defined]


def test_the_stored_candidates_carry_their_cover(context: RunContext) -> None:
    """Die Naht von der Aufloesung bis in die Zeile (#39).

    Die Auswahl bei einer unklaren Zuordnung zeigt Bilder (Ticket 41). Ob die
    Adresse dort ankommt, pruefte bisher niemand: die Tests hoerten am Parser
    auf und setzten erst bei handgeschriebenem JSON wieder an. Als spaeter
    Kandidaten ohne Bild auffielen, war deshalb nicht zu sagen, ob der Weg
    kaputt ist oder die Zeilen nur aelter sind als die Funktion.
    """
    import json

    onleihe = source(fixture("search-hits.html"))
    entry = WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley")

    onleihe.linked_entry(entry, context)

    row = context.store.get_book_source(context.book_for(entry), "onleihe")
    candidates = json.loads(row.details or "{}").get("candidates") or []
    assert candidates, "die Aufloesung hat keine Kandidaten festgehalten"
    assert all(k["cover_url"] for k in candidates)


def test_rejecting_candidates_does_not_move_the_retry_window(context: RunContext) -> None:
    """Ein Klick der Leserin verschiebt keinen Zeitpunkt, der die Aufloesung
    meint (#39).

    Bis hierher setzte jedes "Nichts passt" ``resolved_at`` auf jetzt — und
    damit die naechste Suche um weitere sieben Tage nach hinten. Gerade dann
    also, wenn die bisherigen Treffer nachweislich falsch waren.
    """
    onleihe = source(fixture("search-no-hits.html"))
    entry = WatchlistEntry(title="Project Hail Mary", author="Andy Weir")
    onleihe.linked_entry(entry, context)

    # Drei Tage spaeter lehnt die Leserin ab, was ihr vorgelegt wurde.
    context.store.reject_candidates(
        context.book_for(entry), "onleihe", ["https://example.invalid/1"]
    )

    # Sieben Tage nach der *Aufloesung* wird wieder gesucht, nicht sieben Tage
    # nach der Ablehnung.
    context.now = NOW + RESOLUTION_RETRY_AFTER + timedelta(seconds=1)
    onleihe.linked_entry(entry, context)

    assert len(onleihe.client.requests) == 2  # type: ignore[attr-defined]


def test_editing_the_entry_forces_a_fresh_lookup(context: RunContext) -> None:
    """Resolutions are keyed on title+author, so correcting either re-resolves."""
    onleihe = source(fixture("search-no-hits.html"))
    onleihe.linked_entry(WatchlistEntry(title="Projekt Hail Mary", author="Andy Weir"), context)
    onleihe.linked_entry(WatchlistEntry(title="Project Hail Mary", author="Andy Weir"), context)
    assert len(onleihe.client.requests) == 2  # type: ignore[attr-defined]


# --- through collect() ----------------------------------------------------


def test_collect_resolves_then_reads_availability(context: RunContext) -> None:
    onleihe = source(fixture("search-hits.html"), fixture("detail-unavailable.html"))
    entry = WatchlistEntry(title="Die sieben Schwestern", author="Lucinda Riley")

    observations = onleihe.collect(Settings(slug="test", name="Test"), [entry], context)

    assert len(observations) == 1
    assert observations[0].source_item_id == "373164461"
    assert observations[0].reservation_count == 16
